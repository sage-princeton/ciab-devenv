# Production adapters

Resolve the selected CRUX layout and invoke its production configuration scripts
on the isolated Box. Prerequisites and operational commands are in the
[parent runbook](../README.md).

## Development

Verify adapters from the repository root:

```sh
python3 -m unittest discover -s tests
```

When available, the selected source's Python contracts validate Scaffold settings.
`devctl plan` validates its resolved resource specification without provisioning.
