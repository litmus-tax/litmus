"""Running a route command: fill its path, send it, print what the route answers.

The CLI holds no business logic: it resolves names to ids (policy 02 interfaces Rule 6.2,
policy 03 contract Rule 3.4), sends one request (or one per page with `--all`), follows
jobs, and prints the body (Rule 7.2).
"""

from pathlib import Path
import re
import sys
from typing_extensions import cast
from urllib.parse import urlparse

import httpx

from litmus.client.cli.body import build, lookup
from litmus.client.cli.commands import Command
from litmus.client.cli.context import Context
from litmus.client.cli.index import PATH_PARAMETER, Route, argument, route
from litmus.client.models import Job, JsonObject, JsonValue, Problem
from litmus.client.sdk.auth import claims
from litmus.client.sdk.client import Client, Files, ProblemError
from litmus.client.sdk.jobs import collect, follow

SEGMENT = re.compile(r'^[A-Za-z0-9._:@~-]+$')
"""What a path parameter may hold: no separator, query, fragment or escape."""
UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


def required(name: str, detail: str) -> ProblemError:
  """A problem for a value the command cannot choose on its own."""
  return ProblemError(
    {
      'type': f'urn:litmus:problem:{name}-required',
      'title': f'{name.capitalize()} required',
      'status': 400,
      'detail': detail,
    }
  )


def resource_id(client: Client, unit: str, value: str) -> str:
  """A resource id from a name or an id (`GET /resources?name=`, contract Rule 3.4)."""
  if UUID.match(value):
    return value
  page = cast(
    JsonObject,
    client.request('GET', f'v1/{unit}/resources', params={'name': value}).json(),
  )
  items = page.get('items')
  if isinstance(items, list) and items and isinstance(items[0], dict):
    found = items[0].get('id')
    if isinstance(found, str):
      return found
  return value


def portfolio_id(context: Context, client: Client) -> str:
  """The portfolio: chosen, configured, or the tenant's only one."""
  chosen = getattr(context.args, 'p_portfolio_id', None) or context.connection.portfolio
  if chosen:
    return chosen
  page = cast(
    JsonObject,
    client.request('GET', 'v1/portfolio/portfolios', params={'limit': '2'}).json(),
  )
  portfolios = page.get('portfolios')
  if isinstance(portfolios, list) and len(portfolios) == 1:
    only = portfolios[0]
    if isinstance(only, dict) and isinstance(only.get('portfolio_id'), str):
      return cast(str, only['portfolio_id'])
  raise required('portfolio', 'Choose one with --portfolio or LITMUS_PORTFOLIO.')


def tenant_id(context: Context, client: Client) -> str:
  """The tenant of the connection, else of the credential being sent."""
  if context.connection.tenant:
    return context.connection.tenant
  tenant = claims(client.token or '').get('tenant')
  if isinstance(tenant, str):
    return tenant
  raise required('tenant', 'Choose one with --tenant or LITMUS_TENANT.')


def fill(context: Context, client: Client, command: Command, path: str) -> str:
  """The route with every path parameter filled in."""
  args = context.args
  values: dict[str, str] = dict(command.fixed)
  values['service'] = getattr(args, 'service', command.service)
  unit = values.get('unit') or command.service
  for name in PATH_PARAMETER.findall(path):
    if name in values:
      continue
    if name == 'portfolio_id':
      values[name] = portfolio_id(context, client)
    elif name == 'tenant_id':
      values[name] = tenant_id(context, client)
    elif name == 'resource_id':
      values[name] = resource_id(client, unit, getattr(args, f'p_{name}'))
    else:
      values[name] = getattr(args, f'p_{name}')
  for name, value in values.items():
    if not SEGMENT.match(value) or value in ('.', '..'):
      raise ValueError(f'Invalid {argument(name)}: {value!r}')
  return path.format(**values).removeprefix('/')


def query(context: Context, found: Route) -> dict[str, str | list[str]]:
  """The query parameters given on the command line."""
  params: dict[str, str | list[str]] = {}
  for parameter in found['query']:
    value = getattr(context.args, f'q_{parameter["name"]}', None)
    if value is None:
      continue
    if isinstance(value, bool):
      params[parameter['name']] = 'true' if value else 'false'
    elif isinstance(value, list):
      params[parameter['name']] = [str(v) for v in cast(list[object], value)]
    else:
      params[parameter['name']] = str(value)
  return params


