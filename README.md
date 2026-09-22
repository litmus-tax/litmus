# Litmus client

`litmus-client` provides the public `litmus` command, and an HTTP SDK. It has no dependency on private Litmus packages.

The first release runs locally through `litmus-dev`. Hosted commands, login and
jobs are planned: invoking them here returns exit code 1 and explains what is
unavailable.

```sh
python -m pip install -e './pkg[test]'
litmus capabilities
litmus --json cex sync  # exits 1: hosted service unavailable
pytest pkg/tests -q
```

Install the optional `accounting` extra to use pure offline accounting:

```sh
python -m pip install -e './pkg[accounting]'
litmus accounting --help
litmus accounting run ledger.json --json
```

The SDK accepts a deployment URL explicitly. It supports relative `v1/` routes,
timeouts and bearer tokens. It does not provide or promise a hosted service.

```python
from litmus.client.sdk.client import Client

with Client('https://your-deployment.example', token='your-token') as client:
    response = client.request('GET', 'v1/cex/resources')
```

Services own their Python request and response models and generate OpenAPI through
FastAPI. The client does not carry schema copies or a contract synchronization script.
Capabilities are declared as a typed Python document. The SDK accepts JSON request
values and returns HTTP responses; service-specific decoding belongs to its caller.

The package separates CLI presentation, HTTP transport, and public JSON shapes.
Successful commands return zero; runtime failures return one, and argument parsing
uses the standard usage error status. Findings belong in JSON results.

## Python checks

Install development tools with `python -m pip install -e './pkg[dev]'`, then run
`python scripts/check.py`. The command checks Ruff lint, formatting, and Pyright
for `pkg/src` and `pkg/tests` using that Python interpreter. In the shared Litmus
environment, use `../platform/.venv/bin/python scripts/check.py` (or
`.venv/bin/python scripts/check.py` from platform).

Ruff and Pyright settings live in the repository-root `pyproject.toml` under
`[tool.ruff]` and `[tool.pyright]`. Package metadata and dependencies remain in
`pkg/pyproject.toml`. Shared tooling sections are synchronized manually across the
Litmus repositories. Choose the installed development interpreter in your editor.
See the [tooling policy](../platform/docs/technical/python-tooling.md) for details.
