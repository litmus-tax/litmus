# Architecture

`litmus-tax` is the public surface: the `litmus` command and an HTTP SDK, with no dependency on private Litmus packages and no service code (policy 02 interfaces Rule 7.9). `models` holds the public wire shapes; `sdk/` is the HTTP boundary to one deployment (routes, problems, platform's grants); `cli/` is the command line: connection and credentials, output, and one module per command group. The package root carries only the version.

## Module map

`scripts/check.py` runs `scripts/structure.py` first. `structure.toml` is the source of truth: it declares the layers (top-level packages, or root modules named by their stem), the layers each may import, and one entry per module with its responsibility. The check fails when a module under `pkg/src/litmus/client` has no entry, when an entry names a module that no longer exists, when a module exceeds 400 lines without `split_pending = N`, when a module imports a layer outside its allowance without `layering = N` (issue N tracks the violation; remove the import and the marker together), or when the tables below are stale. Paths are relative to `pkg/src/litmus/client/`; an `__init__.py` holding nothing but a docstring needs no entry. `python scripts/structure.py --print-unlisted` drafts entries for unknown modules and `python scripts/structure.py --render` regenerates the tables below. Edit `structure.toml`, not the tables.

<!-- structure:begin -->
### Root

| Module | Responsibility | May import |
| --- | --- | --- |
| `__init__.py` | Package docstring and `__version__`. | — |
| `models.py` | Public wire shapes the client reads: problems, jobs, platform's device code and token grants. | — |

### sdk

| Module | Responsibility | May import |
| --- | --- | --- |
| `sdk/auth.py` | Platform's grants for the CLI: device flow, refresh and revocation of a login; claims decoded for display. | `sdk`, `models` |
| `sdk/client.py` | The HTTP boundary to one deployment: relative `v1/` routes over one transport, non-2xx answers raised as problems. | `sdk`, `models` |

### cli

| Module | Responsibility | May import |
| --- | --- | --- |
| `cli/app.py` | The `litmus` entry point: the parser, common options, and problem JSON with exit codes. | `cli`, `sdk`, `models`, `__init__` |
| `cli/auth.py` | `litmus auth login\|logout\|status`. | `cli`, `sdk`, `models`, `__init__` |
| `cli/connection.py` | The deployment URL, tenant and portfolio from options, environment and `litmus.toml`. | `cli`, `sdk`, `models`, `__init__` |
| `cli/context.py` | One invocation's arguments, connection, output, client and credential. | `cli`, `sdk`, `models`, `__init__` |
| `cli/credentials.py` | Credential stores per deployment URL: the OS keychain, or a 0600 file; locked for refreshes. | `cli`, `sdk`, `models`, `__init__` |
| `cli/discovery.py` | `litmus capabilities` and `litmus openapi <service>`. | `cli`, `sdk`, `models`, `__init__` |
| `cli/output.py` | Exact API bodies for machines, tables and fields for people, problems on error. | `cli`, `sdk`, `models`, `__init__` |
| `cli/session.py` | The credential a command sends: `LITMUS_API_KEY`, a stored key or login, or the local owner key. | `cli`, `sdk`, `models`, `__init__` |
<!-- structure:end -->
