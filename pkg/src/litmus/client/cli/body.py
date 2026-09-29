"""Request bodies from the command line: generated options, `--body`, and `$VARIABLE`s.

Each JSON body field of a route's OpenAPI schema is an option: `--name` for a top-level
field, and for a field of a nested object (`binding.network`) its own name when free, else
`--binding-network`. `--body` gives the whole body (JSON, `@file`, or `-` for stdin) and
options override its fields. A string that is exactly `$NAME` or `${NAME}` is read from
the environment or the `.env` beside `litmus.toml` (policy 02 interfaces Rule 8.2);
credential routes accept secrets only that way or from a `--body` file, never typed on
the command line (access Rule 15).
"""

import argparse
from collections.abc import Mapping
import json
from pathlib import Path
import re
import sys
from typing_extensions import Any, cast

from litmus.client.cli.commands import Command
from litmus.client.cli.index import Body, Field, escaped
from litmus.client.models import JsonObject, JsonValue

RESERVED = {
  'url',
  'tenant',
  'json',
  'portfolio',
  'service',
  'output',
  'all',
  'all-pages',
  'detach',
  'body',
  'help',
  'idempotency-key',
}
"""Option names the CLI itself uses."""
REFERENCE = re.compile(r'^\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))$')
SECRET_ROUTES = ('/credentials',)
"""Routes whose body fields are secrets (access Rule 15)."""


def option_names(fields: list[Field], taken: set[str]) -> list[tuple[str, Field]]:
  """Each field's option name, without colliding with `taken` or each other."""
  chosen: list[tuple[str, Field]] = []
  used = set(taken) | RESERVED
  for field in fields:
    short = field['path'][-1].replace('_', '-')
    name = short if short not in used else '-'.join(field['path']).replace('_', '-')
    if name in used:
      continue
    used.add(name)
    chosen.append((name, field))
  return chosen


def converter(field: Field) -> Any:
  """The argparse type of a field."""
  return {'integer': int, 'number': float}.get(field['type'], str)


def add_body(
  parser: argparse.ArgumentParser,
  command: Command,
  body: Body,
  taken: set[str],
):
  """Options for a JSON body, plus `--body`; a multipart body takes files."""
  if body['media'].startswith('multipart/'):
    parser.add_argument('files', nargs='+', type=Path, help='Files to upload.')
    return
  fields = [
    f for f in body['fields'] if not command.fields or f['path'][-1] in command.fields
  ]
  extra: list[Field] = [
    {
      'path': [name],
      'type': 'string',
      'repeated': False,
      'choices': [],
      'required': False,
      'help': '',
    }
    for name in command.extra
  ]
  if command.body is None:
    for name, field in option_names(fields + extra, taken):
      text = escaped(field['help'])
      if command.path.endswith(SECRET_ROUTES):
        text += ' (as $VARIABLE, from the environment or .env)'
      options: dict[str, Any] = {
        'dest': 'b_' + '.'.join(field['path']),
        'help': text or None,
      }
      if field['type'] != 'boolean' and not field['choices']:
        options['metavar'] = name.upper().replace('-', '_')
      if field['type'] == 'boolean':
        options['action'] = argparse.BooleanOptionalAction
      else:
        options['type'] = converter(field)
        if field['repeated']:
          options['action'] = 'append'
        if field['choices']:
          options['choices'] = field['choices']
      parser.add_argument(f'--{name}', **options)
  parser.add_argument(
    '--body',
    help='The whole JSON body, @FILE, or - for stdin; options override its fields.',
  )


def dotenv(path: Path) -> dict[str, str]:
  """`NAME=value` lines of a dotenv file, unquoted."""
  values: dict[str, str] = {}
  if not path.is_file():
    return values
  for line in path.read_text().splitlines():
    line = line.strip()
    if not line or line.startswith('#'):
      continue
    key, separator, value = line.removeprefix('export ').partition('=')
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
      value = value[1:-1]
    if separator:
      values[key.strip()] = value
  return values


def resolved(value: JsonValue, lookup: Mapping[str, str]) -> JsonValue:
  """`value` with every `$NAME` string replaced from `lookup`.

  Raises:
    ValueError: A referenced variable is not set.
  """
  if isinstance(value, str):
    match = REFERENCE.match(value)
    if not match:
      return value
    name = match.group(1) or match.group(2)
    if name not in lookup:
      raise ValueError(f'${name} is not set in the environment or .env')
    return lookup[name]
  if isinstance(value, list):
    return [resolved(v, lookup) for v in value]
  if isinstance(value, dict):
    return {k: resolved(v, lookup) for k, v in value.items()}
  return value


def read_body(text: str) -> JsonValue:
  """`--body`: JSON, `@file`, or `-` for stdin."""
  if text == '-':
    text = sys.stdin.read()
  elif text.startswith('@'):
    text = Path(text[1:]).read_text()
  try:
    return cast(JsonValue, json.loads(text))
  except json.JSONDecodeError as error:
    raise ValueError(f'--body is not JSON: {error}') from error


def build(
  args: argparse.Namespace,
  command: Command,
  path: str,
  lookup: Mapping[str, str],
) -> JsonValue:
  """The request body: the command's fixed body, else `--body` with options over it.

  Raises:
    ValueError: A typed secret, a missing variable, or a `--body` that is not an object.
  """
  if command.body is not None:
    return cast(JsonValue, dict(command.body))
  given = getattr(args, 'body', None)
  body = read_body(given) if given else None
  secret = path.endswith(SECRET_ROUTES)
  options = {
    k.removeprefix('b_'): v
    for k, v in vars(args).items()
    if k.startswith('b_') and v is not None
  }
  if not options:
    return resolved(body, lookup) if body is not None else None
  if body is None:
    body = {}
  if not isinstance(body, dict):
    raise ValueError('--body must be a JSON object when options are given')
  for dotted, value in options.items():
    if secret and not (isinstance(value, str) and REFERENCE.match(value)):
      raise ValueError(
        f'Give --{dotted.rsplit(".", 1)[-1].replace("_", "-")} as $VARIABLE '
        '(read from the environment or .env) or in a --body file, never typed'
      )
    target: JsonObject = body
    *parents, last = dotted.split('.')
    for parent in parents:
      child = target.setdefault(parent, {})
      if not isinstance(child, dict):
        raise ValueError(f'--body field {parent} is not an object')
      target = child
    target[last] = cast(JsonValue, value)
  return resolved(body, lookup)


def lookup(
  environ: Mapping[str, str], config: Path | None, cwd: Path
) -> dict[str, str]:
  """Variables for `$NAME`: `.env` beside `litmus.toml` (or here), then the environment."""
  directory = config.parent if config else cwd
  return {**dotenv(directory / '.env'), **environ}
