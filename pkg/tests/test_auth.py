"""Signing in: the device flow, stored logins, API keys and the local owner key."""

from collections.abc import Callable
import json
from pathlib import Path
import stat
from urllib.parse import parse_qs

import httpx
import pytest

from conftest import Deployment, Result, jwt

TENANT = 't_1'


class Platform:
  """A fake issuer: a device code approved on the second poll, rotating refresh tokens."""

  def __init__(self, deployment: Deployment):
    """Serve platform's CLI routes on `deployment`."""
    self.polls = 0
    self.generation = 0
    self.refreshes: list[dict[str, list[str]]] = []
    self.revoked: list[str] = []
    deployment.on(
      'POST',
      '/v1/platform/device/code',
      {
        'device_code': 'device-secret',
        'user_code': 'BCDF-GHJK',
        'verification_uri': 'http://localhost:8080/device',
        'verification_uri_complete': 'http://localhost:8080/device?code=BCDF-GHJK',
        'expires_in': 600,
        'interval': 1,
      },
    )
    deployment.routes[('POST', '/v1/platform/token')] = self.token
    deployment.routes[('POST', '/v1/platform/revoke')] = self.revoke
    deployment.on(
      'GET', '/v1/platform/me', {'memberships': [{'tenant': {'id': TENANT}}]}
    )

  def grant(self, tenant: str | None) -> httpx.Response:
    """A session token (tenantless without `tenant`) and the next refresh token."""
    self.generation += 1
    claims: dict[str, object] = {
      'kind': 'session',
      'sub': 'usr_1',
      'exp': 1_900_000_000,
    }
    claims['aud'] = ['platform', 'portfolio', 'evm'] if tenant else ['platform']
    if tenant:
      claims.update(tenant=tenant, scope='read sync')
    return httpx.Response(
      200,
      json={
        'access_token': jwt(**claims),
        'token_type': 'Bearer',
        'expires_in': 900,
        'refresh_token': f'lr_{self.generation}',
      },
    )

  def token(self, request: httpx.Request) -> httpx.Response:
    """The token endpoint: device grant, then refresh grants of the current login only."""
    form = parse_qs(request.content.decode())
    if form['grant_type'] == ['urn:ietf:params:oauth:grant-type:device_code']:
      assert form['device_code'] == ['device-secret']
      self.polls += 1
      if self.polls == 1:
        return httpx.Response(400, json={'error': 'authorization_pending'})
      return self.grant(None)
    assert form['grant_type'] == ['refresh_token']
    if form['refresh_token'] != [f'lr_{self.generation}']:
      return httpx.Response(400, json={'error': 'invalid_grant'})
    self.refreshes.append(form)
    return self.grant(form.get('tenant', [None])[0])

  def revoke(self, request: httpx.Request) -> httpx.Response:
    """Record the revoked credential."""
    self.revoked.append(parse_qs(request.content.decode())['token'][0])
    return httpx.Response(200, json={})


@pytest.fixture
def platform(deployment: Deployment, monkeypatch: pytest.MonkeyPatch) -> Platform:
  """The fake issuer, polled without waiting."""
  monkeypatch.setattr('litmus.client.sdk.auth.time.sleep', lambda seconds: None)
  return Platform(deployment)


def credentials_file(environ: dict[str, str]) -> Path:
  """The file store's path in the isolated environment."""
  return Path(environ['XDG_CONFIG_HOME']) / 'litmus' / 'credentials.json'


def test_device_login_keeps_login_private(
  run: Callable[..., Result], platform: Platform, environ: dict[str, str]
):
  """Device flow; the login is kept in a 0600 file and never printed.

  # policy 02 interfaces rule 7.5, access rules 8.1 and 17.2
  """
  result = run('auth', 'login', '--no-browser')
  assert result.code == 0, result.stderr
  assert 'BCDF-GHJK' in result.stderr
  assert platform.polls == 2
  path = credentials_file(environ)
  assert stat.S_IMODE(path.stat().st_mode) == 0o600
  assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
  stored = json.loads(path.read_text())['http://localhost:8080']
  assert stored['kind'] == 'login' and stored['tenant'] == TENANT
  status = result.json()
  assert isinstance(status, dict)
  assert status['origin'] == 'login'
  assert status['credential']['tenant'] == TENANT
  for secret in ('lr_', 'device-secret', stored['sessions'][TENANT]['token']):
    assert secret not in result.stdout + result.stderr


