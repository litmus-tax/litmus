"""Platform's grants for the CLI: the device flow, refresh and revocation of a login.

Policy 02 access Rules 8.1 and 17.2 (RFC 8628). The CLI asks for a device code, the person
approves it in the app, and the next poll answers a session token plus the login, a
refresh token (`lr_…`) that each refresh grant rotates. `POST /revoke` ends the login.
"""

from collections.abc import Callable
import base64
import json
import time
from typing_extensions import cast

from litmus.client.models import DeviceCode, JsonObject, JsonValue, Problem, TokenGrant
from litmus.client.sdk.client import Client, ProblemError, problem_of

DEVICE_GRANT = 'urn:ietf:params:oauth:grant-type:device_code'


def start_device(client: Client) -> DeviceCode:
  """Ask platform for a device code and the address where the person approves it."""
  response = client.request('POST', 'v1/platform/device/code')
  return cast(DeviceCode, response.json())


def oauth_problem(error: str, detail: str, status: int = 400) -> Problem:
  """A problem for an OAuth error answer of the token endpoint."""
  return {
    'type': f'urn:litmus:problem:{error.replace("_", "-")}',
    'title': error,
    'status': status,
    'detail': detail,
  }


def token(client: Client, form: dict[str, str]) -> TokenGrant | str:
  """Post a grant: the tokens, or the OAuth `error` code of a `400` answer.

  Raises:
    ProblemError: Any other refusal.
  """
  response = client.request('POST', 'v1/platform/token', form=form, check=False)
  if response.is_success:
    return cast(TokenGrant, response.json())
  if response.status_code == 400:
    body = cast(JsonValue, response.json())
    if isinstance(body, dict) and isinstance(body.get('error'), str):
      return cast(str, body['error'])
  raise ProblemError(problem_of(response), response)


def poll_device(
  client: Client,
  code: DeviceCode,
  *,
  sleep: Callable[[float], None] | None = None,
  clock: Callable[[], float] | None = None,
) -> TokenGrant:
  """Poll the token endpoint until the person approves or denies the code, or it expires.

  Honours `interval` and grows it by 5 s on `slow_down` (RFC 8628 section 3.5).

  Raises:
    ProblemError: Denied (`access-denied`), expired (`expired-token`) or refused.
  """
  sleep = sleep or time.sleep
  clock = clock or time.monotonic
  interval = max(1, code['interval'])
  deadline = clock() + code['expires_in']
  form = {'grant_type': DEVICE_GRANT, 'device_code': code['device_code']}
  while True:
    if clock() >= deadline:
      raise ProblemError(oauth_problem('expired_token', 'The code expired.'))
    sleep(interval)
    answer = token(client, form)
    if not isinstance(answer, str):
      return answer
    if answer == 'authorization_pending':
      continue
    if answer == 'slow_down':
      interval += 5
      continue
    details = {
      'access_denied': 'The code was denied.',
      'expired_token': 'The code expired.',
    }
    raise ProblemError(
      oauth_problem(answer, details.get(answer, f'Login refused: {answer}.'))
    )


def refresh(client: Client, refresh_token: str, *, tenant: str | None) -> TokenGrant:
  """Exchange the login for a session token, of `tenant` or tenantless, and its successor.

  Raises:
    ProblemError: The login ended or the tenant was refused (`invalid-grant`).
  """
  form = {'grant_type': 'refresh_token', 'refresh_token': refresh_token}
  if tenant is not None:
    form['tenant'] = tenant
  answer = token(client, form)
  if isinstance(answer, str):
    detail = (
      f'The login cannot act in tenant {tenant}, or it has ended.'
      if tenant is not None
      else 'The login has ended; run `litmus auth login`.'
    )
    raise ProblemError(oauth_problem(answer, detail, 401))
  return answer


def revoke(client: Client, credential: str):
  """End a login (or a job token) at platform; repeatable (`POST /revoke`)."""
  client.request('POST', 'v1/platform/revoke', form={'token': credential})


def claims(credential: str) -> JsonObject:
  """A credential's JWT claims, decoded without verification, for display only.

  An API key's `lt_` prefix is ignored (access Rule 12.2). Anything that is not a JWT
  has no claims.
  """
  parts = credential.removeprefix('lt_').split('.')
  if len(parts) != 3:
    return {}
  payload = parts[1] + '=' * (-len(parts[1]) % 4)
  try:
    decoded = json.loads(base64.urlsafe_b64decode(payload))
  except (ValueError, UnicodeDecodeError):
    return {}
  return cast(JsonObject, decoded) if isinstance(decoded, dict) else {}
