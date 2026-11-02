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

Local resource drivers use the selected production lifecycle when available.
`bootstrap` reconciles services then the named Box; `reset --confirm NAME` deletes
only that environment's isolated machine and labeled Compose resources.

Sources with native bundling use that implementation for payload assembly and
Box staging. Earlier source revisions use their production install/configure
scripts directly. Both leave the Run stopped until `devctl run`.
