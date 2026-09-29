"""Keep the committed OpenAPI snapshots and the CLI's route index current.

Policy 02 interfaces Rule 5: OpenAPI is the source of truth, CLI help is generated from
it, and committed snapshots with a drift check fail the build on any change.

  python scripts/openapi.py fetch [--url URL]   # snapshot every service into openapi/
  python scripts/openapi.py fetch --check [--url URL]  # fail if a deployment drifted
  python scripts/openapi.py index [--check]     # regenerate (or check) the route index

`openapi/<service>.json` are the snapshots. The index,
`pkg/src/litmus/client/cli/routes.json`, holds per route what the CLI needs: summary,
query parameters, body fields (nested objects flattened one level, unions merged), and
whether the route answers a job or a binary stream. `scripts/check.py` runs
`index --check`.
"""

import argparse
import json
from pathlib import Path
import sys
from typing_extensions import Any
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / 'openapi'
INDEX = ROOT / 'pkg/src/litmus/client/cli/routes.json'
SERVICES = ('platform', 'portfolio', 'evm', 'hl', 'dydx', 'cex')
METHODS = ('get', 'post', 'put', 'patch', 'delete')
SCALARS = ('string', 'integer', 'number', 'boolean')


def dump(value: Any) -> str:
  """Stable JSON text for a committed file."""
  return json.dumps(value, indent=2, ensure_ascii=False) + '\n'


def fetch(url: str, *, check: bool) -> int:
  """Write each service's served document to `openapi/`, or report drift with `check`."""
  drifted = []
  for service in SERVICES:
    with urllib.request.urlopen(
      f'{url.rstrip("/")}/v1/{service}/openapi.json'
    ) as answer:
      text = dump(json.load(answer))
    path = SNAPSHOTS / f'{service}.json'
    if path.exists() and path.read_text() == text:
      continue
    drifted.append(service)
    if not check:
      SNAPSHOTS.mkdir(exist_ok=True)
      path.write_text(text)
  for service in drifted:
    print(f'{"drifted" if check else "wrote"} openapi/{service}.json')
  return 1 if check and drifted else 0


