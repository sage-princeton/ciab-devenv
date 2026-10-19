# Host orchestration

This Python package implements `devctl`: it selects a source worktree, manages
private local state, and launches OrbStack containers or isolated machines.
It contains no CRUX feature scenarios or acceptance criteria.

**Key points:** the host orchestrates; the runner executes. Source and caller
inputs are staged read-only. Credentials come from the caller's direnv environment.
Use the [root runbook](../README.md#developer-runbook-start-a-local-crux) to operate
the environment and `./devctl --usage` for all command options.

| File | Responsibility |
| --- | --- |
| `__main__.py` | Python module entry point used by the root `devctl` script |
| `__init__.py` | Package identity |
| `cli.py` | Argument parsing, explicit OrbStack Compose calls, execution, report export and lifecycle commands |
| `config.py` | Named instances, private credentials/certificates, tracked-source snapshots, input staging and live-service overrides |
| `machine.py` | Isolated Ubuntu creation, staging and invocation of production provisioning scripts |

Each instance uses `~/.local/state/ciab-devenv/<name>` and Docker project
`ciab-<name>`. `CIAB_STATE_ROOT` changes the host state parent. Never print the
generated `instance.json` or private secret transport files in diagnostics.

Changes to orchestration should preserve explicit instance scope, error exit
codes, credential exclusion and source-switch protection. Exercise changed CLI
commands practically and run the [environment tests](../tests/README.md).
Runner implementation is documented in [services/](../services/README.md).