def test_refresh_rotates_under_the_store(
  run: Callable[..., Result], platform: Platform, environ: dict[str, str]
):
  """A cached session token is reused; each refresh rotates the stored login.

  # policy 02 access rule 8.1
  """
  assert run('auth', 'login', '--no-browser').code == 0
  refreshes = len(platform.refreshes)
  assert run('auth', 'status').code == 0
  assert len(platform.refreshes) == refreshes
  path = credentials_file(environ)
  stored = json.loads(path.read_text())
  stored['http://localhost:8080']['sessions'] = {}
  path.write_text(json.dumps(stored))
  assert run('auth', 'status').code == 0
  assert platform.refreshes[-1]['tenant'] == [TENANT]
  after = json.loads(path.read_text())['http://localhost:8080']
  assert after['refresh_token'] == f'lr_{platform.generation}'


def test_logout_revokes_the_login(
  run: Callable[..., Result], platform: Platform, environ: dict[str, str]
):
  """`auth logout` revokes the refresh token at platform and forgets it.

  # policy 02 interfaces rule 7.5
  """
  assert run('auth', 'login', '--no-browser').code == 0
  current = json.loads(credentials_file(environ).read_text())['http://localhost:8080']
  result = run('auth', 'logout')
  assert result.code == 0
  assert platform.revoked == [current['refresh_token']]
  assert json.loads(credentials_file(environ).read_text()) == {}
  assert result.json() == {
    'url': 'http://localhost:8080',
    'signed_out': True,
    'revoked': True,
  }


def test_api_key_is_sent_as_bearer(
  run: Callable[..., Result], deployment: Deployment, tmp_path: Path
):
  """`--api-key-file` keeps a key; `LITMUS_API_KEY` wins; both go out as Bearer.

  # policy 02 interfaces rule 7.5, access rule 12.2
  """
  key = 'lt_' + jwt(kind='key', sub='key:k_1', tenant=TENANT, aud=['evm'], scope='read')
  (tmp_path / 'key').write_text(key + '\n')
  result = run('auth', 'login', '--api-key-file', str(tmp_path / 'key'))
  assert result.code == 0
  assert key not in result.stdout
  assert result.json()['credential']['subject'] == 'key:k_1'
  other = 'lt_' + jwt(kind='key', sub='key:k_2', tenant=TENANT)
  status = run('auth', 'status', env={'LITMUS_API_KEY': other}).json()
  assert status['origin'] == 'environment'
  assert status['credential']['subject'] == 'key:k_2'
  deployment.on('GET', '/v1/evm/openapi.json', {'openapi': '3.1.0'})
  assert run('openapi', 'evm').code == 0
  assert 'Authorization' not in deployment.requests[-1].headers


def test_refuses_a_credentials_file_others_can_read(
  run: Callable[..., Result], environ: dict[str, str]
):
  """A credentials file readable by group or others is refused, not used.

  # policy 02 access rule 8.1
  """
  path = credentials_file(environ)
  path.parent.mkdir(parents=True)
  path.write_text('{}')
  path.chmod(0o644)
  result = run('auth', 'status')
  assert result.code == 1
  assert 'chmod 600' in result.json()['detail']


def test_local_owner_key(run: Callable[..., Result], environ: dict[str, str]):
  """Against the local deployment, the owner key `litmus local up` wrote is used.

  # policy 02 access rule 14.2
  """
  assert run('auth', 'status').code == 1
  key = 'lt_' + jwt(kind='key', sub='key:owner', tenant='local')
  path = Path(environ['XDG_DATA_HOME']) / 'litmus' / 'litmus-local' / 'owner-key'
  path.parent.mkdir(parents=True)
  path.write_text(key)
  status = run('auth', 'status').json()
  assert status['origin'] == 'local-owner-key'
  remote = run('auth', 'status', '--url', 'https://api.example.test')
  assert remote.code == 1
  assert remote.json()['type'] == 'urn:litmus:problem:unauthorized'
