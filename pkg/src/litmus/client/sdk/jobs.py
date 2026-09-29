"""Following jobs and pages: polling `GET /jobs/{j}` and walking `next_cursor`.

Policy 02 interfaces Rule 12 (jobs are followed by polling) and policy 03 contract Rules
4 and 15 (the `Job` shape; every list is `{…, items|records, next_cursor}`).
"""

from collections.abc import Callable
import time
from typing_extensions import cast

from litmus.client.models import FINISHED, Job, JsonObject, JsonValue
from litmus.client.sdk.client import Client, Params


def follow(
  client: Client,
  path: str,
  *,
  update: Callable[[Job], None],
  interval: float = 1.0,
  sleep: Callable[[float], None] | None = None,
) -> Job:
  """Poll a job until it is `succeeded`, `failed` or `cancelled`, reporting each read.

  Args:
    client: The authorized client.
    path: The job's route (`Location` of a `202`, or `v1/<service>/jobs/{id}`).
    update: Called with every read of the job.
    interval: Seconds between reads; grows to at most 5.
    sleep: Waits between reads (default `time.sleep`).
  """
  sleep = sleep or time.sleep
  while True:
    job = cast(Job, client.request('GET', path).json())
    update(job)
    if job['status'] in FINISHED:
      return job
    sleep(interval)
    interval = min(5.0, interval * 1.5)


def list_key(page: JsonObject) -> str | None:
  """The member of a page holding its list (`items`, `records`, or the only list)."""
  for key in ('items', 'records'):
    if isinstance(page.get(key), list):
      return key
  lists = [k for k, v in page.items() if isinstance(v, list)]
  return lists[0] if len(lists) == 1 else None


def collect(client: Client, path: str, params: Params) -> JsonObject:
  """Every page of a list, as one page: the first page with all members and no cursor."""
  first = cast(JsonObject, client.request('GET', path, params=params).json())
  key = list_key(first)
  cursor = first.get('next_cursor')
  if key is None:
    return first
  members = list(cast(list[JsonValue], first[key]))
  while isinstance(cursor, str) and cursor:
    page = cast(
      JsonObject,
      client.request('GET', path, params={**params, 'cursor': cursor}).json(),
    )
    members.extend(cast(list[JsonValue], page.get(key) or []))
    cursor = page.get('next_cursor')
  return {**first, key: members, 'next_cursor': None}
