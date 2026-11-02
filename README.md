# CRUX local development environment

Test one selected CRUX worktree on an isolated OrbStack Ubuntu Box using production
installers and systemd services. This repository supplies infrastructure, reusable
fixtures, execution and evidence collection. Feature scenarios and assertions belong
in the implementing CRUX PR, with temporary scripts outside Git.

Requires macOS, running OrbStack, Docker Compose v2, Python 3.12, Git, OpenSSL and
direnv. Set dedicated test-provider credentials in the ignored `.envrc`, authorize
with `direnv allow`, and prepare bounded Run inputs outside the checkout.

```sh
direnv exec . ./devctl --name review bootstrap --source /absolute/crux-worktree --drop-in /private/inputs
./devctl --name review doctor
./devctl --name review check
./devctl --name review run --timeout 300
./devctl --name review report
./devctl --name review report REPORT_ID --output /private/evidence
./devctl --name review down
# After inspecting and citing exported evidence:
./devctl --name review reset --confirm review
```

Provisioning leaves the Run stopped; `run` starts it explicitly. Inspect actual
artifacts and traces. Reprovision after changing source or inputs; use a fresh named
instance when fresh state matters. After evidence is exported and cited, delete
the machine, containers, volumes and local data, including after failures.

For ACP, add `--scaffold acp --platform codex` at bootstrap and pass a private
`--prompt-file` to `run`. See [operations.md](operations.md) for task controls,
service overrides and fixture APIs, [design.md](design.md) for component boundaries,
[tests](tests/README.md) for environment checks, and `./devctl --usage` for CLI options.

Reserve three consecutive ports for each environment: the base `--port` for the
Langfuse UI, plus two loopback-only fixture ports. Box setup installs `socat` and
manages its local fixture relays; no Docker daemon network override is needed.

Inspect a resolved production graph without resources or credentials:

```sh
./devctl plan --source /path/to/crux-worktree --spec /private/resolved-run.json
```

Public Run/controller configuration is resolved by CRUX's deployment CLI; this
inspection command accepts the resulting resource graph.

`devctl package-inventory` records installed OS/Python/JavaScript packages from the
Box. Weekly Dependabot PRs update declared dependencies; the daily service-image
audit preserves SPDX and vulnerability reports in GitHub Actions.

## Development

Run the [environment checks](tests/README.md#development), then exercise changed
commands through a fresh named environment above. Feature-specific scenarios and
acceptance evidence stay in the implementing CRUX PR.
