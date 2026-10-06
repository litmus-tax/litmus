"""`litmus pnl`, `litmus books live`, reads of the live books by default, and seals before an export or a final mark (policy 05 rule 41, draft amendment of 2026-10-06)."""

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from conftest import Deployment, Result, jwt

KEY = 'lt_' + jwt(kind='key', sub='key:k_1', tenant='t_1', scope='read correct')
P = '/v1/portfolio/portfolios/main'


@pytest.fixture
def keyed(run: Callable[..., Result]) -> Callable[..., Result]:
  """Run commands with an API key and portfolio `main` in the environment."""

  def invoke(*argv: str) -> Result:
    """One command, authenticated."""
    return run(*argv, env={'LITMUS_API_KEY': KEY, 'LITMUS_PORTFOLIO': 'main'})

  return invoke


def test_policy_05_rule_41_pnl_and_the_live_books(
  keyed: Callable[..., Result], deployment: Deployment
):
  """`litmus pnl --by` reads `{P}/pnl`; `books live` their state; `books rows` and `books series` read `live` unless a revision is given."""
  deployment.on('GET', f'{P}/pnl', {'by': 'asset', 'groups': []})
  deployment.on('GET', f'{P}/books/live', {'revision_id': 'live'})
  deployment.on('GET', f'{P}/books/live/rows', {'rows': []})
  deployment.on('GET', f'{P}/books/rev1/series', {'points': []})
  assert keyed('pnl', '--by', 'asset', '--from', '2025-01-01T00:00:00Z').code == 0
  assert keyed('books', 'live').json() == {'revision_id': 'live'}
  assert keyed('books', 'rows', '--kind', 'holdings').json() == {'rows': []}
  assert keyed('books', 'series', 'rev1').json() == {'points': []}
  pnl, live, rows, series = deployment.requests
  assert pnl.url.params['by'] == 'asset' and pnl.url.params['from']
  assert (
    rows.url.path == f'{P}/books/live/rows' and rows.url.params['kind'] == 'holdings'
  )
  assert series.url.path == f'{P}/books/rev1/series'


def test_policy_05_rule_37_2_an_export_at_a_date_seals_there_first(
  keyed: Callable[..., Result], deployment: Deployment, tmp_path: Path
):
  """`books export --as-of DATE` seals the books at DATE for an export (reused here: 200), then exports that revision; neither a revision nor `--as-of` is an error."""
  deployment.on(
    'POST',
    f'{P}/books',
    {
      'revision_id': 'rev9',
      'as_of': '2025-12-31T23:00:00+00:00',
      'reason': 'export',
      'reused': True,
    },
  )
  deployment.routes[('GET', f'{P}/books/rev9/export')] = lambda request: httpx.Response(
    200, content=b'PK'
  )
  target = tmp_path / 'summary.xlsx'
  result = keyed(
    'books', 'export', '--as-of', '2025-12-31T23:00:00Z', '--format', 'summary',
    '--output', str(target),
  )  # fmt: skip
  assert result.code == 0, result.stderr
  assert target.read_bytes() == b'PK'
  seal, export = deployment.requests
  assert json.loads(seal.content) == {
    'as_of': '2025-12-31T23:00:00Z',
    'reason': 'export',
  }
  assert export.url.params['format'] == 'summary'
  assert keyed('books', 'export', '--output', str(target)).code != 0
