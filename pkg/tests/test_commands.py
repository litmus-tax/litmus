"""Route commands: names to ids, flags to query parameters, pages, streams and jobs."""

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from conftest import Deployment, Result, jwt

RESOURCE = '535f6bf4-a4b6-479b-a865-d847f352b306'
KEY = 'lt_' + jwt(kind='key', sub='key:k_1', tenant='t_1', scope='read')


@pytest.fixture
def keyed(run: Callable[..., Result]) -> Callable[..., Result]:
  """Run commands with an API key in the environment."""

  def invoke(*argv: str, env: dict[str, str] | None = None) -> Result:
    """One command, authenticated."""
    return run(*argv, env={'LITMUS_API_KEY': KEY, **(env or {})})

  return invoke


def test_resource_names_resolve_to_ids(
  keyed: Callable[..., Result], deployment: Deployment
):
  """A resource is addressed by name or id; names resolve through `?name=`.

  # policy 02 interfaces rule 6.2, policy 03 contract rule 3.4
  """
  deployment.on(
    'GET', '/v1/evm/resources', {'items': [{'id': RESOURCE}], 'next_cursor': None}
  )
  deployment.on('GET', f'/v1/evm/resources/{RESOURCE}/state', {'schema': 'evm/5'})
  result = keyed('evm', 'state', 'treasury', '--at', '2026-01-01')
  assert result.code == 0, result.stdout
  assert result.json() == {'schema': 'evm/5'}
  lookup, state = deployment.requests
  assert lookup.url.params['name'] == 'treasury'
  assert state.url.params['at'] == '2026-01-01'
  assert state.headers['Authorization'] == f'Bearer {KEY}'
  keyed('evm', 'state', RESOURCE)
  assert len(deployment.requests) == 3


def test_flags_are_query_parameters(
  keyed: Callable[..., Result], deployment: Deployment
):
  """Flags are named after the route's query parameters; `kind` repeats.

  # policy 03 contract rule 18.1
  """
  deployment.on('GET', f'/v1/cex/resources/{RESOURCE}/records', {'records': []})
  args = ['--from', '2026-01-01', '--kind', 'cex.trade', '--kind', 'cex.fee']
  result = keyed('cex', 'records', RESOURCE, *args, '--no-legless', '--limit', '5')
  assert result.code == 0
  params = deployment.requests[-1].url.params
  assert params.get_list('kind') == ['cex.trade', 'cex.fee']
  assert (params['from'], params['legless'], params['limit']) == (
    '2026-01-01',
    'false',
    '5',
  )


def test_all_follows_the_cursor(keyed: Callable[..., Result], deployment: Deployment):
  """`--all` follows `next_cursor` and prints the pages as one.

  # policy 03 contract rule 18.4
  """

  def page(request: httpx.Request) -> httpx.Response:
    """Two pages of resources."""
    if request.url.params.get('cursor') == 'c2':
      return httpx.Response(200, json={'items': [{'id': 'b'}], 'next_cursor': None})
    return httpx.Response(200, json={'items': [{'id': 'a'}], 'next_cursor': 'c2'})

  deployment.routes[('GET', '/v1/hl/resources')] = page
  result = keyed('hl', 'resource', 'list', '--all')
  assert result.json() == {'items': [{'id': 'a'}, {'id': 'b'}], 'next_cursor': None}
  assert keyed('hl', 'resource', 'list').json()['next_cursor'] == 'c2'


def test_portfolio_is_chosen_or_the_only_one(
  keyed: Callable[..., Result], deployment: Deployment
):
  """Portfolio commands take `--portfolio`, `LITMUS_PORTFOLIO`, or the only portfolio.

  # policy 02 interfaces rule 7.10
  """
  deployment.on(
    'GET', '/v1/portfolio/portfolios', {'portfolios': [{'portfolio_id': 'personal'}]}
  )
  for name in ('personal', 'company'):
    deployment.on(
      'GET', f'/v1/portfolio/portfolios/{name}/overview', {'portfolio_id': name}
    )
  assert keyed('overview').json() == {'portfolio_id': 'personal'}
  chosen = keyed('overview', '--portfolio', 'company')
  assert chosen.json() == {'portfolio_id': 'company'}
  from_env = keyed('overview', env={'LITMUS_PORTFOLIO': 'company'})
  assert from_env.json() == {'portfolio_id': 'company'}
  deployment.on('GET', '/v1/portfolio/portfolios', {'portfolios': []})
  assert keyed('overview').json()['type'] == 'urn:litmus:problem:portfolio-required'


def test_platform_routes_use_the_credentials_tenant(
  keyed: Callable[..., Result], deployment: Deployment
):
  """Tenant routes are filled from `--tenant`, else the credential's tenant."""
  deployment.on('GET', '/v1/platform/tenants/t_1/members', {'members': []})
  deployment.on('GET', '/v1/platform/tenants/t_2/members', {'members': [1]})
  assert keyed('members', 'list').json() == {'members': []}
  assert keyed('members', 'list', '--tenant', 't_2').json() == {'members': [1]}


def test_export_streams_bytes(
  keyed: Callable[..., Result], deployment: Deployment, tmp_path: Path
):
  """A binary route is streamed byte for byte to `--output`.

  # policy 03 contract rule 12
  """
  deployment.routes[('GET', f'/v1/dydx/resources/{RESOURCE}/export')] = lambda request: (
    httpx.Response(200, content=b'\x1f\x8bbundle')
  )
  target = tmp_path / 'export.tar.gz'
  result = keyed('dydx', 'export', RESOURCE, '--output', str(target))
  assert result.code == 0 and result.stdout == ''
  assert target.read_bytes() == b'\x1f\x8bbundle'


def test_watch_follows_a_job(
  keyed: Callable[..., Result],
  deployment: Deployment,
  monkeypatch: pytest.MonkeyPatch,
):
  """`jobs watch` polls until the job ends; progress on stderr, the job on stdout.

  # policy 02 interfaces rules 7.4 and 12
  """
  monkeypatch.setattr('litmus.client.sdk.jobs.time.sleep', lambda seconds: None)
  reads = iter(
    [
      {'id': 'j', 'status': 'running', 'progress': [{'at': 't1', 'message': 'fetch'}]},
      {
        'id': 'j',
        'status': 'failed',
        'progress': [{'at': 't1', 'message': 'fetch'}, {'at': 't2', 'message': 'x'}],
        'children': [{'id': 'sync-1', 'status': 'failed'}],
      },
    ]
  )
  deployment.routes[('GET', '/v1/evm/jobs/j')] = lambda request: httpx.Response(
    200, json=next(reads)
  )
  result = keyed('jobs', 'watch', 'j', '--service', 'evm')
  assert result.code == 1
  assert result.json()['status'] == 'failed'
  assert result.stderr.splitlines() == ['t1  fetch', 't2  x', '  sync-1: failed']


def test_path_values_cannot_escape_the_route(keyed: Callable[..., Result]):
  """A positional value never adds path segments, a query or a fragment."""
  for value in ('../keys', 'a/b', 'a?b', 'a#b', '%2e'):
    result = keyed('accounts', 'show', value, '--portfolio', 'p')
    assert result.code == 1
    assert result.json()['type'] == 'urn:litmus:problem:validation'
