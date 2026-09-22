"""Public-package independence, safe transport and explicit hosted limitations."""

import json

import httpx
import pytest

from litmus.client.cli import main
from litmus.client.sdk.client import Client


def test_capabilities_are_honest(capsys):
  """Advertising the direct launcher must not advertise an available hosted API."""
  assert main(['capabilities']) == 0
  assert json.loads(capsys.readouterr().out)['hosted_available'] is False
  assert main(['--json', 'cex', 'sync']) == 1
  assert json.loads(capsys.readouterr().out)['error'] == 'unavailable_dependency'


def test_versioned_transport():
  """The SDK attaches authorization and keeps the selected API origin."""

  def handle(request):
    """Inspect the outgoing synthetic request."""
    assert str(request.url) == 'https://example.test/v1/cex/resources'
    assert request.headers['Authorization'] == 'Bearer synthetic'
    return httpx.Response(200, json={'resources': []})

  with Client(
    'https://example.test', token='synthetic', transport=httpx.MockTransport(handle)
  ) as client:
    assert client.request('GET', 'v1/cex/resources').json() == {'resources': []}


@pytest.mark.parametrize(
  'path',
  [
    'https://elsewhere.test/v1/cex',
    '//elsewhere.test/v1/cex',
    'v1/../secret',
    'v1/%2e%2e/secret',
    'v1/\\elsewhere',
  ],
)
def test_transport_rejects_origin_escape(path):
  """An arbitrary endpoint cannot exfiltrate the configured token."""
  with Client('https://example.test', token='synthetic') as client:
    with pytest.raises(ValueError):
      client.request('GET', path)


def test_rejects_plain_http_credentials():
  """Only an explicitly selected loopback host may use unencrypted HTTP."""
  with pytest.raises(ValueError):
    Client('http://example.test', token='synthetic')
