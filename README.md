# CRUX local development environment

OrbStack infrastructure for running `crux-in-a-box` worktrees with real provider
inference, local services, disposable workspaces and observable execution.

This repository supplies the environment. **Feature scenarios, acceptance
criteria and assertions belong in the implementing `crux-in-a-box` PRs.** Agents
and humans use this environment to carry out those scenarios and inspect the
results. This repo's tests cover its own orchestration and fixtures.

**Start here:** the runbook below starts the local stack and launches a CRUX.
Use [AGENTS.md](AGENTS.md) for agent workflow and evidence requirements.

| Directory | Purpose |
| --- | --- |
| [ciab_devenv/](ciab_devenv/README.md) | Host CLI, instance configuration, input staging and machine orchestration |
| [services/](services/README.md) | Container/machine adapters, local protocol fixtures and execution reports |
| [images/](images/README.md) | Runner image and dependency/build boundaries |
| [tests/](tests/README.md) | Tests of this environment's behavior |

## Developer runbook: start a local CRUX

The result is a local OrbStack stack, a CRUX running against your chosen worktree,
and inspectable workspace/state/logs/traces. Scenario definitions and success
criteria come from the `crux-in-a-box` implementation PR.

1. **Prepare the inputs.** Start OrbStack and open a shell in `ciab-devenv`.
   Select the implementation PR's worktree and prepared SDK drop-in. Set the two
   paths below to your local paths. Follow that drop-in's `OPERATOR_GUIDE.md` to
   resolve placeholders and configure its declared tools/services. The upstream
   `src/sdk-scaffold/README.md` describes the drop-in layout. For Codex in this
   unprivileged container, select `sandbox = "full-access"` in the upstream
   drop-in: the container supplies the isolation, as in the SDK's Docker adapter.
   Set bounded run budgets in the drop-in and wire proprietary integrations to
   the [local fixtures](#local-services-and-fixtures) unless explicitly testing
   a live service.

   ```sh
   CRUX_WORKTREE=/absolute/path/to/crux-in-a-box-worktree
   CRUX_DROPIN=/absolute/path/to/that-prs-prepared-drop-in
   ```

2. **Set credentials.** Put your dedicated test key in the ignored `.envrc` as
   `export OPENAI_API_KEY=...`, then run `chmod 600 .envrc` and `direnv allow`.
   The commands below use `direnv exec .` so they also work without a shell hook.

3. **Stand up and check the local instance.** This builds the selected source's
   runner and starts Langfuse, storage and service fixtures. The probe makes one
   real SDK call and one real Codex turn using the configured model.

   ```sh
   direnv exec . ./devctl --name sdk bootstrap --source "$CRUX_WORKTREE"
   direnv exec . ./devctl --name sdk doctor
   direnv exec . ./devctl --name sdk probe
   direnv exec . ./devctl --name sdk check --drop-in "$CRUX_DROPIN" --run local-research
   ```

4. **Kick off the CRUX run.** This runs in the foreground; the terminal prints
   its output and report location when it exits. The default wall limit is 900
   seconds, including the time allowed for the command to finish.

   ```sh
   direnv exec . ./devctl --name sdk run --drop-in "$CRUX_DROPIN" --run local-research --timeout 900
   ```

5. **Observe and evaluate.** While it runs, use a second terminal for `status`,
   service `logs`, fixture controls and Langfuse at `http://localhost:23100`.
   Filter Langfuse by the run/session name `ciab-sdk-local-research`. The local
   login/password location is documented below. After the command exits:

   ```sh
   ./devctl --name sdk report
   ./devctl --name sdk exec ls -la /work/dropins/local-research/drop-in/workspace
   ./devctl --name sdk exec cat /work/dropins/local-research/state/state.json
   ```

   Apply the implementation PR's assertions to the actual artifacts and service
   behavior. `report latest` selects the most recent command; save its printed
   run ID to retrieve that specific report after other commands.

6. **Resume, start fresh, or stop.** Repeat the same `run` command to resume its
   persisted state; use another `--run` name for a fresh workspace. Ctrl-C stops
   a foreground command; inspect its report before resuming. `down` stops local
   containers and preserves data. Destructive cleanup is explicit:

   ```sh
   ./devctl --name sdk down
   # If this instance has an isolated provisioning machine:
   orb stop ciab-sdk-run
   ./devctl --name sdk reset --confirm sdk
   ```

For production provisioning/systemd behavior, use the separate
[isolated machine workflow](#isolated-provisioning-machine).

## Prerequisites and secrets

Use macOS with OrbStack running, Docker Compose v2, Python 3.11+, Git, OpenSSL,
and a `crux-in-a-box` worktree containing the implementation under test.

Manage secrets with direnv: export a dedicated, low-budget `OPENAI_API_KEY` from
`.envrc`, then run `direnv allow`. `.envrc`, `.envrc.*` and `.direnv/` are ignored,
excluded from builds, and never mounted in runners. `devctl` consumes inherited
environment variables. Outside a direnv-enabled shell, prefix commands with
`direnv exec .`.

Defaults are `CRUX_MODEL=gpt-5.4-mini` and `CRUX_REASONING_EFFORT=low`; override
these in `.envrc`. All inference uses the real provider. The selected model
supports tools, images and low effort; see the
[official model documentation](https://developers.openai.com/api/docs/models/gpt-5.4-mini).
The upstream SDK currently determines which providers are supported.

## Start and inspect

```sh
./devctl --name sdk bootstrap --source /path/to/crux-worktree
./devctl --name sdk doctor
./devctl --name sdk status
./devctl --name sdk probe
```

`bootstrap` builds the runner, starts services and checks connectivity. `probe`
invokes the selected scaffold's own minimal SDK/Codex probe. `./devctl --usage`
provides the full command reference. Docker operations explicitly select the
`orbstack` context without changing your global context.

Langfuse is at `http://localhost:23100`. Its login is `developer@ciab.test`; the
generated password is in `~/.local/state/ciab-devenv/sdk/instance.json`.
Use another `--name` and `--port` for an independent environment.

Source is a read-only snapshot of **tracked files, including local edits**.
Ignored/untracked files and `.git` are excluded. Add intended new source files
to Git's index before testing. Code is refreshed before execution; rebuild after
dependency changes with `build`.

To select another single PR stack, retaining services and prior evidence:

```sh
./devctl --name sdk select --source /path/to/another-crux-worktree
```

Selection refuses while a runner is active, rebuilds dependencies, and reloads
the cost service. It never combines PR revisions.

## Execute caller-owned work

Run any implementation command against `/source`, or stage an additional input
directory read-only at `/input`:

```sh
./devctl --name sdk exec python -m crux_scaffold --help
./devctl --name sdk exec --input /path/to/pr-test-inputs python /input/check.py
./devctl --name sdk check --drop-in /path/to/drop-in --run research
./devctl --name sdk run --drop-in /path/to/drop-in --run research
```

`exec` runs as an unprivileged user in a disposable container with writable
`/work`. Its command, output, exit code and source revision are recorded.
Additional Python tools can be installed into a caller-chosen `/work` or `/tmp`
directory. Test dependencies and test commands are owned by the implementation
PR, not by this environment.

`run` and `check` invoke the real scaffold CLI. They copy the supplied drop-in to
`/work/dropins/research/drop-in`, with state in the sibling `state` directory.
On subsequent calls configuration is refreshed while the existing workspace and
state are retained. Use a new run name for a fresh workspace. Keeping state
outside the drop-in also keeps generated Codex files out of drop-in validation.

Input staging excludes `.env*`, `.git`, `.direnv`, `.venv`, `.ssh`, `.aws`, Python
caches and symlinks. Stage only the directory needed by the command.

Execution defaults to a 15-minute wall limit; use `--timeout` on `exec`, `run` or
`check` to override it. Runners have memory/CPU/process limits and no host Docker
socket, SSH agent or home-directory mount. Scaffold budgets come from the
caller-supplied drop-in. Reported Langfuse spend can lag provider billing.

## Local services and fixtures

| Component | Provided behavior |
| --- | --- |
| SDK/Codex | Actual source and dependencies from the selected worktree |
| Langfuse | Web/worker, PostgreSQL, ClickHouse, Redis and S3 storage |
| Cost tracker | Actual selected checkout's Lambda behind a local HTTP adapter |
| Artifact storage | Local S3-compatible `storage:9000`, bucket `run-archives` |
| Steering fixture | Stateful HTTP service and the Slack MCP tool/CSV contract |
| Mailbox fixture | Authenticated inbox and a downloadable CLI |
| Parameter Store fixture | The GetParameter subset used by box configuration |
| Cloud resource fixtures | STS identity, Cost Explorer, EC2 listing and Runpod pod/billing HTTP subsets |
| Run box | Optional isolated Ubuntu machine invoking production provisioning |

Container images and the runner base are pinned by digest. SDK requirements come
from the selected source. OS packages/transitive Python dependencies can change
on a clean rebuild; the prototype is not a fully locked distribution.

Local HTTPS uses an instance certificate trusted in runners/machines; macOS trust
is untouched. Runner environment variables supply Langfuse, cost and fixture
endpoints/credentials. S3 uses access ID `ciab`, the generated
`CIAB_STORAGE_PASSWORD`, and an explicit caller-configured local AWS profile.
No host AWS profile is mounted. Runners provide the explicit `ciab-local` profile
for local STS/SSM/Cost Explorer/EC2 endpoints and `ciab-storage` for local S3.

The steering MCP server is `/devenv/services/slack_mcp.py`. Declare it in the
upstream drop-in with `CIAB_FIXTURE_URL`, `CIAB_FIXTURE_TOKEN` and `SSL_CERT_FILE`
passed through. The fixture supports channel/thread messages, retained duplicate
identities, injected HTTP errors and an inspectable state. It is not Slack itself.

The mailbox CLI is served at `https://fixtures.test/downloads/mailbox`; it reads
`auth.json` in `CIAB_MAILBOX_HOME`, containing a fixture URL and token. Upstream
provisioning manifests own its checksum, installation and authentication checks.
The SSM fixture accepts only local credentials (`CIABLOCAL`) and the fixed
`/crux/local/system/env` parameter; it does not implement IAM/signature validation.

```sh
./devctl --name sdk fixture show
./devctl --name sdk fixture message 'Operator message'
./devctl --name sdk fixture fail slack
./devctl --name sdk fixture recover slack
```

Authenticated fixture routes expose `/messages`, `/mail`, `/state`, `/reset` and
`/fault`. The `/fault` body selects `service` and HTTP `status` (zero recovers).
`POST /cloud` replaces caller-owned cloud fixture state: `account`,
`aws_billing` (tag to Cost Explorer groups), `instances` (objects with `id` and
`tag`), and `pods` (ID to `live` pod response and optional `billing` amounts).
An empty fixture means unknown billing/no configured resources. It never creates
real cloud resources. Failures for `aws` and `runpod` use the same `/fault` API.

The SDK currently hardcodes Runpod's hostname, so the instance's Docker DNS maps
`api.runpod.io` to its local TLS fixture. This mapping is limited to that network;
host DNS and trust are unchanged. Set `CIAB_USE_LIVE_RUNPOD=1` with an explicit
`RUNPOD_API_KEY`, then re-run `up`, to remove that local mapping for live reads.

Real Slack/Gmail OAuth, email delivery, AWS IAM and GPU provisioning require
separate upstream integration validation; the fixture does not establish them.

## Optional live services

Explicit overrides select individual services:

- `CIAB_LIVE_LANGFUSE_BASE_URL`, `CIAB_LIVE_LANGFUSE_PUBLIC_KEY`,
  `CIAB_LIVE_LANGFUSE_SECRET_KEY` select another Langfuse project.
- `CIAB_LIVE_COST_TRACKER_URL`, `CIAB_LIVE_COST_TRACKER_TOKEN` select another cost
  endpoint. The default local handler queries the selected Langfuse project.
- Slack/mailbox integration endpoints and credentials are declared by the
  upstream drop-in. Use dedicated test destinations and explicit authorization
  before sending to actual recipients.

There is no automatic production fallback. Local services remain available when
an individual client endpoint is overridden. Re-run `up` after changing service
configuration.

## Isolated provisioning machine

The selected source must contain the SDK box provisioning scripts. Supply the
implementation PR's drop-in, optional provisioning manifest and private per-run
service credential bundle:

```sh
./devctl --name sdk machine create
./devctl --name sdk machine provision --drop-in /path/to/drop-in --manifest /path/to/provision.json
./devctl --name sdk machine exec -- systemctl start crux-sdk-run
./devctl --name sdk machine exec -- systemctl status crux-sdk-run
```

`--secrets-json /private/path/run-secrets.json` optionally supplies the production
secret-delivery format, including `SERVICE_AUTH`; the inherited OpenAI key is
included automatically. Configuration uses the local SSM fixture and actual
`install-run.sh`/`configure-run.sh`. The production configure hook performs its
own probe and installs the systemd service without starting it. Existing run state
and workspace are retained when reprovisioning; recreate the machine for a clean
box. The caller owns launching the service and assessing its behavior.

Machines have no Mac filesystem mounts or forwarded SSH agent. They still share
OrbStack's Linux kernel. `machine exec` executes as root in this disposable box.

## Evidence and cleanup

```sh
./devctl --name sdk report
./devctl --name sdk report RUN_ID --output /tmp/ciab-report
./devctl --name sdk logs langfuse-worker
./devctl --name sdk down
```

Reports contain execution status, revision/local changes, command, model settings,
service endpoints, duration and artifact hashes. They record process outcomes,
not an acceptance verdict. Sanitized summaries/logs can be exported; raw sessions
and generated artifacts stay in the `/work` volume and can be inspected via
`exec`. Langfuse's UI exposes recorded observations. Machine commands use the
production systemd journal and `/var/log/crux-*` logs.

[AGENTS.md](AGENTS.md) requires all users to record assertions, outcomes, trace and
artifact locations, and coverage gaps in the implementing PR's evidence. Review
logs/artifacts for secrets before sharing; never commit raw sessions.

Private host state is `~/.local/state/ciab-devenv/<name>` (`CIAB_STATE_ROOT`
overrides its parent). `down` preserves data. `reset --confirm NAME` deletes only
that named local stack and its state. Remove its separate machine with
`machine delete --confirm NAME` after inspecting/exporting evidence.

After testing each CRUX PR, export the evidence you need, run `down`, and stop
its isolated machine with `orb stop ciab-NAME-run` if one was created. Do this
after failed or interrupted testing too. Check `docker --context orbstack ps`
and `orb list` to confirm that the instance has no running containers or machine.
Stopping preserves evidence; resetting volumes or deleting the machine discards
it. Leave services running only when the user explicitly requests it.

## Environment development

```sh
./devctl --name sdk exec python -m unittest discover -s /devenv/tests -v
./devctl --name sdk exec ruff check /devenv/ciab_devenv /devenv/services /devenv/tests --no-cache
```

Prototype tracked by [AE-269](https://linear.app/agent-evals/issue/AE-269).
The shared services and execution/reporting layers are separate from the SDK
launch adapter. Future AgentRQ-hosted Claude Code/Codex runners can add adapters
and Compose profiles while reusing these services. Their feature scenarios stay
in the implementing repository.
