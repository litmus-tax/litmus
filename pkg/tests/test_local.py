"""`litmus local`: thin wrappers over platform's `scripts/local.py` (interfaces Rule 7.8)."""

from collections.abc import Callable
from pathlib import Path
import subprocess

import pytest

from conftest import Result


@pytest.fixture
def platform(tmp_path: Path) -> Path:
  """A platform checkout beside the working directory, with its script and interpreter."""
  checkout = tmp_path / 'platform'
  (checkout / 'scripts').mkdir(parents=True)
  (checkout / 'scripts' / 'local.py').write_text('')
  (checkout / '.venv' / 'bin').mkdir(parents=True)
  (checkout / '.venv' / 'bin' / 'python').write_text('')
  return checkout


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
  """Record the commands run instead of running them; Docker is installed."""
  recorded: list[list[str]] = []

  def fake(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
    """Answer exit code 3, to check it is passed through."""
    recorded.append(command)
    return subprocess.CompletedProcess(command, 3)

  monkeypatch.setattr('litmus.client.cli.local.subprocess.run', fake)
  monkeypatch.setattr(
    'litmus.client.cli.local.shutil.which', lambda name: '/bin/docker'
  )
  return recorded


def test_verbs_run_platforms_script(
  run: Callable[..., Result], platform: Path, calls: list[list[str]]
):
  """Each verb runs `scripts/local.py` with the same arguments; its exit code is kept.

  # policy 02 interfaces rule 7.8
  """
  script = str(platform / 'scripts' / 'local.py')
  python = str(platform / '.venv' / 'bin' / 'python')
  result = run('local', 'up', '--stable', '--ref', 'v1', '--owner', 'me@example.com')
  assert result.code == 3
  assert calls[-1] == [
    python,
    script,
    'up',
    '--stable',
    '--owner',
    'me@example.com',
    '--ref',
    'v1',
  ]
  run('local', 'logs', 'api', 'worker', '-f')
  assert calls[-1][2:] == ['logs', '--follow', 'api', 'worker']
  run('local', 'down', '--env-file', 'deploy.env')
  assert calls[-1][2:] == ['down', '--env-file', 'deploy.env']


def test_platform_checkout_is_found_or_named(
  run: Callable[..., Result],
  platform: Path,
  calls: list[list[str]],
  monkeypatch: pytest.MonkeyPatch,
  tmp_path: Path,
):
  """The checkout is `--platform`, `LITMUS_PLATFORM_DIR`, or a `platform/` above here."""
  nested = tmp_path / 'litmus' / 'exports'
  nested.mkdir(parents=True)
  monkeypatch.chdir(nested)
  assert run('local', 'status').code == 3
  assert calls[-1][1] == str(platform / 'scripts' / 'local.py')
  missing = run('local', 'status', env={'LITMUS_PLATFORM_DIR': str(tmp_path / 'none')})
  assert missing.code == 1 and 'has no scripts/local.py' in missing.json()['detail']


def test_requires_docker(
  run: Callable[..., Result], platform: Path, monkeypatch: pytest.MonkeyPatch
):
  """Without Docker the commands refuse, saying so."""
  monkeypatch.setattr('litmus.client.cli.local.shutil.which', lambda name: None)
  result = run('local', 'up')
  assert result.code == 1 and 'requires Docker' in result.json()['detail']
