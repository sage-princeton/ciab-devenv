# Environment tests

Regression tests for environment orchestration and fixtures. Requires Python 3.12
and permission to bind localhost for HTTP fixtures.

## Development

From the repository root:

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q ciab_devenv devops monitoring services verification tests
shellcheck devctl
```

Run Ruff inside the provisioned Box and exercise changed commands through the
[parent runbook](../README.md). Feature acceptance evidence belongs in CRUX PRs.
