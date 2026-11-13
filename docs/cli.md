# CLI design

Why the `litmus` command is shaped as it is. The commands themselves come from the services' OpenAPI documents (`litmus <group> --help`); the routes they call are the API's conventions ([platform api-conventions](https://github.com/litmus-tax/platform/blob/main/docs/api-conventions.md)).

## HTTP only

`litmus` has no offline and no in-process commands, contains no service code and does not bundle the accounting engine (owner, 2026-09-27). `litmus-dev` and the unit data CLIs were removed; service packages keep only `litmus-<unit> debug` verbs for diagnostics that have no route, which normal work never needs. The engine library keeps its own offline `accounting` command for people who install it.

*Why:* one CLI speaking the API's shapes can be scripted against either interchangeably, and no second, in-process path can drift from the API. If our own work bypasses the API, its gaps stay invisible: agents, smoke tests and the owner's tooling use `litmus` or HTTP with platform-issued credentials. Accepted costs: every command needs a running deployment, and bulk reads stream over HTTP.

## Grammar

1. `litmus <unit> …` for each unit, one verb per common route (`resource list|create|show|rename|delete`, `sync`, `records`, `changes`, `state`, `compartments`, `items`, `verification`, `verify`, `export`, `evidence`), the optional ones where the unit's `/capabilities` declares them (`edits`, `credentials`, `probe`, `usage`), and its own (`evm networks`, `cex venues`, `cex upload`, …).
2. Portfolio verbs at the root with `--portfolio` (`accounts`, `sync`, `records`, `history`, `state`, `items`, `overview`, `valuation`, `prices`, `reconcile`, `links`, `corrections`, `counterparties`, `books`, `pnl`, `totals`, `series`, `audit`, `export`); `portfolios` and `settings`.
3. `litmus tenants|members|keys|me`, `litmus jobs list|show|watch|cancel [--service]`, `litmus auth login|logout|status`, `litmus apply`, `litmus capabilities`, `litmus openapi <service>`.
4. **Naming:** nouns for collections (`accounts`, `keys`), verbs for actions (`sync`, `reconcile`), `list|show|create|…` sub-verbs. A resource or account is addressed by name or id; names resolve through the route's `?name=` filter.
5. **Every command maps to one public route,** and there is no command for anything without one: what an agent needs gets a route first. A test can compare the command list with the OpenAPI documents.

*Why:* a client that reads each unit's `/capabilities` and OpenAPI needs no release for a unit's common verbs, and an action only the CLI or only the app can do is invisible to the others.

## Output and errors

1. When stdout is not a TTY, or with `--json`, output is exactly the API response body; on a TTY it is a human rendering.
2. Errors print the problem JSON and exit `1`; usage errors exit `2`. Progress goes to stderr.
3. Long operations wait and show progress on stderr; `--detach` prints the job instead; `jobs watch` follows a job and its children.
4. Paginated verbs print one page, or follow `next_cursor` with `--paginate` (owner, 2026-10-01: `--all` would clash with route parameters such as `edits?all`).

*Why:* scripts and agents can move between the CLI and HTTP without changing how they read results or errors.

## Credentials and connection

1. **`auth login`** runs platform's device flow against the connected deployment (approve the code at `app.litmus.tax/device`) and keeps the refresh credential in the OS keychain. Against a self-hosted deployment it signs in at the hosted platform through that deployment's edge.
2. **`LITMUS_API_KEY`** authenticates non-interactively: the CLI sends it as a Bearer header like any client, and services verify it like any credential. Keys are never exchanged for tokens.
3. **The connection** comes from `--url`, `LITMUS_URL` or `litmus.toml [connection]`, in that order; the default is local.
4. **Secrets only as `$VAR`.** In `litmus.toml`, credentials appear only as `$VARIABLE` references resolved from `.env` or the environment, never in a tracked file. Credentials are write-only: `apply` re-sends one only when the stored fingerprint differs, and no command prints one back.

*Why:* an agent uses the same CLI a person does, with a key instead of a login, and a configuration file can be committed to git and applied to a fresh tenant without ever holding a secret.

## `apply` and `local`

`apply` reconciles a `litmus.toml` with the deployment through public routes only: it plans `create`, `update`, `unchanged`, `unmanaged` or `delete`, changes nothing with `--dry-run`, deletes nothing without `--prune`, never syncs, and uploads only export files the resource does not already hold. `litmus local …` commands are thin conveniences over plain Docker Compose (render, up, down, status, logs, config, migrate); everything they do can be done without them, and hosted-only users never need them. *Why:* a file that syncs or deletes by surprise is not safe to re-run, and a local command that hides Compose would be one more thing to debug.
