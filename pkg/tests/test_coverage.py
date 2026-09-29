"""Every public route has a command and every command a route (interfaces Rule 7.10.2)."""

import json
from pathlib import Path

from litmus.client.cli.commands import UNITS, commands, unit_commands
from litmus.client.cli.index import route, routes_of
from litmus.client.models import SERVICES

SNAPSHOTS = Path(__file__).resolve().parents[2] / 'openapi'
METHODS = ('get', 'post', 'put', 'patch', 'delete')

DISCOVERY = {('GET', f'/v1/{s}/capabilities') for s in SERVICES}
"""`litmus capabilities` reads every service's `/capabilities` (Rule 7.6)."""
SESSION = {
  ('POST', '/v1/platform/device/code'),
  ('POST', '/v1/platform/token'),
  ('POST', '/v1/platform/revoke'),
}
"""`litmus auth login|logout|status` (Rule 7.5)."""
APPLY = {('POST', '/v1/portfolio/portfolios/{portfolio_id}/apply')}
"""`litmus apply` (Rule 8)."""
NOT_FOR_CLIENTS = {
  ('GET', '/v1/platform/.well-known/jwks.json'),
  ('GET', '/v1/platform/.well-known/openid-configuration'),
  ('GET', '/v1/platform/revocations'),
  *(
    ('POST', f'/v1/platform/{path}')
    for path in (
      'login/code',
      'login/code/verify',
      'login/password',
      'signup',
      'login/email-verification',
      'login/password-reset',
      'login/password-reset/confirm',
      'login/social/callback',
      'login/refresh',
      'logout',
      'device/{user_code}/approve',
      'device/{user_code}/deny',
    )
  ),
  ('GET', '/v1/platform/login/social/{provider}'),
  ('GET', '/v1/platform/device/{user_code}'),
}
"""Routes for verifiers (keys and revocations) and for the app's own login pages, which
the app's server calls on a person's behalf (access Rule 17); a CLI has no use for them.
Rule 7.10.2 does not exempt them yet: specs#61."""


def served() -> set[tuple[str, str]]:
  """Every route of the committed OpenAPI snapshots."""
  found: set[tuple[str, str]] = set()
  for service in SERVICES:
    document = json.loads((SNAPSHOTS / f'{service}.json').read_text())
    for path, operations in document['paths'].items():
      found |= {(m.upper(), path) for m in operations if m in METHODS}
  return found


def covered() -> set[tuple[str, str]]:
  """The routes the commands call."""
  found: set[tuple[str, str]] = set()
  for command in commands():
    if not routes_of(command):
      continue
    for path in filter(None, (command.path, command.alternate)):
      services = SERVICES if command.service == '{service}' else (command.service,)
      for service in services:
        if route(service, command.method, path) is None:
          continue
        filled = path.replace('{service}', service)
        for name, value in command.fixed.items():
          filled = filled.replace('{' + name + '}', value)
        found.add((command.method, filled))
  return found


def generic(route: tuple[str, str]) -> tuple[str, str]:
  """A route with fixed path parameters put back, as OpenAPI names it."""
  method, path = route
  for unit in UNITS:
    path = path.replace(f'/resources/{unit}/', '/resources/{unit}/')
  return method, path


def test_every_route_has_a_command():
  """No public route lacks a command, except verifier and app-login routes.

  # policy 02 interfaces rule 7.10.2
  """
  calls = {generic(r) for r in covered()}
  assert served() - calls - DISCOVERY - SESSION - APPLY - NOT_FOR_CLIENTS == set()


def test_every_command_has_a_route():
  """Every command calls a served route; unit commands exist only where the unit serves it.

  # policy 02 interfaces rule 7.10.2
  """
  unit_words = {c.words for u in UNITS for c in unit_commands(u)}
  for command in commands():
    if command.words in unit_words and not routes_of(command):
      continue
    assert routes_of(command), command.words
  assert {generic(r) for r in covered()} <= served()
  hl = {c.words for c in unit_commands('hl') if routes_of(c)}
  assert ('hl', 'edits', 'list') not in hl and ('hl', 'usage') in hl
