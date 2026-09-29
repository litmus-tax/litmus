"""Write commands: bodies from options, jobs followed or detached, secrets, uploads, apply."""

from collections.abc import Callable
import json
from pathlib import Path

import httpx
import pytest

from conftest import Deployment, Result, jwt

RESOURCE = '535f6bf4-a4b6-479b-a865-d847f352b306'
KEY = 'lt_' + jwt(kind='key', sub='key:k_1', tenant='t_1', scope='read sync admin')


@pytest.fixture
def keyed(
  run: Callable[..., Result], monkeypatch: pytest.MonkeyPatch
) -> Callable[..., Result]:
  """Run commands with an API key, polling jobs without waiting."""
  monkeypatch.setattr('litmus.client.sdk.jobs.time.sleep', lambda seconds: None)

  def invoke(*argv: str, env: dict[str, str] | None = None) -> Result:
    """One command, authenticated."""
    return run(*argv, env={'LITMUS_API_KEY': KEY, **(env or {})})

  return invoke


def sent(request: httpx.Request) -> object:
  """A request's JSON body."""
  return json.loads(request.content)


def test_options_build_the_body(
  keyed: Callable[..., Result], deployment: Deployment, tmp_path: Path
):
  """Body fields are options, nested binding fields by their own name; `--body` is a base.

  # policy 03 contract rule 2.1, policy 02 interfaces rule 9.6
  """
  deployment.on('POST', '/v1/evm/resources', {'id': RESOURCE}, status=201)
  result = keyed(
    'evm',
    'resource',
    'create',
    '--name',
    'treasury-base',
    '--network',
    'base',
    '--address',
    '0xabc',
    '--idempotency-key',
    'k1',
  )
  assert result.code == 0 and result.json() == {'id': RESOURCE}
  request = deployment.requests[-1]
  assert sent(request) == {
    'name': 'treasury-base',
    'binding': {'network': 'base', 'address': '0xabc'},
  }
  assert request.headers['Idempotency-Key'] == 'k1'
  (tmp_path / 'body.json').write_text('{"name": "old", "binding": {"network": "base"}}')
  keyed(
    'evm', 'resource', 'create', '--body', f'@{tmp_path / "body.json"}', '--name', 'new'
  )
  assert sent(deployment.requests[-1]) == {
    'name': 'new',
    'binding': {'network': 'base'},
  }


def test_jobs_are_followed_or_detached(
  keyed: Callable[..., Result], deployment: Deployment
):
  """A `202` job is followed to its end; `--detach` prints the accepted job instead.

  # policy 02 interfaces rule 7.4
  """
  accepted = {'job': 'sync-1', 'status': 'queued', 'resource': RESOURCE}
  deployment.routes[('POST', f'/v1/hl/resources/{RESOURCE}/sync')] = lambda request: (
    httpx.Response(202, json=accepted, headers={'Location': '/v1/hl/jobs/sync-1'})
  )
  reads = iter(['running', 'succeeded', 'failed'])
  deployment.routes[('GET', '/v1/hl/jobs/sync-1')] = lambda request: httpx.Response(
    200, json={'id': 'sync-1', 'status': next(reads), 'progress': []}
  )
  followed = keyed('hl', 'sync', RESOURCE, '--no-fetch')
  assert followed.code == 0
  assert followed.json() == {'id': 'sync-1', 'status': 'succeeded', 'progress': []}
  assert sent(deployment.requests[0]) == {'fetch': False}
  failed = keyed('hl', 'sync', RESOURCE)
  assert failed.code == 1 and failed.json()['status'] == 'failed'
  detached = keyed('hl', 'sync', RESOURCE, '--detach')
  assert (detached.code, detached.json()) == (0, accepted)


def test_secrets_only_as_variables(
  keyed: Callable[..., Result], deployment: Deployment, tmp_path: Path
):
  """Credentials are refused when typed, and read from the environment or `.env`.

  # policy 02 access rule 15, interfaces rule 8.2
  """
  path = f'/v1/cex/resources/{RESOURCE}/credentials'
  deployment.on('PUT', path, {'configured': True})
  typed = keyed(
    'cex', 'credentials', 'set', RESOURCE, '--api-key', 'AK', '--api-secret', 'S3CRET'
  )
  assert typed.code == 1 and 'S3CRET' not in typed.stdout + typed.stderr
  tested = keyed(
    'cex', 'credentials', 'test', RESOURCE, '--api-key', 'AK', '--api-secret', 'S3CRET'
  )
  assert tested.code == 1
  assert not deployment.requests
  (tmp_path / '.env').write_text('BITGET_SECRET="from-dotenv"\n')
  result = keyed(
    'cex',
    'credentials',
    'set',
    RESOURCE,
    '--api-key',
    '$BITGET_KEY',
    '--api-secret',
    '${BITGET_SECRET}',
    env={'BITGET_KEY': 'from-env'},
  )
  assert result.code == 0
  assert sent(deployment.requests[-1]) == {
    'api_key': 'from-env',
    'api_secret': 'from-dotenv',
  }
  missing = keyed(
    'cex', 'credentials', 'set', RESOURCE, '--api-key', '$NOPE', '--api-secret', '$NOPE'
  )
  assert missing.code == 1 and '$NOPE is not set' in missing.json()['detail']


