"""Route commands as argparse parsers, with options generated from OpenAPI.

Policy 02 interfaces Rule 5.2: CLI help comes from the OpenAPI documents. `routes.json`
is generated from the committed snapshots by `scripts/openapi.py index`; each command's
help is its route's description, each query parameter an option named after it (policy 03
contract Rule 18.1: `--from --to --kind --compartment --reference --cursor --limit`).
"""

import argparse
from collections.abc import Callable
import re
from typing_extensions import Any

from litmus.client.cli.body import add_body
from litmus.client.cli.commands import Command
from litmus.client.cli.index import (
  PATH_PARAMETER,
  Parameter,
  Route,
  argument,
  escaped,
  positionals,
  routes_of,
)
from litmus.client.models import SERVICES


def add_query(parser: argparse.ArgumentParser, parameters: list[Parameter]):
  """One option per query parameter, `--all` for a paged route."""
  seen: set[str] = set()
  for parameter in parameters:
    name = parameter['name']
    if name in seen:
      continue
    seen.add(name)
    option = '--' + name.replace('_', '-')
    options: dict[str, Any] = {
      'dest': f'q_{name}',
      'help': escaped(parameter['help']) or None,
    }
    if parameter['type'] == 'boolean':
      options['action'] = argparse.BooleanOptionalAction
    elif parameter['repeated']:
      options['action'] = 'append'
    if parameter['choices'] and parameter['type'] != 'boolean':
      options['choices'] = parameter['choices']
    if parameter['required']:
      options['required'] = True
    parser.add_argument(option, **options)
  if 'cursor' in seen:
    # policy 03 contract Rule 18.4 names the flag `--all`; a route whose own query
    # parameter is `all` (edits, Rule 7.3.3) keeps only `--all-pages` (specs#60).
    flags = ('--all-pages',) if 'all' in seen else ('--all', '--all-pages')
    parser.add_argument(
      *flags,
      dest='all_pages',
      action='store_true',
      help='Follow next_cursor and print every page as one.',
    )


def configure(parser: argparse.ArgumentParser, command: Command, found: list[Route]):
  """Arguments of a route command: positionals, `--portfolio`, `--service`, options."""
  names = PATH_PARAMETER.findall(command.path)
  if 'portfolio_id' in names:
    if command.own_portfolio:
      parser.add_argument(
        'p_portfolio_id',
        metavar='portfolio',
        nargs='?',
        help='The portfolio (default: --portfolio).',
      )
    parser.add_argument(
      '--portfolio',
      dest='portfolio',
      default=argparse.SUPPRESS,
      help='The portfolio (default: LITMUS_PORTFOLIO, litmus.toml, or the only one).',
    )
  if 'service' in names:
    parser.add_argument(
      '--service', choices=SERVICES, default='portfolio', help='The job service.'
    )
  for name in positionals(command):
    if name == 'resource_id':
      parser.add_argument(
        'p_resource_id',
        metavar='resource',
        nargs='?' if command.alternate else None,
        help='A resource name or id.',
      )
    else:
      parser.add_argument(f'p_{name}', metavar=argument(name))
  parameters = [p for r in found for p in r['query']]
  add_query(parser, parameters)
  if any(r['binary'] for r in found):
    parser.add_argument(
      '-o', '--output', help='Write the bytes to this file (default: stdout).'
    )
  body = found[0]['body']
  if body is not None:
    taken = {p['name'].replace('_', '-') for p in parameters}
    taken |= {argument(n).replace('_', '-') for n in positionals(command)}
    add_body(parser, command, body, taken)
  if command.method == 'POST':
    parser.add_argument(
      '--idempotency-key',
      help='Makes a retry return the original result (policy 03 Rules 3.5 and 4.3).',
    )
  if any(r['job'] for r in found):
    parser.add_argument(
      '--detach',
      action='store_true',
      help='Print the accepted job instead of waiting for it.',
    )


def headline(text: str, width: int = 72) -> str:
  """The start of a description, up to its first clause, cut to `width`."""
  cut = re.split(r'\. |; |: | \(|, one ', text, maxsplit=1)[0].rstrip('.')
  return cut if len(cut) <= width else cut[: width - 1].rstrip() + '…'


class Tree:
  """Nested subcommand parsers, created on first use."""

  def __init__(
    self,
    commands: 'argparse._SubParsersAction[argparse.ArgumentParser]',
    common: argparse.ArgumentParser,
  ):
    """Hang commands off the root's subcommands."""
    self.common = common
    self.groups: dict[
      tuple[str, ...], 'argparse._SubParsersAction[argparse.ArgumentParser]'
    ] = {(): commands}

  def group(
    self, words: tuple[str, ...]
  ) -> 'argparse._SubParsersAction[argparse.ArgumentParser]':
    """The subcommands of a group, creating the group's parser when missing."""
    if words not in self.groups:
      parent = self.group(words[:-1])
      text = GROUPS.get(words) or GROUPS.get(words[-1:])
      parser = parent.add_parser(words[-1], parents=[self.common], help=text)
      self.groups[words] = parser.add_subparsers(
        dest='_'.join(words) or 'command', required=True, metavar='VERB'
      )
    return self.groups[words]

  def add(self, command: Command, handler: Callable[..., int]):
    """Register a command whose route the index knows."""
    found = routes_of(command)
    if not found:
      return
    text = command.help or found[0]['help'] or found[0]['summary']
    parser = self.group(command.words[:-1]).add_parser(
      command.words[-1],
      parents=[self.common],
      help=escaped(headline(text)),
      description=escaped(text),
    )
    configure(parser, command, found)
    parser.set_defaults(handler=handler, route_command=command)


GROUPS: dict[tuple[str, ...], str] = {
  **{(u,): f'The {u} unit: resources, data, jobs and edits.' for u in SERVICES},
  ('portfolios',): 'Portfolios of the tenant.',
  ('settings',): "The portfolio's settings.",
  ('accounts',): "The portfolio's accounts.",
  ('budgets',): 'Spending budgets of the portfolio and its accounts.',
  ('prices',): 'Prices: gaps and refreshes.',
  ('links',): 'Reconciliation links.',
  ('corrections',): 'Portfolio corrections.',
  ('books',): 'Book revisions: build, list, show, export.',
  ('tenants',): 'Tenants (workspaces) of the signed-in person.',
  ('members',): "The tenant's members.",
  ('keys',): "The tenant's API keys.",
  ('jobs',): 'Jobs of any service (--service).',
  ('resource',): "The unit's resources.",
  ('edits',): "A resource's edits: staged corrections, uploads and overrides.",
  ('credentials',): "A resource's exchange credentials (never shown).",
  ('budget',): "A resource's spending budget.",
}
