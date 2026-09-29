"""Public wire shapes the client reads: problems, jobs and platform's grants."""

from typing_extensions import Literal, NotRequired, Required, TypeAlias, TypedDict

JsonValue: TypeAlias = (
  str | int | float | bool | None | list['JsonValue'] | dict[str, 'JsonValue']
)
JsonObject: TypeAlias = dict[str, JsonValue]
Service = Literal['platform', 'portfolio', 'evm', 'hl', 'dydx', 'cex']
SERVICES: tuple[Service, ...] = ('platform', 'portfolio', 'evm', 'hl', 'dydx', 'cex')
"""Every service a deployment may serve under `/v1/<service>` (policy 02 topologies term 1)."""
Unit = Literal['evm', 'hl', 'dydx', 'cex']
UNITS: tuple[Unit, ...] = ('evm', 'hl', 'dydx', 'cex')


class Problem(TypedDict, total=False):
  """An RFC 9457 problem: every non-2xx answer (policy 03 contract Rule 14)."""

  type: Required[str]
  """`urn:litmus:problem:<name>`, or `about:blank`."""
  title: str
  status: int
  detail: str
  instance: str
  errors: list[JsonValue]


JobStatus = Literal['queued', 'running', 'succeeded', 'failed', 'cancelled']
FINISHED: tuple[JobStatus, ...] = ('succeeded', 'failed', 'cancelled')


class Progress(TypedDict):
  """One progress message of a job."""

  at: str
  message: str


class Job(TypedDict, total=False):
  """A job as `GET /jobs/{j}` serves it (policy 03 contract Rule 4.4); portfolio adds `children`."""

  id: Required[str]
  kind: str
  status: Required[JobStatus]
  progress: list[Progress]
  result: JsonValue
  error: JsonValue
  children: list[JsonValue]


class DeviceCode(TypedDict):
  """Platform's answer to `POST /device/code` (RFC 8628 section 3.2)."""

  device_code: str
  user_code: str
  verification_uri: str
  verification_uri_complete: str
  expires_in: int
  interval: int


class TokenGrant(TypedDict):
  """A successful `POST /token` answer: a session token, and with a login its next refresh token."""

  access_token: str
  token_type: str
  expires_in: int
  refresh_token: NotRequired[str]
  """The login (`lr_…`), rotated on every refresh grant."""
  scope: NotRequired[str]
