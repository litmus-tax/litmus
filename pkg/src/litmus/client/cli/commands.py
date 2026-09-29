"""Every route command: its words and the one public route it calls (interfaces Rule 7.10).

A command names its route by method and path; its options come from that route's
OpenAPI (the generated `routes.json`). Path parameters are filled in by name:
`portfolio_id` from `--portfolio`, `tenant_id` from the connection's tenant, `service`
from `--service`, `unit` fixed by the command, and every other one is a positional
argument (`resource_id` becomes `resource` and takes a name or an id, Rule 6.2).
"""

from dataclasses import dataclass, field

from litmus.client.models import UNITS, JsonObject


@dataclass(frozen=True)
class Command:
  """One command and its route."""

  words: tuple[str, ...]
  method: str
  path: str
  """`/v1/<service>/…`; `{service}` is chosen with `--service`."""
  help: str = ''
  """Overrides the route's description."""
  fixed: dict[str, str] = field(default_factory=dict[str, str])
  """Path parameters the command fixes (`unit`)."""
  body: JsonObject | None = None
  """A fixed body (for example `archive`), instead of options."""
  alternate: str | None = None
  """The route used when the optional `resource` argument is given."""
  tenantless: bool = False
  """A platform route that needs no tenant (a login may not have chosen one)."""
  own_portfolio: bool = False
  """`portfolio_id` is a positional (defaulting to `--portfolio`) rather than an option."""

  @property
  def service(self) -> str:
    """The service in the path, or `{service}`."""
    return self.path.split('/')[2]


P = '/v1/portfolio/portfolios/{portfolio_id}'
T = '/v1/platform/tenants/{tenant_id}'
R = '/resources/{resource_id}'


def unit_commands(unit: str) -> list[Command]:
  """The commands of one unit (policy 03 contract Rules 16 and 18)."""
  u = f'/v1/{unit}'
  return [
    Command((unit, 'capabilities'), 'GET', f'{u}/capabilities'),
    Command((unit, 'resource', 'list'), 'GET', f'{u}/resources'),
    Command((unit, 'resource', 'show'), 'GET', f'{u}{R}'),
    Command(
      (unit, 'resource', 'accounts'),
      'GET',
      '/v1/portfolio/resources/{unit}/{resource_id}/accounts',
      help='The portfolio accounts that point at the resource.',
      fixed={'unit': unit},
    ),
    Command((unit, 'records'), 'GET', f'{u}{R}/records'),
    Command((unit, 'changes'), 'GET', f'{u}{R}/changes'),
    Command((unit, 'state'), 'GET', f'{u}{R}/state'),
    Command((unit, 'compartments'), 'GET', f'{u}{R}/compartments'),
    Command((unit, 'items'), 'GET', f'{u}{R}/items'),
    Command((unit, 'verification'), 'GET', f'{u}{R}/verification'),
    Command((unit, 'export'), 'GET', f'{u}{R}/export'),
    Command((unit, 'evidence'), 'GET', f'{u}{R}/evidence/{{digest}}'),
    Command((unit, 'edits', 'list'), 'GET', f'{u}{R}/edits'),
    Command((unit, 'credentials', 'show'), 'GET', f'{u}{R}/credentials'),
    Command(
      (unit, 'usage'),
      'GET',
      f'{u}/usage',
      help='Usage of every resource, or with a resource its own.',
      alternate=f'{u}{R}/usage',
    ),
    Command((unit, 'budget', 'show'), 'GET', f'{u}{R}/budget'),
    Command((unit, 'networks'), 'GET', f'{u}/networks'),
    Command((unit, 'venues'), 'GET', f'{u}/venues'),
    Command((unit, 'coverage'), 'GET', f'{u}{R}/coverage'),
  ]


PORTFOLIO = [
  Command(('portfolios', 'list'), 'GET', '/v1/portfolio/portfolios'),
  Command(('portfolios', 'show'), 'GET', P, own_portfolio=True),
  Command(('settings', 'show'), 'GET', P, help="The portfolio's settings."),
  Command(('accounts', 'list'), 'GET', f'{P}/accounts'),
  Command(('accounts', 'show'), 'GET', f'{P}/accounts/{{account}}'),
  Command(('imports',), 'GET', f'{P}/accounts/{{account}}/imports'),
  Command(('budgets', 'list'), 'GET', f'{P}/budget'),
  Command(('budgets', 'show'), 'GET', f'{P}/accounts/{{account}}/budget'),
  Command(('records',), 'GET', f'{P}/records'),
  Command(('history',), 'GET', f'{P}/history'),
  Command(('state',), 'GET', f'{P}/state'),
  Command(('items',), 'GET', f'{P}/items'),
  Command(('overview',), 'GET', f'{P}/overview'),
  Command(('valuation',), 'GET', f'{P}/valuation'),
  Command(('prices', 'gaps'), 'GET', f'{P}/prices/gaps'),
  Command(('links', 'list'), 'GET', f'{P}/links'),
  Command(('links', 'show'), 'GET', f'{P}/links/{{link_id}}'),
  Command(('unmatched',), 'GET', f'{P}/unmatched'),
  Command(('corrections', 'list'), 'GET', f'{P}/corrections'),
  Command(('corrections', 'show'), 'GET', f'{P}/corrections/{{correction_id}}'),
  Command(('corrections', 'candidates'), 'GET', f'{P}/corrections/candidates'),
  Command(('audit',), 'GET', f'{P}/audit'),
  Command(('books', 'list'), 'GET', f'{P}/books'),
  Command(('books', 'show'), 'GET', f'{P}/books/{{revision_id}}'),
  Command(('books', 'export'), 'GET', f'{P}/books/{{revision_id}}/export'),
  Command(('currencies',), 'GET', '/v1/portfolio/currencies'),
]

PLATFORM = [
  Command(('me',), 'GET', '/v1/platform/me', tenantless=True),
  Command(('tenants', 'list'), 'GET', '/v1/platform/tenants', tenantless=True),
  Command(('tenants', 'show'), 'GET', T),
  Command(('members', 'list'), 'GET', f'{T}/members'),
  Command(('principals',), 'GET', f'{T}/principals'),
  Command(('keys', 'list'), 'GET', f'{T}/keys'),
  Command(('keys', 'show'), 'GET', f'{T}/keys/{{key_id}}'),
]

JOBS = [
  Command(('jobs', 'list'), 'GET', '/v1/{service}/jobs'),
  Command(('jobs', 'show'), 'GET', '/v1/{service}/jobs/{job_id}'),
  Command(
    ('jobs', 'watch'),
    'GET',
    '/v1/{service}/jobs/{job_id}',
    help='Follow a job and its children until it finishes; progress on stderr.',
  ),
]


def commands() -> list[Command]:
  """Every route command, unit commands for each unit."""
  return [
    *(c for unit in UNITS for c in unit_commands(unit)),
    *PORTFOLIO,
    *PLATFORM,
    *JOBS,
  ]
