"""Transport safety, connection precedence, output and errors, and discovery."""

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from conftest import Deployment, Result, jwt
from litmus.client.cli.connection import LOCAL_URL, resolve
from litmus.client.cli.output import render
from litmus.client.sdk.client import Client, ProblemError


def test_versioned_transport():
  """The SDK attaches authorization and keeps the selected API origin."""

  def handle(request: httpx.Request) -> httpx.Response:
    """Inspect the outgoing synthetic request."""
    assert str(request.url) == 'https://example.test/v1/cex/resources'
    assert request.headers['Authorization'] == 'Bearer synthetic'
    return httpx.Response(200, json={'items': []})

  with Client(
    'https://example.test', token='synthetic', transport=httpx.MockTransport(handle)
  ) as client:
    assert client.request('GET', 'v1/cex/resources').json() == {'items': []}


@pytest.mark.parametrize(
  'path',
  [
    'https://elsewhere.test/v1/cex',
    '//elsewhere.test/v1/cex',
    'v1/../secret',
    'v1/%2e%2e/secret',
    'v1/\\elsewhere',
    'v1/cex?next=https://elsewhere.test',
  ],
)
def test_transport_rejects_origin_escape(path: str):
  """An arbitrary endpoint cannot exfiltrate the configured token."""
  with Client('https://example.test', token='synthetic') as client:
    with pytest.raises(ValueError):
      client.request('GET', path)


def test_rejects_plain_http_credentials():
  """Only an explicitly selected loopback host may use unencrypted HTTP."""
  with pytest.raises(ValueError):
    Client('http://example.test', token='synthetic')


def test_unreachable_deployment_is_a_problem():
  """A transport failure is the problem `unavailable`, like any refusal.

  # policy 02 interfaces rule 7.3
  """

  def fail(request: httpx.Request) -> httpx.Response:
    """Refuse the connection."""
    raise httpx.ConnectError('refused', request=request)

  with Client('https://example.test', transport=httpx.MockTransport(fail)) as client:
    with pytest.raises(ProblemError) as raised:
      client.request('GET', 'v1/evm/resources')
  assert raised.value.problem['type'] == 'urn:litmus:problem:unavailable'


def test_connection_precedence(tmp_path: Path):
  """`--url`, then `LITMUS_URL`, then `litmus.toml [connection]`; the default is local.

  # policy 02 interfaces rule 7.7
  """
  (tmp_path / 'litmus.toml').write_text(
    '[connection]\nurl = "https://file.test/"\ntenant = "t_file"\n'
    '[portfolios.company]\nlabel = "Company"\n'
  )
  nested = tmp_path / 'exports'
  nested.mkdir()
  environ = {'LITMUS_URL': 'https://env.test'}
  assert resolve(url='https://option.test', environ=environ, cwd=nested).url == (
    'https://option.test'
  )
  assert resolve(environ=environ, cwd=nested).url == 'https://env.test'
  from_file = resolve(environ={}, cwd=nested)
  assert (from_file.url, from_file.source) == ('https://file.test', 'file')
  assert (from_file.tenant, from_file.portfolio) == ('t_file', 'company')
  empty = tmp_path.parent / 'elsewhere'
  empty.mkdir(exist_ok=True)
  assert resolve(environ={}, cwd=empty).url == LOCAL_URL
  (tmp_path / 'litmus.toml').write_text('[connection]\nurl = "local"\n')
  assert resolve(environ={}, cwd=tmp_path).url == LOCAL_URL


def test_problem_json_and_exit_codes(
  run: Callable[..., Result], deployment: Deployment
):
  """A refusal prints the problem object and exits 1; a usage error exits 2.

  # policy 02 interfaces rule 7.3
  """
  key = 'lt_' + jwt(kind='key', sub='key:k_1', tenant='t_1')
  result = run('openapi', 'evm', env={'LITMUS_API_KEY': key})
  assert result.code == 1
  assert result.json() == {
    'type': 'urn:litmus:problem:not-found',
    'title': 'Not Found',
    'status': 404,
  }
  with pytest.raises(SystemExit) as raised:
    run('openapi', 'nowhere')
  assert raised.value.code == 2


def test_capabilities_reports_the_deployment(
  run: Callable[..., Result], deployment: Deployment
):
  """`capabilities` reports each service's health and capabilities, as served.

  # policy 02 interfaces rule 7.6
  """
  deployment.on('GET', '/v1/evm/health', {'service': 'evm', 'version': '0.6.0'})
  deployment.on('GET', '/v1/evm/capabilities', {'unit': 'evm', 'schema': 'evm/5'})
  deployment.on(
    'GET',
    '/v1/cex/health',
    {'type': 'urn:litmus:problem:unavailable', 'title': 'Unavailable'},
    status=503,
  )
  result = run('capabilities')
  assert result.code == 0
  services = result.json()['services']
  assert services['evm'] == {
    'served': True,
    'healthy': True,
    'health': {'service': 'evm', 'version': '0.6.0'},
    'capabilities': {'unit': 'evm', 'schema': 'evm/5'},
  }
  assert services['cex']['healthy'] is False
  assert services['platform'] == {'served': False}


def test_human_rendering_is_the_body():
  """On a terminal a page renders as a table of its items, computing nothing.

  # policy 02 interfaces rule 7.2
  """
  page = {
    'items': [
      {'id': 'r1', 'name': 'treasury', 'binding': {'network': 'base'}},
      {'id': 'r2', 'name': 'ops', 'binding': {'network': 'ethereum'}},
    ],
    'next_cursor': None,
  }
  lines = render(page).splitlines()
  assert lines[0].split() == ['id', 'name', 'binding']
  assert lines[1].split()[:2] == ['r1', 'treasury']
  assert 'status  ok' in render({'status': 'ok'})
