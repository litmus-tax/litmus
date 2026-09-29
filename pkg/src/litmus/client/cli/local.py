"""`litmus local …`: thin conveniences over the local deployment's Docker Compose project.

Policy 02 interfaces Rule 7.8 and topologies Rule 3. Each command runs platform's
`scripts/local.py` (platform#54), which renders `infra/litmus.toml` into a Compose project
and drives it with plain `docker compose`; everything it does can be done without it.
Until the self-hosted images are published (topologies Rule 7.5), the images are built
from source, so these commands need a platform checkout: `--platform`,
`LITMUS_PLATFORM_DIR`, or a `platform/` beside the working directory or one of its
parents. They never touch a deployment's data: `down` keeps every volume.
"""

import argparse
from collections.abc import Mapping
import os
from pathlib import Path
import shutil
import subprocess
import sys

from litmus.client.cli.context import Context

SCRIPT = Path('scripts') / 'local.py'
VERBS: dict[str, str] = {
  'render': 'Render the Compose project and Caddyfile from infra/litmus.toml.',
  'up': 'Start or upgrade the deployment and wait until every service is healthy.',
  'status': 'Containers, finished one-shot jobs included; the snapshot when stable.',
  'down': 'Stop every container; volumes, keys and data are kept.',
  'logs': 'Container logs.',
  'migrate': 'Provision and migrate again (init, then migrate).',
  'bootstrap': 'Create the development owner on a fresh deployment (access Rule 14.2).',
}


def add_commands(
  commands: 'argparse._SubParsersAction[argparse.ArgumentParser]',
  common: argparse.ArgumentParser,
):
  """Register the `local` group."""
  group = commands.add_parser(
    'local',
    help='Run a local deployment with Docker Compose (requires Docker).',
    description=__doc__.split('\n\n')[1] if __doc__ else None,
  )
  verbs = group.add_subparsers(dest='local_verb', required=True, metavar='VERB')
  for verb, text in VERBS.items():
    parser = verbs.add_parser(verb, help=text, description=text)
    parser.add_argument(
      '--platform', type=Path, help='The platform checkout (LITMUS_PLATFORM_DIR).'
    )
    if verb == 'render':
      parser.add_argument('--check', action='store_true', help='Only check.')
    if verb != 'render':
      parser.add_argument('--env-file', help='The env file (default ./.env).')
    if verb in ('up', 'migrate', 'bootstrap'):
      parser.add_argument(
        '--stable', action='store_true', help='Images from a snapshot at --ref.'
      )
    if verb in ('up', 'bootstrap'):
      parser.add_argument(
        '--owner',
        help='The developer created as owner on a fresh deployment '
        '(default LITMUS_OWNER_EMAIL, else git user.email).',
      )
    if verb == 'up':
      parser.add_argument('--ref', help='With --stable: the git ref (default main).')
      parser.add_argument(
        '--build', action='store_true', help='Rebuild the live image.'
      )
      parser.add_argument(
        '--no-bootstrap',
        action='store_true',
        help='Never create the development owner.',
      )
    if verb == 'logs':
      parser.add_argument('services', nargs='*', help='Containers (default all).')
      parser.add_argument('-f', '--follow', action='store_true', help='Follow.')
    parser.set_defaults(handler=run)


def find_platform(chosen: Path | None, environ: Mapping[str, str], cwd: Path) -> Path:
  """The platform checkout that holds `scripts/local.py`.

  Raises:
    ValueError: None was named or found.
  """
  named = chosen or (
    Path(environ['LITMUS_PLATFORM_DIR']) if environ.get('LITMUS_PLATFORM_DIR') else None
  )
  candidates = (
    [named]
    if named
    else [
      path
      for directory in (cwd, *cwd.parents)
      for path in (directory, directory / 'platform')
    ]
  )
  for candidate in candidates:
    candidate = candidate.expanduser().resolve()
    if (candidate / SCRIPT).is_file():
      return candidate
  raise ValueError(
    'litmus local needs a platform checkout until the self-hosted images are '
    'published: name it with --platform or LITMUS_PLATFORM_DIR'
    + (f' ({named} has no {SCRIPT})' if named else '')
  )


def arguments(args: argparse.Namespace) -> list[str]:
  """The `scripts/local.py` command line for these arguments."""
  verb: str = args.local_verb
  result = [verb]
  for flag in ('check', 'stable', 'build', 'no_bootstrap', 'follow'):
    if getattr(args, flag, False):
      result.append('--' + flag.replace('_', '-'))
  for option in ('env_file', 'owner', 'ref'):
    value = getattr(args, option, None)
    if value:
      result += ['--' + option.replace('_', '-'), value]
  result += getattr(args, 'services', None) or []
  return result


def run(context: Context) -> int:
  """Run the verb with platform's script, passing its output and exit code through."""
  args = context.args
  if args.local_verb != 'render' and shutil.which('docker') is None:
    raise ValueError('litmus local requires Docker (docker compose)')
  platform = find_platform(args.platform, context.environ, context.cwd)
  interpreter = platform / '.venv' / 'bin' / 'python'
  python = str(interpreter) if interpreter.is_file() else sys.executable
  completed = subprocess.run(
    [python, str(platform / SCRIPT), *arguments(args)],
    cwd=context.cwd,
    env=dict(context.environ) if context.environ is not os.environ else None,
    check=False,
  )
  return completed.returncode
