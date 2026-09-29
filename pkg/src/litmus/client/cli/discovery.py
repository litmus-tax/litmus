"""`litmus capabilities` and `litmus openapi <service>`: what the deployment serves.

Policy 02 interfaces Rules 5 and 7.6: `capabilities` reports what the connected
deployment actually serves (each service's `/health`, with its version, and its
`/capabilities`), never a fixed document; `openapi` prints a service's OpenAPI document.
"""

import argparse
import json

from litmus.client.cli.context import Context
from litmus.client.models import SERVICES, JsonValue
from litmus.client.sdk.client import Client


def add_commands(
  commands: 'argparse._SubParsersAction[argparse.ArgumentParser]',
  common: argparse.ArgumentParser,
):
  """Register `capabilities` and `openapi`."""
  capabilities = commands.add_parser(
    'capabilities',
    parents=[common],
    help="What the deployment serves: each service's health, version and capabilities.",
  )
  capabilities.set_defaults(handler=run_capabilities)
  openapi = commands.add_parser(
    'openapi', parents=[common], help="Print a service's OpenAPI document."
  )
  openapi.add_argument('service', choices=SERVICES)
  openapi.set_defaults(handler=run_openapi)


def answer(client: Client, path: str) -> tuple[int | None, JsonValue]:
  """A route's status and JSON body (or problem), `None` when unreachable."""
  response = client.request('GET', path, check=False)
  try:
    return response.status_code, response.json()
  except ValueError:
    return response.status_code, None


def run_capabilities(context: Context) -> int:
  """Ask every service for its health and capabilities; none needs a credential."""
  client = context.client()
  services: dict[str, JsonValue] = {}
  for service in SERVICES:
    status, health = answer(client, f'v1/{service}/health')
    if status == 404:
      services[service] = {'served': False}
      continue
    capability_status, capabilities = answer(client, f'v1/{service}/capabilities')
    services[service] = {
      'served': True,
      'healthy': status == 200,
      'health': health,
      'capabilities': capabilities if capability_status == 200 else None,
    }
  context.output.body({'url': context.connection.url, 'services': services})
  return 0


def run_openapi(context: Context) -> int:
  """Print the OpenAPI document exactly as served."""
  service = context.args.service
  response = context.client().request('GET', f'v1/{service}/openapi.json')
  output = context.output
  output.stdout.write(
    response.text if output.json else json.dumps(response.json(), indent=2)
  )
  output.stdout.write('\n')
  return 0