def watch(context: Context, client: Client, path: str) -> Job:
  """Follow a job to its end, printing new progress and child states on stderr."""
  seen: dict[str, int] = {'progress': 0}
  children: dict[str, str] = {}

  def update(job: Job):
    """Report what changed since the last read."""
    progress = job.get('progress') or []
    for entry in progress[seen['progress'] :]:
      context.output.note(f'{entry["at"]}  {entry["message"]}')
    seen['progress'] = len(progress)
    for child in job.get('children') or []:
      if isinstance(child, dict):
        name = str(child.get('id') or child.get('job') or '?')
        status = str(child.get('status') or '')
        if children.get(name) != status:
          children[name] = status
          context.output.note(f'  {name}: {status}')

  def retry(problem: Problem):
    """Say that a read failed and will be retried."""
    detail = problem.get('detail') or problem.get('title') or problem['type']
    context.output.note(f'(reading the job failed, retrying: {detail})')

  return follow(client, path, update=update, retry=retry)


def finished(context: Context, job: Job) -> int:
  """Print a finished job; exit 1 unless it succeeded."""
  context.output.body(cast(JsonValue, job))
  return 0 if job['status'] == 'succeeded' else 1


def stream(
  context: Context, client: Client, path: str, params: dict[str, str | list[str]]
):
  """Write a binary body to `--output`, or to stdout when it is not a terminal."""
  target = getattr(context.args, 'output', None)
  stdout = context.output.stdout
  if target is None and stdout.isatty():
    raise ValueError('Refusing to write bytes to a terminal: use --output FILE')
  with client.stream('GET', path, params=params) as response:
    if target is not None:
      with open(target, 'wb') as file:
        for chunk in response.iter_bytes():
          file.write(chunk)
      return
    buffer = getattr(stdout, 'buffer', None) or sys.stdout.buffer
    for chunk in response.iter_bytes():
      buffer.write(chunk)
    buffer.flush()


def run(context: Context) -> int:
  """Run the route command in `context.args.route_command`."""
  command: Command = context.args.route_command
  args = context.args
  path = command.path
  if command.alternate and getattr(args, 'p_resource_id', None):
    path = command.alternate
  service = getattr(args, 'service', command.service)
  found = route(service, command.method, path)
  if found is None:
    raise ValueError(f'{service} serves no {command.method} {path}')
  client = context.authorize(tenant=not command.tenantless)
  target = fill(context, client, command, path)
  params = query(context, found)
  if command.words[-2:] == ('jobs', 'watch'):
    return finished(context, watch(context, client, target))
  if found['binary']:
    stream(context, client, target, params)
    return 0
  if getattr(args, 'all_pages', False):
    context.output.body(cast(JsonValue, collect(client, target, params)))
    return 0
  response = send(context, client, command, found, target, params)
  answer = cast(JsonValue, response.json()) if response.content else None
  job = answer.get('job') if isinstance(answer, dict) else None
  detach = getattr(args, 'detach', False)
  if response.status_code == 202 and isinstance(job, str) and not detach:
    location = urlparse(response.headers.get('Location', '')).path
    location = location[location.find('/v1/') :] if '/v1/' in location else ''
    if '/jobs/' not in location:
      location = f'v1/{service}/jobs/{job}'
    followed = watch(context, client, location)
    if isinstance(answer, dict) and 'id' in answer:
      context.output.body(answer)
      return 0 if followed['status'] == 'succeeded' else 1
    return finished(context, followed)
  if answer is not None or response.status_code != 204:
    context.output.body(answer)
  return 0


def send(
  context: Context,
  client: Client,
  command: Command,
  found: Route,
  target: str,
  params: dict[str, str | list[str]],
) -> httpx.Response:
  """Send the request, with its body, files and `Idempotency-Key`."""
  args = context.args
  headers = {}
  if getattr(args, 'idempotency_key', None):
    headers['Idempotency-Key'] = args.idempotency_key
  files: Files | None = None
  payload: JsonValue = None
  if found['body'] and found['body']['media'].startswith('multipart/'):
    paths: list[Path] = args.files
    files = [
      ('files', (p.name, p.read_bytes(), 'application/octet-stream')) for p in paths
    ]
  elif found['body']:
    variables = lookup(context.environ, context.connection.config, context.cwd)
    payload = build(args, command, target, variables)
  return client.request(
    command.method,
    target,
    params=params,
    body=payload,
    files=files,
    headers=headers,
  )
