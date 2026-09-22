"""Public CLI capabilities and optional pure accounting commands."""

import argparse
import json
import sys

from litmus.client import __version__
from litmus.client.models import Capabilities


def capabilities() -> Capabilities:
  """Describe features from the installed client without copied service schemas."""
  return {
    'schema_version': '1.0',
    'release': __version__,
    'hosted_available': False,
    'direct_executable': 'litmus-dev',
    'source_units': ['hl', 'dydx', 'evm', 'cex'],
    'source_verbs': ['sync', 'query', 'state', 'items', 'verify', 'export'],
    'portfolio_verbs': [
      'accounts',
      'sync',
      'query',
      'state',
      'reconcile',
      'audit',
      'prices',
      'books',
      'items',
      'correct',
      'export',
      'replay',
    ],
    'future_auth_verbs': ['login', 'logout', 'status'],
    'future_job_verbs': ['list', 'show', 'watch', 'cancel'],
    'notes': 'Hosted commands require a deployed service; use litmus-dev for local execution.',
  }


def main(argv: list[str] | None = None) -> int:
  """Report honest hosted capabilities and dispatch optional offline accounting."""
  args = list(sys.argv[1:] if argv is None else argv)
  json_output = '--json' in args
  if args and args[0] == '--json':
    args.pop(0)
  if args and args[0] == 'accounting':
    try:
      from litmus.accounting.cli import main as accounting_main
    except ImportError:
      print(
        'Install litmus-client[accounting] for offline accounting.', file=sys.stderr
      )
      return 1
    accounting_args = args[1:]
    if json_output and '--json' not in accounting_args:
      accounting_args.insert(0, '--json')
    return accounting_main(accounting_args)
  parser = argparse.ArgumentParser(
    prog='litmus',
    description='Public client. Hosted commands are unavailable in this local release; use litmus-dev.',
  )
  parser.add_argument(
    '--json', action='store_true', help='Emit machine-readable output'
  )
  parser.add_argument('--version', action='version', version='litmus-client 0.1.0')
  parser.add_argument(
    'command',
    nargs='?',
    choices=[
      'capabilities',
      'auth',
      'hl',
      'dydx',
      'evm',
      'cex',
      'accounts',
      'sync',
      'query',
      'state',
      'reconcile',
      'audit',
      'prices',
      'books',
      'items',
      'correct',
      'export',
      'replay',
      'jobs',
      'accounting',
    ],
  )
  parser.add_argument('arguments', nargs=argparse.REMAINDER)
  parsed = parser.parse_args(args)
  if parsed.command is None:
    parser.print_help()
    return 0
  if parsed.command == 'capabilities':
    print(json.dumps(capabilities(), indent=2))
    return 0
  payload = {
    'error': 'unavailable_dependency',
    'message': 'Hosted commands are not implemented in this release. Use litmus-dev for local execution.',
    'command': parsed.command,
  }
  if json_output:
    print(json.dumps(payload))
  else:
    print(payload['message'], file=sys.stderr)
  return 1
