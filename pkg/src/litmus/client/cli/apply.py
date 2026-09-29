"""`litmus apply [file] [--dry-run] [--prune]`: the configuration in `litmus.toml`, applied.

Policy 02 interfaces Rule 8, through public routes only (8.7), resources first, then
portfolios with their accounts (8.3); it never syncs (8.6) and deletes nothing without
`--prune` (8.5).

1. `[<unit>.resources.<name>]`: a resource missing by name is created with the table as
   its binding (`POST /v1/<unit>/resources`); one that exists is `unchanged`, or a
   `conflict` when its binding differs (bindings are immutable, policy 03 Rule 2.2).
   Resources are never deleted here.
2. `[portfolios.<id>]`: its `accounts` tables and `policy` go to portfolio's
   `POST {P}/apply` (`?dry_run`, `?prune`), which plans and applies them; without a
   `policy` table the portfolio's current policy is sent, so it is never reset.

Credentials and export folders (`credentials`, `files` on an account) are not applied
yet: they are left out and named on stderr.
"""

import argparse
from pathlib import Path
from typing_extensions import cast

from litmus.client.cli.body import lookup, resolved
from litmus.client.cli.connection import read_config
from litmus.client.cli.context import Context
from litmus.client.models import UNITS, JsonObject, JsonValue
from litmus.client.sdk.client import Client, ProblemError

NOT_APPLIED = ('credentials', 'files')


def add_commands(
  commands: 'argparse._SubParsersAction[argparse.ArgumentParser]',
  common: argparse.ArgumentParser,
):
  """Register `apply`."""
  parser = commands.add_parser(
    'apply',
    parents=[common],
    help='Apply litmus.toml: unit resources, then portfolios and their accounts.',
    description=__doc__.split('\n\n')[1] if __doc__ else None,
  )
  parser.add_argument(
    'file', nargs='?', type=Path, help='Default: the nearest litmus.toml.'
  )
  parser.add_argument(
    '--dry-run', action='store_true', help='Plan only; change nothing.'
  )
  parser.add_argument(
    '--prune', action='store_true', help='Delete stored accounts the file omits.'
  )
  parser.add_argument(
    '--portfolio', default=argparse.SUPPRESS, help='Apply only this portfolio.'
  )
  parser.set_defaults(handler=run)


def table(value: object, where: str) -> JsonObject:
  """A TOML table, or an error naming where."""
  if not isinstance(value, dict):
    raise ValueError(f'{where} must be a table')
  return cast(JsonObject, value)


def apply_resources(
  client: Client,
  document: JsonObject,
  variables: dict[str, str],
  *,
  dry_run: bool,
) -> dict[str, JsonValue]:
  """Create each declared unit resource that does not exist yet."""
  plans: dict[str, JsonValue] = {}
  for unit in UNITS:
    declared = table(table(document.get(unit, {}), unit).get('resources', {}), unit)
    unit_plans: dict[str, JsonValue] = {}
    for name, binding in declared.items():
      binding = table(resolved(binding, variables), f'{unit}.resources.{name}')
      page = cast(
        JsonObject,
        client.request('GET', f'v1/{unit}/resources', params={'name': name}).json(),
      )
      items = cast(list[JsonObject], page.get('items') or [])
      if items:
        current = cast(JsonObject, items[0].get('binding') or {})
        same = all(
          str(current.get(k, '')).lower() == str(v).lower() for k, v in binding.items()
        )
        unit_plans[name] = {
          'plan': 'unchanged' if same else 'conflict',
          'resource': items[0],
        }
        continue
      created: JsonValue = None
      if not dry_run:
        created = client.request(
          'POST', f'v1/{unit}/resources', body={'name': name, 'binding': binding}
        ).json()
      unit_plans[name] = {'plan': 'create', 'resource': created}
    if unit_plans:
      plans[unit] = unit_plans
  return plans


def current_policy(client: Client, portfolio: str) -> JsonValue:
  """The portfolio's stored policy, or `None` when the portfolio does not exist yet."""
  try:
    shown = cast(
      JsonObject, client.request('GET', f'v1/portfolio/portfolios/{portfolio}').json()
    )
  except ProblemError as error:
    if error.problem.get('status') == 404:
      return None
    raise
  return shown.get('policy')


def run(context: Context) -> int:
  """Apply the file; print the plan (and results) per resource and portfolio."""
  args = context.args
  path = args.file or context.connection.config
  if path is None:
    raise ValueError('No litmus.toml here or in a parent directory; name a file')
  document = cast(JsonObject, read_config(path))
  variables = lookup(context.environ, path, context.cwd)
  client = context.authorize()
  result: dict[str, JsonValue] = {
    'resources': apply_resources(client, document, variables, dry_run=args.dry_run),
    'portfolios': {},
  }
  portfolios = table(document.get('portfolios', {}), 'portfolios')
  only = getattr(args, 'portfolio', None)
  applied = cast(dict[str, JsonValue], result['portfolios'])
  for portfolio, settings in portfolios.items():
    if only and portfolio != only:
      continue
    settings = table(settings, f'portfolios.{portfolio}')
    accounts: dict[str, JsonValue] = {}
    for name, spec in table(settings.get('accounts', {}), 'accounts').items():
      spec = dict(table(spec, f'portfolios.{portfolio}.accounts.{name}'))
      for key in NOT_APPLIED:
        if spec.pop(key, None) is not None:
          context.output.note(f'{portfolio}.{name}.{key}: not applied yet (left out)')
      accounts[name] = resolved(cast(JsonObject, spec), variables)
    body: JsonObject = {'accounts': accounts}
    policy = resolved(settings.get('policy'), variables) or current_policy(
      client, portfolio
    )
    if policy is not None:
      body['policy'] = policy
    params = {'dry_run': str(args.dry_run).lower(), 'prune': str(args.prune).lower()}
    applied[portfolio] = client.request(
      'POST', f'v1/portfolio/portfolios/{portfolio}/apply', params=params, body=body
    ).json()
  context.output.body(result)
  return 0
