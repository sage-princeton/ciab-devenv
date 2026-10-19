# Reusable verification helpers

This directory provides generic helpers for executing and observing CRUX runs.
It contains no PR-specific scenarios, acceptance criteria or evidence files.
Create those temporarily outside git checkouts and describe them in the
implementing PR. Small scripts can be included directly in its description.

The runner mounts this package read-only at `/devenv/verification`. Its existing
Python path makes `from verification.sdk import ...` available to caller scripts.
No service or model call runs merely by importing `verification.sdk`.

| File | Purpose |
| --- | --- |
| `sdk.py` | Bounded drop-in construction from caller inputs; scaffold invocation; state/session inspection; authenticated fixture and Langfuse requests; trace polling |
| `offline.py` | Run the selected checkout's existing SDK checks and available provisioning/cost tests with model/tracing credentials removed |
| `__init__.py` | Package marker |

`case` accepts the caller's prompt and configuration fragments; its defaults are
a bounded single-phase file-producing drop-in. `invoke` runs that drop-in and
checks a caller-selected exit code. `state`, `state_dir` and `conversation` read
persisted results. `http`, `fixture` and `langfuse` query services; `traced` polls
for observations and saves their metadata. `require` checks a caller-specified
source capability. These helpers do not decide feature acceptance: the caller
supplies the scenario and its assertions.

Generated drop-ins, state, command logs and trace metadata live under the
runner's `CIAB_RUN_DIR` in the instance's `/work` volume. Each case gets a distinct
session suffix. Keep raw sessions and credentials private; inspect and sanitize
evidence before adding it to a PR.

## Use from an ad hoc verification script

Create a temporary input directory outside all repositories. Write the scenario
script there, importing helpers from `verification.sdk`, then run it through the
selected instance. `--input` mounts that directory read-only at `/input`:

```sh
direnv exec . ./devctl --name sdk exec --input /private/path/to/temporary-input python /input/check.py
./devctl --name sdk report latest
```

To run existing upstream checks without creating a scenario script:

```sh
./devctl --name sdk exec python -m verification.offline
```

Record scenarios, tested commits/local changes, commands, assertions, observed
results, report locations and remaining gaps in the PR description or comments.
Do not commit the temporary input or generated evidence to either repository.
Stop the stack and any associated machine when testing finishes, including after
failures; the root [runbook](../README.md) covers setup, observation and shutdown.
