"""Where the CLI keeps what it signs in with, per deployment URL.

Policy 02 access Rule 8.1 and interfaces Rule 7.5: the login's refresh credential is kept
in the OS keychain when one is available (the optional `keyring` package with a working
backend), otherwise in `$XDG_CONFIG_HOME/litmus/credentials.json`, created with mode 0600
in a 0700 directory and refused when others can read it. `LITMUS_CREDENTIALS=file` or
`keychain` selects one. Nothing here is ever printed.
"""

from collections.abc import Generator, Mapping
from contextlib import AbstractContextManager, contextmanager
import json
import os
from pathlib import Path
import stat
from typing_extensions import Literal, NotRequired, Protocol, TypedDict, cast

KEYRING_SERVICE = 'litmus-tax'


class Session(TypedDict):
  """A session token cached until shortly before it expires (at most 900 s)."""

  token: str
  expires_at: float
  """Seconds since the epoch."""


class Login(TypedDict):
  """A device-flow login: the rotating refresh token and the tenant chosen with it."""

  kind: Literal['login']
  refresh_token: str
  tenant: NotRequired[str]
  sessions: NotRequired[dict[str, Session]]
  """Cached session tokens by tenant (`""` for the tenantless platform token)."""


class Key(TypedDict):
  """An API key given with `auth login --api-key-file` (access Rule 12)."""

  kind: Literal['key']
  key: str


Stored = Login | Key


class Store(Protocol):
  """Credentials per deployment URL, changed under a lock (refresh tokens rotate)."""

  description: str

  def get(self, url: str) -> Stored | None:
    """The credential kept for a deployment."""
    ...

  def put(self, url: str, value: Stored | None):
    """Keep, replace or (with `None`) forget a deployment's credential."""
    ...

  def lock(self) -> AbstractContextManager[None]:
    """Hold the store's lock while reading, refreshing and writing a login."""
    ...


def config_directory(environ: Mapping[str, str]) -> Path:
  """`$XDG_CONFIG_HOME/litmus`, by default `~/.config/litmus`."""
  base = environ.get('XDG_CONFIG_HOME') or str(Path.home() / '.config')
  return Path(base) / 'litmus'


@contextmanager
def file_lock(path: Path) -> Generator[None]:
  """An exclusive advisory lock on `path` where the platform has `fcntl`."""
  path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
  descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
  try:
    try:
      import fcntl

      fcntl.flock(descriptor, fcntl.LOCK_EX)
    except ImportError:
      pass
    yield
  finally:
    os.close(descriptor)


class FileStore:
  """Credentials in one JSON file, mode 0600."""

  def __init__(self, directory: Path):
    """Keep the file in `directory`, created with mode 0700 when missing."""
    self.path = directory / 'credentials.json'
    self.description = str(self.path)

  def read(self) -> dict[str, Stored]:
    """Every kept credential.

    Raises:
      ValueError: The file can be read by others, or is not a credentials file.
    """
    if not self.path.exists():
      return {}
    mode = stat.S_IMODE(self.path.stat().st_mode)
    if mode & 0o077:
      raise ValueError(
        f'{self.path} can be read by others (mode {mode:o}); run chmod 600 on it'
      )
    data = json.loads(self.path.read_text() or '{}')
    if not isinstance(data, dict):
      raise ValueError(f'{self.path} is not a credentials file')
    return cast(dict[str, Stored], data)

  def get(self, url: str) -> Stored | None:
    """The credential kept for a deployment."""
    return self.read().get(url)

  def put(self, url: str, value: Stored | None):
    """Rewrite the file atomically with mode 0600."""
    data = self.read()
    if value is None:
      data.pop(url, None)
    else:
      data[url] = value
    self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = self.path.with_suffix('.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as file:
      json.dump(data, file, indent=2)
    os.chmod(temporary, 0o600)
    os.replace(temporary, self.path)

  @contextmanager
  def lock(self) -> Generator[None]:
    """Serialise refreshes across concurrent commands."""
    with file_lock(self.path.with_suffix('.lock')):
      yield


class KeyringStore:
  """Credentials in the OS keychain, one entry per deployment URL."""

  def __init__(self, directory: Path):
    """Use the `keyring` package; the lock file stays in `directory`."""
    import keyring  # pyright: ignore[reportMissingImports]

    self.keyring = keyring
    self.lock_path = directory / 'credentials.lock'
    self.description = f'OS keychain ({KEYRING_SERVICE})'

  def get(self, url: str) -> Stored | None:
    """The credential kept for a deployment."""
    value = self.keyring.get_password(KEYRING_SERVICE, url)
    return cast(Stored, json.loads(value)) if value else None

  def put(self, url: str, value: Stored | None):
    """Keep or forget the entry."""
    if value is not None:
      self.keyring.set_password(KEYRING_SERVICE, url, json.dumps(value))
    elif self.keyring.get_password(KEYRING_SERVICE, url) is not None:
      self.keyring.delete_password(KEYRING_SERVICE, url)

  @contextmanager
  def lock(self) -> Generator[None]:
    """Serialise refreshes across concurrent commands."""
    with file_lock(self.lock_path):
      yield


def keychain_usable() -> bool:
  """Whether `keyring` is installed with a backend that actually stores secrets."""
  try:
    import keyring  # pyright: ignore[reportMissingImports]

    backend = keyring.get_keyring()  # pyright: ignore[reportUnknownMemberType]
  except Exception:
    return False
  module = type(backend).__module__  # pyright: ignore[reportUnknownArgumentType]
  return not module.startswith(('keyring.backends.fail', 'keyring.backends.null'))


def default_store(environ: Mapping[str, str]) -> Store:
  """The keychain when usable (or asked for), else the 0600 file.

  Raises:
    ValueError: `LITMUS_CREDENTIALS` names an unknown or unusable store.
  """
  directory = config_directory(environ)
  choice = environ.get('LITMUS_CREDENTIALS', 'auto')
  if choice not in ('auto', 'file', 'keychain'):
    raise ValueError('LITMUS_CREDENTIALS must be auto, file or keychain')
  if choice == 'keychain' and not keychain_usable():
    raise ValueError('No usable OS keychain: install litmus-tax[keychain]')
  if choice == 'keychain' or (choice == 'auto' and keychain_usable()):
    return KeyringStore(directory)
  return FileStore(directory)