def test_fixed_bodies_and_empty_answers(
  keyed: Callable[..., Result], deployment: Deployment
):
  """`accounts archive` sends its fixed body; a `204` prints nothing.

  # policy 02 interfaces rule 7.10
  """
  deployment.on(
    'PATCH', '/v1/portfolio/portfolios/p/accounts/bitget', {'account': 'bitget'}
  )
  assert keyed('accounts', 'archive', 'bitget', '--portfolio', 'p').code == 0
  assert sent(deployment.requests[-1]) == {'archived': True}
  deployment.routes[('DELETE', '/v1/platform/tenants/t_1/keys/k_9')] = lambda request: (
    httpx.Response(204)
  )
  revoked = keyed('keys', 'revoke', 'k_9')
  assert (revoked.code, revoked.stdout) == (0, '')


def test_upload_sends_files(
  keyed: Callable[..., Result], deployment: Deployment, tmp_path: Path
):
  """`cex upload` posts the files as multipart; attaching them is an edit.

  # policy 03 contract rule 9
  """
  deployment.on('POST', f'/v1/cex/resources/{RESOURCE}/uploads', {'files': []})
  (tmp_path / 'trades.csv').write_bytes(b'a,b\n1,2\n')
  assert keyed('cex', 'upload', RESOURCE, str(tmp_path / 'trades.csv')).code == 0
  request = deployment.requests[-1]
  assert request.headers['Content-Type'].startswith('multipart/form-data')
  assert b'filename="trades.csv"' in request.content and b'1,2' in request.content


def test_apply_creates_resources_then_portfolios(
  keyed: Callable[..., Result], deployment: Deployment, tmp_path: Path
):
  """Resources are created by name, portfolios applied through `{P}/apply`; nothing syncs.

  # policy 02 interfaces rules 8.3, 8.5 and 8.6
  """
  (tmp_path / 'litmus.toml').write_text(
    '[connection]\nurl = "local"\n'
    '[evm.resources.treasury]\nnetwork = "base"\naddress = "$ADDRESS"\n'
    '[evm.resources.ops]\nnetwork = "ethereum"\naddress = "0x2"\n'
    '[portfolios.company.accounts.bitget]\nunit = "cex"\nkey = "bitget"\n'
    'venue = "bitget"\nfiles = "exports/bitget"\n'
  )
  existing = {'id': RESOURCE, 'binding': {'network': 'ethereum', 'address': '0x2'}}

  def resources(request: httpx.Request) -> httpx.Response:
    """`ops` exists; `treasury` does not."""
    found = [existing] if request.url.params['name'] == 'ops' else []
    return httpx.Response(200, json={'items': found, 'next_cursor': None})

  deployment.routes[('GET', '/v1/evm/resources')] = resources
  deployment.on('POST', '/v1/evm/resources', {'id': 'new'}, status=201)
  deployment.on(
    'GET', '/v1/portfolio/portfolios/company', {'policy': {'cost_method': 'hifo'}}
  )
  deployment.on('POST', '/v1/portfolio/portfolios/company/apply', {'plan': []})
  dry = keyed('apply', '--dry-run', env={'ADDRESS': '0x1'})
  assert dry.code == 0, dry.stdout
  assert dry.json()['resources']['evm']['treasury'] == {
    'plan': 'create',
    'resource': None,
  }
  assert dry.json()['resources']['evm']['ops']['plan'] == 'unchanged'
  assert 'bitget.files: not applied yet' in dry.stderr
  posted = [r for r in deployment.requests if r.method == 'POST']
  assert [r.url.path for r in posted] == ['/v1/portfolio/portfolios/company/apply']
  assert posted[0].url.params['dry_run'] == 'true'
  assert sent(posted[0]) == {
    'accounts': {'bitget': {'unit': 'cex', 'key': 'bitget', 'venue': 'bitget'}},
    'policy': {'cost_method': 'hifo'},
  }
  keyed('apply', env={'ADDRESS': '0x1'})
  created = [
    r
    for r in deployment.requests
    if r.url.path == '/v1/evm/resources' and r.method == 'POST'
  ]
  assert sent(created[0]) == {
    'name': 'treasury',
    'binding': {'network': 'base', 'address': '0x1'},
  }
  assert not any('/sync' in r.url.path for r in deployment.requests)


def test_following_survives_a_gateway_error(
  keyed: Callable[..., Result], deployment: Deployment
):
  """A `502` while following a job is retried, not reported as the job's failure.

  # policy 02 interfaces rule 7.4
  """
  answers = iter(
    [
      httpx.Response(502, text='Bad Gateway'),
      httpx.Response(200, json={'id': 'j', 'status': 'succeeded'}),
    ]
  )
  deployment.routes[('GET', '/v1/portfolio/jobs/j')] = lambda request: next(answers)
  result = keyed('jobs', 'watch', 'j')
  assert (result.code, result.json()) == (0, {'id': 'j', 'status': 'succeeded'})
  assert 'retrying' in result.stderr
