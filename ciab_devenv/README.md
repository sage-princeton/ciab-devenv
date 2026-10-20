# Host orchestration

This Python package implements `devctl`: it selects a source worktree, manages
private local state, and manages service containers and the isolated Ubuntu run machine.
It contains no CRUX feature scenarios or acceptance criteria.

**Key points:** the host orchestrates; the production systemd unit executes CRUX. Source and caller
inputs are copied root-owned into the machine. Credentials come from the caller's direnv environment.
Use the [root runbook](../README.md#developer-runbook-start-a-local-crux) to operate
the environment and `./devctl --usage` for all command options.

| File | Responsibility |
| --- | --- |
| `__main__.py` | Python module entry point used by the root `devctl` script |
| `__init__.py` | Package identity |
| `cli.py` | Argument parsing, explicit OrbStack Compose calls, execution, report export and lifecycle commands |
| `config.py` | Named instances, private credentials/certificates, tracked-source snapshots, input staging and live-service overrides |
| `machine.py` | Isolated Ubuntu lifecycle, source validation, production provisioning, job dispatch and cached reports |

Each instance uses `~/.local/state/ciab-devenv/<name>` and Docker project
`ciab-<name>`. `CIAB_STATE_ROOT` changes the host state parent. Never print the
generated `instance.json` or private secret transport files in diagnostics.

Changes to orchestration should preserve explicit instance scope, error exit
codes, credential exclusion and source-switch protection. Exercise changed CLI
commands practically and run the [environment tests](../tests/README.md).
Machine execution is documented in [services/](../services/README.md).
