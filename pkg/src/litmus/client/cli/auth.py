"""`litmus auth login|logout|status`: signing in to a deployment.

Policy 02 interfaces Rule 7.5 and access Rules 12 and 17.2. `login` runs platform's
device flow through the deployment's edge (a self-hosted edge forwards `/v1/platform` to
the hosted issuer, access Rule 13.4), or keeps an API key given with `--api-key-file`.
`logout` revokes the login at platform and forgets it. No command prints a credential.
"""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import webbrowser

from litmus.client.cli.context import Context
from litmus.client.cli.credentials import Key, Login
from litmus.client.models import JsonObject, JsonValue
from litmus.client.sdk.auth import claims, poll_device, revoke, start_device
from litmus.client.sdk.client import ProblemError


def add_commands(
  commands: 'argparse._SubParsersAction[argparse.ArgumentParser]',
  common: argparse.ArgumentParser,
):
  """Register the `auth` group."""
  group = commands.add_parser(
    'auth', help='Sign in to the deployment, or out.', parents=[common]
  )
  verbs = group.add_subparsers(dest='verb', required=True, metavar='VERB')
  login = verbs.add_parser(
    'login',
    parents=[common],
    help='Sign in with the device flow, or keep an API key.',
    description='Sign in with the device flow: approve the code shown in the app. '
    'With --api-key-file, keep an API key instead (for agents and CI).',
  )
  login.add_argument(
    '--api-key-file',
    type=Path,
    help='A file holding an API key (lt_…); `-` reads standard input.',
  )
  login.add_argument(
    '--no-browser', action='store_true', help='Do not open the approval page.'
  )
  login.set_defaults(handler=run_login)
  logout = verbs.add_parser(
    'logout', parents=[common], help='Revoke the login and forget it.'
  )
  logout.set_defaults(handler=run_logout)
  status = verbs.add_parser(
    'status', parents=[common], help='Show which credential commands send.'
  )
  status.set_defaults(handler=run_status)


def read_key(path: Path) -> str:
  """An API key from a file, or standard input for `-`.

  Raises:
    ValueError: The file does not hold an API key.
  """
  text = sys.stdin.read() if str(path) == '-' else path.read_text()
  key = text.strip()
  if not key.startswith('lt_') or any(c.isspace() for c in key):
    raise ValueError(f'{path} does not hold an API key (lt_…)')
  return key


def run_login(context: Context) -> int:
  """Sign in, then print the status."""
  url = context.connection.url
  args = context.args
  if args.api_key_file is not None:
    stored: Key | Login = {'kind': 'key', 'key': read_key(args.api_key_file)}
    with context.store.lock():
      context.store.put(url, stored)
    return run_status(context)
  client = context.client()
  code = start_device(client)
  context.output.note(
    f'To sign in to {url}, open {code["verification_uri_complete"]}\n'
    f'and confirm the code {code["user_code"]}. Waiting…'
  )
  if not args.no_browser and sys.stderr.isatty():
    webbrowser.open(code['verification_uri_complete'])
  grant = poll_device(client, code)
  refresh_token = grant.get('refresh_token')
  if not refresh_token:
    raise ProblemError(
      {
        'type': 'urn:litmus:problem:invalid-grant',
        'title': 'Invalid grant',
        'detail': 'Platform answered no refresh token.',
      }
    )
  login: Login = {
    'kind': 'login',
    'refresh_token': refresh_token,
    'sessions': {
      '': {
        'token': grant['access_token'],
        'expires_at': datetime.now(timezone.utc).timestamp() + grant['expires_in'],
      }
    },
  }
  if context.connection.tenant:
    login['tenant'] = context.connection.tenant
  with context.store.lock():
    context.store.put(url, login)
  return run_status(context)


def run_logout(context: Context) -> int:
  """Revoke a login at platform, then forget whatever was kept."""
  url = context.connection.url
  with context.store.lock():
    stored = context.store.get(url)
    revoked = False
    if stored is not None and stored['kind'] == 'login':
      revoke(context.client(), stored['refresh_token'])
      revoked = True
    context.store.put(url, None)
  if stored is not None and stored['kind'] == 'key':
    context.output.note(
      'The API key was forgotten, not revoked: an admin revokes keys with '
      '`litmus keys revoke`.'
    )
  context.output.body(
    {'url': url, 'signed_out': stored is not None, 'revoked': revoked}
  )
  return 0


def described(credential: str) -> JsonObject:
  """What a credential's claims say, never the credential itself."""
  found = claims(credential)
  expires = found.get('exp')
  scope = found.get('scope')
  audience = found.get('aud')
  result: JsonObject = {
    'kind': found.get('kind'),
    'subject': found.get('sub'),
    'tenant': found.get('tenant'),
    'scopes': list[JsonValue](scope.split()) if isinstance(scope, str) else [],
    'audiences': audience if isinstance(audience, list) else [audience],
    'expires_at': datetime.fromtimestamp(expires, timezone.utc).isoformat()
    if isinstance(expires, (int, float))
    else None,
  }
  if 'agent' in found:
    result['agent'] = found['agent']
  return result


def run_status(context: Context) -> int:
  """Print the connection and the credential commands send, described by its claims."""
  connection = context.connection
  sessions = context.sessions()
  try:
    credential = sessions.credential(tenant=True)
  except ProblemError as error:
    if error.problem['type'] != 'urn:litmus:problem:tenant-required':
      raise
    credential = sessions.credential(tenant=False)
  status: dict[str, JsonValue] = {
    'url': connection.url,
    'url_source': connection.source,
    'origin': credential.origin,
    'credential': described(credential.token),
  }
  if credential.origin in ('key', 'login'):
    status['store'] = context.store.description
  context.output.body(status)
  return 0
