"""Shared fixtures: an isolated environment, fake credentials and a fake deployment."""

import base64
from collections.abc import Callable
from dataclasses import dataclass, field
import io
import json
from pathlib import Path
from typing_extensions import Any

import httpx
import pytest

from litmus.client.cli.app import main


def jwt(**claims: object) -> str:
  """An unsigned token with `claims`: the CLI only decodes claims for display."""

  def part(value: object) -> str:
    """One base64url JWT segment."""
    return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b'=').decode()

  return f'{part({"alg": "ES256"})}.{part(claims)}.signature'


@dataclass
class Result:
  """One command's exit code and output."""

  code: int
  stdout: str
  stderr: str

  def json(self) -> Any:
    """Standard output as JSON."""
    return json.loads(self.stdout)


@dataclass
class Deployment:
  """A fake deployment: `routes` answer `(method, path)`; every request is recorded."""

  routes: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]] = field(
    default_factory=dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]]
  )
  requests: list[httpx.Request] = field(default_factory=list[httpx.Request])

  def handle(self, request: httpx.Request) -> httpx.Response:
    """Answer from `routes`, else a problem `404`."""
    self.requests.append(request)
    route = self.routes.get((request.method, request.url.path))
    if route is None:
      return httpx.Response(
        404,
        json={
          'type': 'urn:litmus:problem:not-found',
          'title': 'Not Found',
          'status': 404,
        },
        headers={'Content-Type': 'application/problem+json'},
      )
    return route(request)

  def on(self, method: str, path: str, body: object = None, status: int = 200):
    """Answer `method path` with a fixed JSON body."""
    self.routes[(method, path)] = lambda request: httpx.Response(status, json=body)


@pytest.fixture
def environ(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
  """A clean environment with private config and data directories, in an empty directory."""
  monkeypatch.chdir(tmp_path)
  return {
    'XDG_CONFIG_HOME': str(tmp_path / 'config'),
    'XDG_DATA_HOME': str(tmp_path / 'data'),
    'LITMUS_CREDENTIALS': 'file',
  }


@pytest.fixture
def deployment() -> Deployment:
  """An empty fake deployment."""
  return Deployment()


@pytest.fixture
def run(environ: dict[str, str], deployment: Deployment) -> Callable[..., Result]:
  """Run `litmus` against the fake deployment in the isolated environment."""

  def invoke(*argv: str, env: dict[str, str] | None = None) -> Result:
    """One command; `env` adds variables."""
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(
      list(argv),
      environ={**environ, **(env or {})},
      transport=httpx.MockTransport(deployment.handle),
      stdout=stdout,
      stderr=stderr,
    )
    return Result(code, stdout.getvalue(), stderr.getvalue())

  return invoke