class Document:
  """One OpenAPI document, with `$ref` resolution."""

  def __init__(self, data: dict[str, Any]):
    """Keep the document."""
    self.data = data

  def resolve(self, schema: dict[str, Any]) -> dict[str, Any]:
    """A schema with its `$ref` followed, and `X | null` reduced to `X`."""
    while '$ref' in schema:
      name = schema['$ref'].rsplit('/', 1)[-1]
      schema = self.data['components']['schemas'][name]
    options = schema.get('anyOf') or []
    others = [o for o in options if o.get('type') != 'null']
    if options and len(others) == 1 and len(others) < len(options):
      merged = {k: v for k, v in schema.items() if k != 'anyOf'}
      return {**self.resolve(others[0]), **merged}
    return schema

  def variants(self, schema: dict[str, Any]) -> list[dict[str, Any]]:
    """The object variants of a schema: itself, or each member of a union."""
    schema = self.resolve(schema)
    members = schema.get('oneOf') or schema.get('anyOf')
    if members:
      return [v for m in members for v in self.variants(m)]
    return [schema] if schema.get('type') == 'object' or 'properties' in schema else []

  def kind(self, schema: dict[str, Any]) -> tuple[str, bool, list[str]] | None:
    """`(type, repeated, choices)` of a scalar or scalar-array schema, else `None`."""
    schema = self.resolve(schema)
    if schema.get('type') == 'array':
      inner = self.kind(schema.get('items', {}))
      return (inner[0], True, inner[2]) if inner and not inner[1] else None
    choices = [str(c) for c in schema.get('enum', [])]
    if 'const' in schema:
      choices = [str(schema['const'])]
    if schema.get('type') in SCALARS:
      return schema['type'], False, choices
    members = schema.get('anyOf') or schema.get('oneOf') or []
    kinds = [self.kind(m) for m in members]
    if members and all(k and not k[1] for k in kinds):
      return 'string', False, [c for k in kinds if k for c in k[2]]
    if choices:
      return 'string', False, choices
    return None

  def fields(self, schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Body fields: scalar properties, and one level of nested object properties."""
    found: dict[str, dict[str, Any]] = {}
    variants = self.variants(schema)
    for variant in variants:
      required = set(variant.get('required', []))
      for name, value in variant.get('properties', {}).items():
        kind = self.kind(value)
        entries: list[tuple[list[str], tuple[str, bool, list[str]], bool, str]] = []
        if kind:
          entries.append(([name], kind, name in required, self.help(value)))
        else:
          for nested in self.variants(value):
            inner_required = set(nested.get('required', []))
            for key, inner in nested.get('properties', {}).items():
              inner_kind = self.kind(inner)
              if inner_kind:
                entries.append(
                  ([name, key], inner_kind, key in inner_required, self.help(inner))
                )
        for path, (type_, repeated, choices), needed, text in entries:
          key = '.'.join(path)
          entry = found.get(key)
          if entry is None:
            found[key] = {
              'path': path,
              'type': type_,
              'repeated': repeated,
              'choices': choices,
              'required': needed and len(variants) == 1,
              'help': text,
            }
          else:
            entry['choices'] = sorted(set(entry['choices']) | set(choices))
    return list(found.values())

  @staticmethod
  def help(schema: dict[str, Any]) -> str:
    """The first line of a schema's description."""
    return (schema.get('description') or schema.get('title') or '').split('\n')[0]

  def route(self, operation: dict[str, Any]) -> dict[str, Any]:
    """What the CLI needs of one operation."""
    query = []
    for parameter in operation.get('parameters', []):
      if parameter['in'] != 'query':
        continue
      kind = self.kind(parameter.get('schema', {})) or ('string', False, [])
      query.append(
        {
          'name': parameter['name'],
          'type': kind[0],
          'repeated': kind[1],
          'choices': kind[2],
          'required': bool(parameter.get('required')),
          'help': (parameter.get('description') or '').split('\n')[0],
        }
      )
    body = None
    request = operation.get('requestBody')
    if request:
      media, content = next(iter(request['content'].items()))
      body = {
        'media': media,
        'required': bool(request.get('required')),
        'fields': self.fields(content.get('schema', {}))
        if media == 'application/json'
        else [],
      }
    success = [c for c in operation['responses'] if c.startswith('2')]
    media_types = {
      m for c in success for m in operation['responses'][c].get('content', {})
    }
    description = operation.get('description') or ''
    return {
      'summary': operation.get('summary', ''),
      'help': description.split('\n\n')[0].replace('\n', ' ')
      or operation.get('summary', ''),
      'query': query,
      'body': body,
      'job': '202' in success,
      'binary': (bool(media_types) and 'application/json' not in media_types)
      or 'application/octet-stream' in media_types,
    }


def build() -> dict[str, dict[str, Any]]:
  """The route index of every snapshot: service to `METHOD path` to route."""
  index: dict[str, dict[str, Any]] = {}
  for service in SERVICES:
    path = SNAPSHOTS / f'{service}.json'
    document = Document(json.loads(path.read_text()))
    routes = index.setdefault(service, {})
    for route, operations in document.data['paths'].items():
      for method, operation in operations.items():
        if method in METHODS:
          routes[f'{method.upper()} {route}'] = document.route(operation)
  return index


def write_index(*, check: bool) -> int:
  """Regenerate the index, or report it stale with `check`."""
  text = dump(build())
  if INDEX.exists() and INDEX.read_text() == text:
    return 0
  if check:
    print(f'{INDEX.relative_to(ROOT)} is stale: run scripts/openapi.py index')
    return 1
  INDEX.write_text(text)
  print(f'wrote {INDEX.relative_to(ROOT)}')
  return 0


def main(argv: list[str] | None = None) -> int:
  """Fetch snapshots, or build or check the index."""
  parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
  commands = parser.add_subparsers(dest='command', required=True)
  fetching = commands.add_parser('fetch', help='Snapshot every service.')
  fetching.add_argument('--url', default='http://localhost:8080')
  fetching.add_argument('--check', action='store_true', help='Only report drift.')
  indexing = commands.add_parser('index', help='Regenerate the route index.')
  indexing.add_argument('--check', action='store_true', help='Only check.')
  args = parser.parse_args(argv)
  if args.command == 'fetch':
    return fetch(args.url, check=args.check)
  return write_index(check=args.check)


if __name__ == '__main__':
  sys.exit(main())
