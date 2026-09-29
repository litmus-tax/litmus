"""The HTTP boundary to one Litmus deployment: versioned routes over one transport.

Every non-2xx answer is raised as `ProblemError` carrying its problem JSON (policy 03
contract Rule 14); an unreachable deployment is the problem `unavailable`.
"""

from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
import json
from types import TracebackType
from urllib.parse import urlparse
from typing_extensions import Self, cast

import httpx

from litmus.client.models import JsonValue, Problem

Params = Mapping[str, str | Sequence[str]]
"""Query parameters; a sequence repeats the parameter."""
Files = Sequence[tuple[str, tuple[str, bytes, str]]]
"""Multipart files as `(field, (filename, content, media type))`."""


class ProblemError(Exception):
  """A refused or failed request, with the problem the deployment answered."""

  def __init__(self, problem: Problem, response: httpx.Response | None = None):
    """Keep the problem, and the response when there was one."""
    super().__init__(problem.get('detail') or problem.get('title') or problem['type'])
    self.problem = problem
    self.response = response


def problem_of(response: httpx.Response) -> Problem:
  """The problem a non-2xx response carries, or one built from its status line."""
  try:
    body = cast(JsonValue, response.json())
  except (json.JSONDecodeError, UnicodeDecodeError):
    body = None
  if isinstance(body, dict) and isinstance(body.get('type'), str):
    return cast(Problem, body)
  problem: Problem = {
    'type': 'about:blank',
    'title': response.reason_phrase or 'Error',
    'status': response.status_code,
  }
  if isinstance(body, dict):
    detail = body.get('error_description') or body.get('error') or body.get('detail')
    if isinstance(detail, str):
      problem['detail'] = detail
  elif response.text:
    problem['detail'] = response.text[:500]
  return problem


def unavailable(url: str, error: Exception) -> Problem:
  """The problem for a deployment that cannot be reached."""
  return {
    'type': 'urn:litmus:problem:unavailable',
    'title': 'Unavailable',
    'detail': f'Cannot reach {url}: {error}',
  }


def checked_path(path: str) -> str:
  """A relative `v1/` route, refusing anything that could leave the deployment."""
  path = path.removeprefix('/')
  parsed = urlparse(path)
  if (
    parsed.scheme
    or parsed.netloc
    or parsed.query
    or not path.startswith('v1/')
    or '\\' in path
    or '%' in parsed.path
    or any(part in ('.', '..') for part in parsed.path.split('/'))
  ):
    raise ValueError('Expected a relative v1/ route without traversal')
  return path


class Client:
  """Send authenticated requests to one caller-selected Litmus deployment."""

  def __init__(
    self,
    base_url: str,
    *,
    token: str | None = None,
    timeout: float = 60,
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
    self.base_url = base_url.rstrip('/')
    self.http = httpx.Client(
      base_url=self.base_url + '/',
      timeout=timeout,
      transport=transport,
      follow_redirects=False,
    )
    self.token = token

  def headers(self, extra: Mapping[str, str] | None) -> dict[str, str]:
    """The request headers: the bearer credential, if any, and `extra`."""
    headers = {'Authorization': f'Bearer {self.token}'} if self.token else {}
    headers.update(extra or {})
    return headers

  def request(
    self,
    method: str,
    path: str,
    *,
    params: Params | None = None,
    body: JsonValue = None,
    form: Mapping[str, str] | None = None,
    files: Files | None = None,
    headers: Mapping[str, str] | None = None,
    check: bool = True,
  ) -> httpx.Response:
    """Request a relative versioned route without forwarding credentials elsewhere.

    Args:
      method: The HTTP method.
      path: A `v1/…` route; a leading slash (as in `Location`) is accepted.
      params: Query parameters.
      body: A JSON body.
      form: A form-encoded body, instead of `body`.
      files: Multipart files, instead of `body`.
      headers: Extra headers.
      check: Raise `ProblemError` for a non-2xx answer.

    Raises:
      ProblemError: The deployment refused the request, or could not be reached.
    """
    route = checked_path(path)
    try:
      response = self.http.request(
        method,
        route,
        params=params,
        json=body if form is None and files is None and body is not None else None,
        data=form,
        files=files,
        headers=self.headers(headers),
      )
    except httpx.TransportError as error:
      raise ProblemError(unavailable(self.base_url, error)) from error
    if check and not response.is_success:
      raise ProblemError(problem_of(response), response)
    return response

  @contextmanager
  def stream(
    self, method: str, path: str, *, params: Params | None = None
  ) -> Generator[httpx.Response]:
    """Stream a route's body, for exports and evidence objects.

    Raises:
      ProblemError: As `request`.
    """
    route = checked_path(path)
    try:
      with self.http.stream(
        method, route, params=params, headers=self.headers(None)
      ) as response:
        if not response.is_success:
          response.read()
          raise ProblemError(problem_of(response), response)
        yield response
    except httpx.TransportError as error:
      raise ProblemError(unavailable(self.base_url, error)) from error

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
