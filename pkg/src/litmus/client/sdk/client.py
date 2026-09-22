"""Small HTTP boundary for a future hosted Litmus deployment."""

from types import TracebackType
from urllib.parse import urlparse
from typing_extensions import Self

from litmus.client.models import JsonValue

import httpx


class Client:
  """Send authenticated requests to a caller-selected Litmus deployment.

  No hosted service ships in the first local release. This transport does not
  imply that any particular endpoint or authentication flow is available.
  """

  def __init__(
    self,
    base_url: str,
    *,
    token: str | None = None,
    timeout: float = 30,
    transport: httpx.BaseTransport | None = None,
  ):
    """Use HTTPS, or HTTP for an explicitly selected loopback development host."""
    parsed = urlparse(base_url)
    if parsed.scheme != 'https' and not (
      parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1', '::1')
    ):
      raise ValueError('Use HTTPS, or HTTP on a loopback development host')
    if (
      not parsed.hostname
      or parsed.username
      or parsed.password
      or parsed.query
      or parsed.fragment
    ):
      raise ValueError(
        'The API URL must be a host and optional path, without credentials'
      )
    self.http = httpx.Client(
      base_url=base_url.rstrip('/') + '/',
      headers={'Authorization': f'Bearer {token}'} if token else {},
      timeout=timeout,
      transport=transport,
      follow_redirects=False,
    )

  def request(
    self, method: str, path: str, *, body: JsonValue = None
  ) -> httpx.Response:
    """Request a relative versioned route without forwarding credentials elsewhere."""
    parsed = urlparse(path)
    if (
      parsed.scheme
      or parsed.netloc
      or not path.startswith('v1/')
      or '\\' in path
      or '%' in parsed.path
      or any(part in ('.', '..') for part in parsed.path.split('/'))
    ):
      raise ValueError('Expected a relative v1/ route without traversal')
    response = self.http.request(method, path, json=body)
    response.raise_for_status()
    return response

  def close(self):
    """Release HTTP connections."""
    self.http.close()

  def __enter__(self) -> Self:
    """Use the client as a context manager."""
    return self

  def __exit__(
    self,
    exception_type: type[BaseException] | None,
    exception: BaseException | None,
    traceback: TracebackType | None,
  ):
    """Release connections after a context block."""
    self.close()
