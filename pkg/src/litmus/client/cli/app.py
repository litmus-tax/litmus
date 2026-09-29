"""The `litmus` command: one public CLI over HTTP only (policy 02 interfaces Rule 7).

Every command talks to the connected deployment's public routes; nothing runs in-process
(Rule 7.9). Errors print problem JSON and exit 1; usage errors exit 2 (Rule 7.3).
"""

import argparse
from collections.abc import Callable, Mapping, Sequence
import os
from pathlib import Path
import sys
from typing_extensions import TextIO

import httpx

from litmus.client import __version__
from litmus.client.cli import apply, auth, discovery, invoke
from litmus.client.cli.commands import commands as route_commands
from litmus.client.cli.context import Context
from litmus.client.cli.credentials import Store, default_store
from litmus.client.cli.output import Output
from litmus.client.cli.routes import Tree
from litmus.client.models import Problem
from litmus.client.sdk.client import ProblemError

Handler = Callable[[Context], int]


def common_options() -> argparse.ArgumentParser:
  """Options every command accepts, before or after its name."""
  common = argparse.ArgumentParser(add_help=False)
  common.add_argument(
    '--url',
    default=argparse.SUPPRESS,
    help='The deployment (default: LITMUS_URL, litmus.toml [connection], else local).',
  )
  common.add_argument(
    '--tenant',
    default=argparse.SUPPRESS,
    help='The tenant a login acts in (default: LITMUS_TENANT, litmus.toml).',
  )
  common.add_argument(
    '--json',
    action='store_true',
    default=argparse.SUPPRESS,
    help='Print exact API bodies (the default when stdout is not a terminal).',
  )
  return common


def parser() -> argparse.ArgumentParser:
  """The whole command line."""
  common = common_options()
  root = argparse.ArgumentParser(
    prog='litmus',
    parents=[common],
    description='The Litmus CLI: every command calls the connected deployment over '
    'HTTP. Output is the API body with --json or when piped; errors are problem JSON '
    '(exit 1), usage errors exit 2.',
  )
  root.add_argument('--version', action='version', version=f'litmus-tax {__version__}')
  commands = root.add_subparsers(dest='command', required=True, metavar='COMMAND')
  auth.add_commands(commands, common)
  discovery.add_commands(commands, common)
  apply.add_commands(commands, common)
  tree = Tree(commands, common)
  for command in route_commands():
    tree.add(command, invoke.run)
  return root


def main(
  argv: Sequence[str] | None = None,
  *,
  environ: Mapping[str, str] | None = None,
  transport: httpx.BaseTransport | None = None,
  store: Callable[[Mapping[str, str]], Store] = default_store,
  stdout: TextIO | None = None,
  stderr: TextIO | None = None,
) -> int:
  """Run one command and return its exit code.

  Args:
    argv: The arguments after `litmus`.
    environ: The environment (default `os.environ`).
    transport: An HTTP transport, for tests.
    store: Builds the credential store from the environment.
    stdout: Where results go.
    stderr: Where progress, hints and human-readable errors go.
  """
  out = stdout or sys.stdout
  args = parser().parse_args(list(sys.argv[1:] if argv is None else argv))
  output = Output(
    json=bool(getattr(args, 'json', False)) or not out.isatty(),
    stdout=out,
    stderr=stderr or sys.stderr,
  )
  context = Context(
    args=args,
    environ=os.environ if environ is None else environ,
    output=output,
    cwd=Path.cwd(),
    transport=transport,
    store_factory=store,
  )
  handler: Handler = args.handler
  try:
    return handler(context)
  except ProblemError as error:
    return output.problem(error.problem)
  except (ValueError, OSError) as error:
    problem: Problem = {
      'type': 'urn:litmus:problem:validation',
      'title': 'Invalid input',
      'detail': str(error),
    }
    return output.problem(problem)
  except KeyboardInterrupt:
    output.note('interrupted')
    return 130
  finally:
    client = context.cache.get('client')
    if client is not None:
      client.close()  # pyright: ignore[reportAttributeAccessIssue]
