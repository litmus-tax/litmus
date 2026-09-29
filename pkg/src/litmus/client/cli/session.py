"""The credential a command sends: an API key, or a session token from the stored login.

Policy 02 interfaces Rule 7.5 and access Rules 1, 12 and 14.2, in this order:

1. `LITMUS_API_KEY`, sent as a Bearer header like any other credential;
2. what `litmus auth login` kept for the deployment: an API key, or a login whose refresh
   token is exchanged for a session token (cached until shortly before it expires; each
   exchange rotates the refresh token, under the store's lock);
3. for the local deployment only, the development owner's key that `litmus local up`
   writes into the deployment state directory.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
import time
from typing_extensions import Literal, cast

from litmus.client.cli.connection import Connection
from litmus.client.cli.credentials import Login, Session, Store
from litmus.client.models import JsonObject, Problem
from litmus.client.sdk.auth import refresh
from litmus.client.sdk.client import Client, ProblemError

MARGIN = 60
"""Seconds before expiry at which a cached session token is no longer used."""
PROJECT = 'litmus-local'
"""The local deployment's Compose project, which names its state directory."""

Origin = Literal['environment', 'key', 'login', 'local-owner-key']


@dataclass(frozen=True)
class Credential:
  """A bearer credential and where it came from."""

  token: str
  origin: Origin


def state_directory(environ: Mapping[str, str]) -> Path:
  """The local deployment state directory (topologies term 11)."""
  data = environ.get('XDG_DATA_HOME') or str(Path.home() / '.local' / 'share')
  return Path(data) / 'litmus' / (environ.get('COMPOSE_PROJECT_NAME') or PROJECT)


def owner_key(environ: Mapping[str, str]) -> Path:
  """Where `litmus local up` writes the development owner's key (access Rule 14.2)."""
  return state_directory(environ) / 'owner-key'


def unauthorized(detail: str) -> Problem:
  """The problem for a command that has no credential to send."""
  return {
    'type': 'urn:litmus:problem:unauthorized',
    'title': 'Unauthorized',
    'status': 401,
    'detail': detail,
  }


class Sessions:
  """Finds and refreshes the credential of one connection."""

  def __init__(
    self,
    connection: Connection,
    store: Store,
    client: Client,
    environ: Mapping[str, str],
    clock: Callable[[], float] = time.time,
  ):
    """Bind the connection, its credential store and a client for platform's grants."""
    self.connection = connection
    self.store = store
    self.client = client
    self.environ = environ
    self.clock = clock

  def credential(self, *, tenant: bool = True) -> Credential:
    """The credential to send; with `tenant`, a login's session token names a tenant.

    Raises:
      ProblemError: No credential, an ended login, or no tenant to choose.
    """
    key = self.environ.get('LITMUS_API_KEY')
    if key:
      return Credential(key.strip(), 'environment')
    stored = self.store.get(self.connection.url)
    if stored is not None and stored['kind'] == 'key':
      return Credential(stored['key'], 'key')
    if stored is not None:
      chosen = self.tenant() if tenant else None
      return Credential(self.session(chosen), 'login')
    path = owner_key(self.environ)
    if self.connection.local and path.is_file():
      return Credential(path.read_text().strip(), 'local-owner-key')
    raise ProblemError(
      unauthorized(
        f'Not signed in to {self.connection.url}: run `litmus auth login`, '
        'or set LITMUS_API_KEY.'
      )
    )

  def login(self) -> Login:
    """The stored login.

    Raises:
      ProblemError: No login is stored.
    """
    stored = self.store.get(self.connection.url)
    if stored is None or stored['kind'] != 'login':
      raise ProblemError(unauthorized('No login is stored; run `litmus auth login`.'))
    return stored

  def session(self, tenant: str | None) -> str:
    """A session token for `tenant` (tenantless with `None`), refreshing when needed."""
    with self.store.lock():
      login = self.login()
      sessions = login.get('sessions', {})
      cached = sessions.get(tenant or '')
      if cached and cached['expires_at'] - MARGIN > self.clock():
        return cached['token']
      grant = refresh(self.client, login['refresh_token'], tenant=tenant)
      login['refresh_token'] = grant.get('refresh_token', login['refresh_token'])
      session: Session = {
        'token': grant['access_token'],
        'expires_at': self.clock() + grant['expires_in'],
      }
      login['sessions'] = {
        name: value
        for name, value in sessions.items()
        if value['expires_at'] > self.clock()
      } | {tenant or '': session}
      self.store.put(self.connection.url, login)
      return session['token']

  def tenant(self) -> str:
    """The tenant a login acts in: chosen, remembered, or the caller's only membership.

    Raises:
      ProblemError: The login belongs to several tenants and none was chosen.
    """
    if self.connection.tenant:
      return self.connection.tenant
    login = self.login()
    remembered = login.get('tenant')
    if remembered:
      return remembered
    self.client.token = self.session(None)
    me = cast(JsonObject, self.client.request('GET', 'v1/platform/me').json())
    memberships = me.get('memberships')
    tenants: list[str] = []
    if isinstance(memberships, list):
      for membership in memberships:
        if isinstance(membership, dict) and isinstance(membership.get('tenant'), dict):
          identifier = cast(JsonObject, membership['tenant']).get('id')
          if isinstance(identifier, str):
            tenants.append(identifier)
    if len(tenants) != 1:
      raise ProblemError(
        {
          'type': 'urn:litmus:problem:tenant-required',
          'title': 'Tenant required',
          'status': 400,
          'detail': 'Choose a tenant with --tenant, LITMUS_TENANT or '
          '`litmus auth login --tenant`: '
          + (', '.join(tenants) or 'this login belongs to no tenant'),
        }
      )
    with self.store.lock():
      login = self.login()
      login['tenant'] = tenants[0]
      self.store.put(self.connection.url, login)
    return tenants[0]
