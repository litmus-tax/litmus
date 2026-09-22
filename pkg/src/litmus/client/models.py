"""Public client capability and JSON request shapes."""

from typing_extensions import Literal, TypeAlias, TypedDict

JsonValue: TypeAlias = (
  str | int | float | bool | None | list['JsonValue'] | dict[str, 'JsonValue']
)
SourceUnit = Literal['hl', 'dydx', 'evm', 'cex']


class Capabilities(TypedDict):
  """Features implemented by this client and its local companion."""

  schema_version: Literal['1.0']
  release: str
  hosted_available: Literal[False]
  direct_executable: Literal['litmus-dev']
  source_units: list[SourceUnit]
  source_verbs: list[str]
  portfolio_verbs: list[str]
  future_auth_verbs: list[str]
  future_job_verbs: list[str]
  notes: str
