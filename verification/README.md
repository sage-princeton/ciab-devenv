# Reusable verification helpers

Feature-independent helpers for source checks, execution and artifact inspection.
Provisioning installs them at `/devenv/verification`; caller scenarios stay outside
Git. With a selected/provisioned environment:

```sh
./devctl --name review exec python -m verification.offline
./devctl --name review exec --input /private/verification python /input/check.py
```

Inspect actual outcomes and cite evidence before cleanup using the parent runbook.

## Development

Run the [environment checks](../tests/README.md#development) and invoke changed
helpers in a provisioned Box. Keep helpers independent of any CRUX feature.
