# Architecture

`litmus-client` is the public surface: the `litmus` command and an HTTP SDK, with no dependency on private Litmus packages. `models` holds the public wire shapes; `sdk/` is the transport toward a hosted deployment; `cli/` mounts the public commands and, when the `accounting` extra is installed, the pure accounting commands. The package root carries only the version.

## Module map

`scripts/check.py` runs `scripts/structure.py` first. `structure.toml` is the source of truth: it declares the layers (top-level packages, or root modules named by their stem), the layers each may import, and one entry per module with its responsibility. The check fails when a module under `pkg/src/litmus/client` has no entry, when an entry names a module that no longer exists, when a module exceeds 400 lines without `split_pending = N`, when a module imports a layer outside its allowance without `layering = N` (issue N tracks the violation; remove the import and the marker together), or when the tables below are stale. Paths are relative to `pkg/src/litmus/client/`; an `__init__.py` holding nothing but a docstring needs no entry. `python scripts/structure.py --print-unlisted` drafts entries for unknown modules and `python scripts/structure.py --render` regenerates the tables below. Edit `structure.toml`, not the tables.

<!-- structure:begin -->
### Root

| Module | Responsibility | May import |
| --- | --- | --- |
| `__init__.py` | Package docstring and `__version__`. | — |
| `models.py` | Public client capability and JSON request shapes. | — |

### sdk

| Module | Responsibility | May import |
| --- | --- | --- |
| `sdk/client.py` | Small HTTP boundary for a future hosted Litmus deployment: versioned endpoints over one transport. | `models` |

### cli

| Module | Responsibility | May import |
| --- | --- | --- |
| `cli/__init__.py` | The public `litmus` Typer app: capabilities, placeholder hosted commands exiting 1, and the optional pure accounting commands. | `cli`, `models`, `__init__` |
<!-- structure:end -->
