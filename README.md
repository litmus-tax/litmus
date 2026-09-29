# Litmus CLI

`litmus-tax` provides the public `litmus` command and a small HTTP SDK. Every command
calls a Litmus deployment's public routes over HTTP; nothing runs in-process, and the
package holds no service code ([policy 02 interfaces Rule 7][rule7]). Licensed under
[Apache-2.0](LICENSE).

```sh
python -m pip install -e './pkg[dev]'
litmus capabilities                 # what the connected deployment serves
litmus auth login                   # device flow: approve the code in the app
litmus auth status
```

## Connection

Commands go to `--url`, else `LITMUS_URL`, else `[connection] url` of the nearest
`litmus.toml` (in the working directory or a parent), else the local deployment at
`http://localhost:8080` (`url = "local"`). A login acts in `--tenant`, `LITMUS_TENANT`,
`[connection] tenant`, the tenant chosen at login, or the login's only membership.

## Credentials

1. `litmus auth login` runs platform's device flow (RFC 8628): it shows a code to
   approve at the app's `/device` page and keeps the login, a rotating refresh token,
   in the OS keychain when the optional `keychain` extra (`keyring`) has a working
   backend, otherwise in `$XDG_CONFIG_HOME/litmus/credentials.json` (mode 0600, refused
   when others can read it). `LITMUS_CREDENTIALS=file|keychain` forces one.
2. Agents and CI use an API key: `litmus auth login --api-key-file key.txt` keeps it,
   and `LITMUS_API_KEY=lt_…` is used without storing anything. Either is sent as
   `Authorization: Bearer`.
3. Against the local deployment, with nothing else configured, the development owner's
   key that `litmus local up` writes (`~/.local/share/litmus/litmus-local/owner-key`)
   is used.
4. `litmus auth logout` revokes the login at platform and forgets it. No command prints
   a credential.

## Output and errors

When stdout is not a terminal, or with `--json`, output is exactly the API response
body; on a terminal it is a table or field rendering of the same body. Errors print the
problem object (RFC 9457) and exit 1; usage errors exit 2.

## SDK

```python
from litmus.client.sdk.client import Client

with Client('https://api.litmus.tax', token='lt_…') as client:
    page = client.request('GET', 'v1/evm/resources').json()
```

A non-2xx answer raises `ProblemError` with the problem; an unreachable deployment is the
problem `unavailable`.

## Python checks

Install development tools with `python -m pip install -e './pkg[dev]'`, then run
`python scripts/check.py`. The command checks Ruff lint, formatting, and Pyright
for `pkg/src` and `pkg/tests` using that Python interpreter. In the shared Litmus
environment, use `../platform/.venv/bin/python scripts/check.py` (or
`.venv/bin/python scripts/check.py` from platform).

`scripts/check.py` runs `scripts/structure.py` first. It checks the package against
the module map in `structure.toml`, rendered as tables in
[docs/architecture.md](docs/architecture.md): every module needs an entry, no module
may exceed 400 lines unless its entry says `split_pending = N`, and a module may
import only the layers its own layer allows unless its entry says `layering = N`.
Adding a module means adding its entry; `python scripts/structure.py --print-unlisted`
drafts one, and `python scripts/structure.py --render` refreshes the tables, which
the check requires to be current.

Ruff and Pyright settings live in the repository-root `pyproject.toml` under
`[tool.ruff]` and `[tool.pyright]`. Package metadata and dependencies remain in
`pkg/pyproject.toml`. Shared tooling sections are synchronized manually across the
Litmus repositories. Choose the installed development interpreter in your editor.
See the [tooling policy](../platform/docs/technical/python-tooling.md) for details.

[rule7]: https://github.com/litmus-tax/specs/blob/main/docs/policies/02-platform/interfaces.md
