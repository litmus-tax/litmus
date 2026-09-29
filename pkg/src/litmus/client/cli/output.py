"""What commands print: the API body for machines, a plain rendering for people.

Policy 02 interfaces Rules 7.2 and 7.3 (policy 03 contract Rules 14.4 and 18.2): when
stdout is not a TTY, or with `--json`, output is exactly the API response body; on a TTY
it is a human rendering of the same body, computing nothing the body does not hold.
Errors print the problem object (as JSON, or one line on a TTY) and exit 1; progress
and hints go to stderr.
"""

from dataclasses import dataclass
import json
import shutil
import sys
from typing_extensions import TextIO

from litmus.client.models import JsonValue, Problem

MAX_COLUMNS = 8
MAX_CELL = 40


@dataclass
class Output:
  """Where and how a command prints."""

  json: bool
  """Print exact API bodies (`--json`, or stdout is not a TTY)."""
  stdout: TextIO = sys.stdout
  stderr: TextIO = sys.stderr

  def body(self, value: JsonValue):
    """Print a response body."""
    if self.json:
      self.stdout.write(json.dumps(value) + '\n')
    else:
      self.stdout.write(render(value) + '\n')

  def problem(self, problem: Problem) -> int:
    """Print a problem and return the exit code 1."""
    if self.json:
      self.stdout.write(json.dumps(problem) + '\n')
    else:
      name = problem['type'].removeprefix('urn:litmus:problem:')
      text = problem.get('detail') or problem.get('title') or ''
      status = problem.get('status')
      prefix = f'error ({name}{f", {status}" if status else ""})'
      self.stderr.write(f'{prefix}: {text}\n')
      errors = problem.get('errors')
      if errors:
        self.stderr.write(json.dumps(errors, indent=2) + '\n')
    return 1

  def note(self, text: str):
    """A message for people, on stderr (progress, hints)."""
    self.stderr.write(text + '\n')
    self.stderr.flush()


def cell(value: JsonValue) -> str:
  """One table cell: scalars as text, nested values as compact JSON, cut to fit."""
  if value is None:
    text = ''
  elif isinstance(value, bool):
    text = 'yes' if value else 'no'
  elif isinstance(value, (str, int, float)):
    text = str(value)
  else:
    text = json.dumps(value, separators=(',', ':'))
  return text if len(text) <= MAX_CELL else text[: MAX_CELL - 1] + '…'


def table(rows: list[dict[str, JsonValue]]) -> str:
  """Rows as aligned columns: the keys of the rows, scalar-valued ones first."""
  if not rows:
    return '(none)'
  columns: list[str] = []
  for row in rows:
    for key in row:
      if key not in columns:
        columns.append(key)
  scalar = [
    c for c in columns if all(not isinstance(r.get(c), (dict, list)) for r in rows)
  ]
  columns = (scalar + [c for c in columns if c not in scalar])[:MAX_COLUMNS]
  cells = [[cell(row.get(column)) for column in columns] for row in rows]
  widths = [
    max(len(column), *(len(line[i]) for line in cells))
    for i, column in enumerate(columns)
  ]
  lines = ['  '.join(c.ljust(w) for c, w in zip(columns, widths)).rstrip()]
  lines += [
    '  '.join(c.ljust(w) for c, w in zip(line, widths)).rstrip() for line in cells
  ]
  width = shutil.get_terminal_size((200, 24)).columns
  return '\n'.join(line[:width] for line in lines)


def rows_of(value: list[JsonValue]) -> list[dict[str, JsonValue]] | None:
  """A list whose members are all objects, as table rows."""
  if value and all(isinstance(item, dict) for item in value):
    return [item for item in value if isinstance(item, dict)]
  return None


def fields(value: dict[str, JsonValue], indent: str = '') -> list[str]:
  """An object as `key  value` lines; nested objects indented, lists of objects as tables."""
  lines: list[str] = []
  width = max((len(key) for key in value), default=0)
  for key, item in value.items():
    if isinstance(item, dict) and item:
      lines.append(f'{indent}{key}:')
      lines.extend(fields(item, indent + '  '))
    elif isinstance(item, list) and rows_of(item) is not None:
      lines.append(f'{indent}{key}: {len(item)}')
      lines.extend(
        indent + '  ' + line for line in table(rows_of(item) or []).splitlines()
      )
    else:
      text = cell(item) if not isinstance(item, str) else item
      lines.append(f'{indent}{key.ljust(width)}  {text}')
  return lines


def render(value: JsonValue) -> str:
  """A human rendering of a body: a page as a table, an object as fields."""
  if isinstance(value, list):
    rows = rows_of(value)
    return table(rows) if rows is not None else '\n'.join(cell(v) for v in value)
  if not isinstance(value, dict):
    return cell(value) if not isinstance(value, str) else value
  lists = [
    k for k, v in value.items() if isinstance(v, list) and rows_of(v) is not None
  ]
  if len(lists) == 1 and 'next_cursor' in value:
    key = lists[0]
    rest: dict[str, JsonValue] = {
      k: v for k, v in value.items() if k != key and v is not None
    }
    head = fields(rest) if rest else []
    items = value[key]
    assert isinstance(items, list)
    return '\n'.join([*head, table(rows_of(items) or [])])
  return '\n'.join(fields(value))
