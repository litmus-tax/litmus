"""The generated route index: what each public route takes and answers.

Policy 02 interfaces Rule 5.2: `routes.json` is generated from the committed OpenAPI
snapshots by `scripts/openapi.py index`, and is all the CLI knows of a route.
"""

from functools import cache
from importlib import resources
import json
import re
from typing_extensions import Literal, TypedDict, cast

from litmus.client.cli.commands import Command
from litmus.client.models import SERVICES


class Parameter(TypedDict):
  """A query parameter of a route."""

  name: str
  type: Literal['string', 'integer', 'number', 'boolean']
  repeated: bool
  choices: list[str]
  required: bool
  help: str


class Field(TypedDict):
  """A body field; `path` has two parts for a field of a nested object."""

  path: list[str]
  type: Literal['string', 'integer', 'number', 'boolean']
  repeated: bool
  choices: list[str]
  required: bool
  help: str


class Body(TypedDict):
  """A route's request body."""

  media: str
  required: bool
  fields: list[Field]


class Route(TypedDict):
  """What the CLI needs of one route."""

  summary: str
  help: str
  query: list[Parameter]
  body: Body | None
  job: bool
  """The route answers `202` (a job, or an edit)."""
  binary: bool
  """The route streams bytes rather than JSON."""


PATH_PARAMETER = re.compile(r'\{([a-z_]+)\}')
IMPLIED = ('portfolio_id', 'tenant_id', 'service', 'unit')
"""Path parameters filled from options or the command, never positionals."""


@cache
def index() -> dict[str, dict[str, Route]]:
  """The generated route index: service to `METHOD path` to route."""
  text = resources.files('litmus.client.cli').joinpath('routes.json').read_text()
  return cast(dict[str, dict[str, Route]], json.loads(text))


def route(service: str, method: str, path: str) -> Route | None:
  """One route of a service, by its path with `{service}` filled in."""
  return index().get(service, {}).get(f'{method} {path.replace("{service}", service)}')


def routes_of(command: Command) -> list[Route]:
  """The routes a command may call: one, or one per service for `{service}` paths."""
  services = SERVICES if command.service == '{service}' else (command.service,)
  found = [route(s, command.method, command.path) for s in services]
  return [r for r in found if r is not None]


def positionals(command: Command) -> list[str]:
  """The path parameters a command takes as positional arguments, in path order."""
  names = PATH_PARAMETER.findall(command.path)
  return [n for n in names if n not in IMPLIED]


def argument(name: str) -> str:
  """A path parameter's argument name: `resource_id` is `resource`."""
  return name.removesuffix('_id')


def escaped(text: str) -> str:
  """Help text safe for argparse's `%` formatting."""
  return text.replace('%', '%%')
