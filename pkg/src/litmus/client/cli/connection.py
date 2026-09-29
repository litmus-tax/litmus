"""Which deployment a command talks to, and in which tenant and portfolio.

Policy 02 interfaces Rule 7.7: the connection comes from `--url`, `LITMUS_URL` or
`litmus.toml [connection]`, in that order, and the default is local. `litmus.toml` is the
nearest one in the working directory or a parent. The tenant follows the same order
(`--tenant`, `LITMUS_TENANT`, `[connection] tenant`); the portfolio comes from
`--portfolio`, `LITMUS_PORTFOLIO`, or the one `[portfolios.<id>]` table of the file.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import tomllib
from typing_extensions import Any, Literal

LOCAL_URL = 'http://localhost:8080'
"""A local deployment's base URL (topologies Rule 1)."""
CONFIG_NAME = 'litmus.toml'

Source = Literal['option', 'environment', 'file', 'default']


@dataclass(frozen=True)
class Connection:
  """Where commands go, and where each setting came from."""

  url: str
  """The deployment's base URL, without a trailing slash."""
  source: Source
  tenant: str | None = None
  portfolio: str | None = None
  config: Path | None = None
  """The `litmus.toml` read, if any."""

  @property
  def local(self) -> bool:
    """Whether this is the default local deployment."""
    return self.url == LOCAL_URL


def find_config(start: Path) -> Path | None:
  """The nearest `litmus.toml` in `start` or one of its parents."""
  for directory in (start, *start.parents):
    candidate = directory / CONFIG_NAME
    if candidate.is_file():
      return candidate
  return None


def read_config(path: Path) -> dict[str, Any]:
  """A `litmus.toml` document.

  Raises:
    ValueError: The file is not valid TOML.
  """
  try:
    return tomllib.loads(path.read_text())
  except tomllib.TOMLDecodeError as error:
    raise ValueError(f'{path}: {error}') from error


def normalized(url: str) -> str:
  """A base URL without its trailing slash; `local` is the local deployment."""
  return LOCAL_URL if url == 'local' else url.rstrip('/')


def resolve(
  *,
  url: str | None = None,
  tenant: str | None = None,
  portfolio: str | None = None,
  environ: Mapping[str, str],
  cwd: Path,
) -> Connection:
  """The connection for one command, from its options, the environment and `litmus.toml`.

  Raises:
    ValueError: An invalid `litmus.toml`.
  """
  config = find_config(cwd)
  document = read_config(config) if config else {}
  table = document.get('connection', {})
  if not isinstance(table, dict):
    raise ValueError(f'{config}: [connection] must be a table')
  source: Source
  if url:
    selected, source = url, 'option'
  elif environ.get('LITMUS_URL'):
    selected, source = environ['LITMUS_URL'], 'environment'
  elif isinstance(table.get('url'), str):
    selected, source = table['url'], 'file'
  else:
    selected, source = LOCAL_URL, 'default'
  file_tenant = table.get('tenant')
  portfolios = document.get('portfolios', {})
  only = (
    next(iter(portfolios))
    if isinstance(portfolios, dict) and len(portfolios) == 1
    else None
  )
  return Connection(
    url=normalized(selected),
    source=source,
    tenant=tenant
    or environ.get('LITMUS_TENANT')
    or (file_tenant if isinstance(file_tenant, str) else None),
    portfolio=portfolio or environ.get('LITMUS_PORTFOLIO') or only,
    config=config,
  )
