# CRUX local development environment

Run a selected `crux-in-a-box` worktree on an **isolated OrbStack Ubuntu 24.04
machine**, installed by CRUX's production provisioning scripts. Langfuse, storage
and service fixtures run in local containers. All inference uses the real model
provider with a dedicated test key.

**Start here:** follow the runbook below to provision a box and launch CRUX.
`run` starts the selected production systemd service; ACP mode submits and observes an AgentRQ task. There is no container
execution path. `down` stops both the machine and its service containers while
preserving evidence and data.

This repository owns infrastructure, reusable fixtures, execution and observation.
Feature scenarios, acceptance criteria, rerun instructions and validation evidence
belong in implementing **CRUX PR descriptions/comments**. Create PR-specific
scripts and drop-ins temporarily outside git checkouts; do not commit them anywhere.
Reusable helpers live in `verification/`. See [AGENTS.md](AGENTS.md) for agent guidance.

| Directory | Purpose |
| --- | --- |
| [ciab_devenv/](ciab_devenv/README.md) | Host CLI, private configuration, staging and machine lifecycle |
| [services/](services/README.md) | Production provisioning adapter, execution reports and local protocol fixtures |
| [verification/](verification/README.md) | Reusable SDK execution, state/trace inspection and upstream check helpers |
| [tests/](tests/README.md) | Tests of the environment's orchestration and fixtures |

## Developer runbook: start a local CRUX

Prerequisites: macOS, OrbStack running, Docker Compose v2, Python 3.11+, Git,
OpenSSL and direnv. Use a CRUX worktree containing the selected production scaffold module
(`src/ec2-workspaces/scaffolds/sdk.sh` or `acp.sh`).

1. **Prepare a single PR worktree and drop-in.** Follow its `OPERATOR_GUIDE.md`
   and the upstream SDK README. Resolve placeholders, set bounded budgets, and
   configure integrations for local fixtures. Codex can use the production
   `sandbox = "workspace-write"`; provisioning checks sandboxed shell execution
   and file writes. Inputs and feature-specific checks stay outside git.

   ```sh
   CRUX_WORKTREE=/absolute/path/to/crux-worktree
   CRUX_DROPIN=/absolute/path/to/prepared-drop-in
   cd /absolute/path/to/ciab-devenv
   ```

2. **Set credentials.** Put `export OPENAI_API_KEY=...` in the ignored `.envrc`,
   run `chmod 600 .envrc`, then `direnv allow`. Use a dedicated test key.
   Defaults are `CRUX_MODEL=gpt-5.4-mini` and `CRUX_REASONING_EFFORT=low`;
   explicit environment overrides apply on provisioning. Never paste keys in
   commands, reports or PRs.

3. **Start and provision.** This starts the service stack, creates an isolated
   Ubuntu machine, copies the selected tracked source, and invokes production
   `install-run.sh` and `configure-run.sh`. Configuration performs real SDK and
   Codex inference probes and installs the systemd unit without starting CRUX.
   Allow several minutes for a fresh installation.

   ```sh
   direnv exec . ./devctl --name sdk bootstrap --source "$CRUX_WORKTREE" --drop-in "$CRUX_DROPIN"
   ./devctl --name sdk doctor
   ./devctl --name sdk check
   ```

   Optional `--manifest /path/provision.json` and
   `--secrets-json /private/path/run-secrets.json` supply production provisioning
   inputs supported by the selected CRUX revision. The inherited OpenAI key is
   included automatically. A failed probe fails provisioning; inspect the report
   and private `/var/log/crux-agent-probe*.log` on the machine.

4. **Start CRUX.** The command starts and observes `crux-sdk-run` in the
   foreground. It collects the journal, exit status and workspace file hashes.
   The default wall limit is 900 seconds. Timeout or Ctrl-C stops the service.

   ```sh
   ./devctl --name sdk run --timeout 900
   ```

5. **Observe and evaluate.** In another terminal use `status`, `logs`, or the
   fixture controls below. Langfuse is at `http://localhost:23100`, with session
   name `ciab-sdk`. Login is `developer@ciab.test`; the generated password is in
   the instance's private `instance.json` (do not print it in agent logs).

   ```sh
   ./devctl --name sdk report
   ./devctl --name sdk exec cat /srv/crux-run/run-harness/workspace/DONE.txt
   ./devctl --name sdk exec cat /srv/crux-run/state/state.json
   ./devctl --name sdk report REPORT_ID --output /tmp/ciab-report
   ```

   Apply the PR's assertions to actual artifacts, traces and service behavior.
   `report latest` selects the latest command, including fixture controls; retain
   a specific report ID when collecting evidence.

6. **Stop after testing.** Always shut down the instance after each PR, including
   failed testing. Reports remain available from the host while OrbStack is off.

   ```sh
   ./devctl --name sdk down
   ./devctl --name sdk machine status
   ./devctl --name sdk report REPORT_ID
   ```

   `down` verifies that the named machine and containers are stopped. It preserves
   the machine disk, volumes and reports. Use `up` to resume the environment;
   CRUX starts only when you call `run`. Repeat `run` to resume its persisted
   scaffold state. Use a new instance name and port for an independent run.

## AgentRQ / ACP runs

Select `--scaffold acp --platform codex` or `--platform claude` at setup/bootstrap.
ACP uses the selected worktree's production controller image and CLI/gateway pins.
The controller runs locally in Compose; the vendor agent and ACP gateway run on
isolated Ubuntu. The controller dashboard is `https://localhost:<port + 1>` using
the instance CA. Its generated root login token is in private `instance.json`.
Controller administrator credentials stay on the host.

```sh
direnv exec . ./devctl --name acp bootstrap --source "$CRUX_WORKTREE" --scaffold acp --platform codex --port 23200
./devctl --name acp doctor
./devctl --name acp run --prompt-file /private/path/task.txt --timeout 300
./devctl --name acp task show TASK_ID
./devctl --name acp task reply TASK_ID --message-file /private/path/reply.txt
./devctl --name acp run --task-id TASK_ID --timeout 300
./devctl --name acp task cancel TASK_ID
./devctl --name acp down
```

Use `CRUX_MODEL` / `CRUX_REASONING_EFFORT` and the platform's test credential:
`OPENAI_API_KEY` for Codex, `ANTHROPIC_API_KEY` for Claude. Claude requires an
explicit model. `--provider openrouter` selects `OPENROUTER_API_KEY`; the model
must then be an explicit provider model ID. No provider fallback occurs.
`--drop-in` is optional in ACP mode; it stages caller files at
`/srv/crux-run/run-harness`, with a writable `workspace/` directory. Tasks run
from `/srv/crux-run`. Supply prompts as files outside the checkout.

`probe` submits a bounded task through the real controller/gateway. `run` watches
task state, not service exit: completed succeeds, blocked/rejected exits 3,
timeout exits 124, interruption exits 130. The gateway is stopped after observation
ends, including failure; timeout/interruption also reject the task. Unfinished
tasks must be requeued with `--task-id` or cancelled before starting another.
Requeueing starts a new agent session against the existing task and workspace;
prior conversation context depends on what the vendor agent retrieves from AgentRQ. Task controls remain
available from another terminal during a run. Reports include controller task IDs,
status transitions, installed versions, and a machine journal/artifact snapshot.
`report REPORT_ID --output /tmp/report` exports the task report, sanitized logs,
and `machine.json` together. Task show/reply/cancel commands also create reports;
retain the run's specific report ID because `latest` includes these controls.
Provider credentials used for redaction are kept in the instance's private
host state so later commands still scrub them when invoked outside direnv.

ACP artifacts are indexed under `/srv/crux-run`; credential/configuration
folders such as `.codex`, `.claude`, `.mcp.json`, `.aws` and `.env*` are excluded.
The final report records controller task state separately from command success.
Inspect the actual output and assertions in addition to a successful task.

The controller remains local and persists across `down`/`up`. The gateway and
trace exporter stay disabled until a run starts. Cancellation first requests an
AgentRQ stop, then stops the local gateway even if the notification is unavailable.
It refuses to stop a different active task. Task replies persist in AgentRQ; after
a stopped run, requeue with `--task-id` and have the agent inspect the task's
messages. Model budget limits remain caller-owned; the wall limit bounds the run,
with additional time needed to stop services and collect evidence.

Claude Code provisioning/settings are supported, but live Claude validation was
deferred by the owner. OpenRouter routing is also not covered by the local live
validation. These paths require their own dedicated test credentials.

## Source changes and generic commands

Source is copied into root-owned `/source` from **tracked files, including local
edits**; `.git`, ignored/untracked files and `.env*` are excluded. Add intended new
source files to the Git index before testing. SDK code is installed at `/opt/crux-sdk-scaffold`; ACP vendor tools use the
production installer's locations. The agent runs as `ubuntu`. No source checkout, host
home directory, Docker socket, or SSH agent is shared with the machine.

Reprovision after changing source, dependencies, drop-in configuration, model
settings or service overrides. This retains the run workspace and state; it does
not reset a completed run. Use a fresh named instance for fresh acceptance runs.
Execution refuses if the selected source no longer matches the provisioning receipt.

```sh
direnv exec . ./devctl --name sdk provision --drop-in "$CRUX_DROPIN"
./devctl --name sdk select --source /path/to/another-pr-worktree
direnv exec . ./devctl --name sdk provision --drop-in /path/to/that-pr-drop-in
```

`select` records one worktree and invalidates the old provisioning receipt. It
never combines PR revisions. There is no `build` command or runner image.

`exec` executes arbitrary commands as `ubuntu` on the same provisioned machine,
with its installed SDK environment, local service credentials and writable `/work`.
`--input` copies a temporary directory read-only to `/input`. Staging excludes
`.env*`, `.git`, `.direnv`, `.venv`, `.ssh`, `.aws`, Python caches and symlinks.
A later staged input replaces `/input`.

```sh
./devctl --name sdk exec python -m crux_scaffold --help
./devctl --name sdk exec --input /tmp/pr-verification python /input/check.py
./devctl --name sdk exec python -m verification.offline
./devctl --name sdk probe --timeout 180
```

`check` validates the SDK drop-in or checks that the ACP unit is installed.
`probe` runs the SDK/Codex probe or submits a bounded ACP task through AgentRQ. Both use the provisioned environment. Test tools pytest, Ruff and ShellCheck
are installed for generic verification. `machine exec -- COMMAND` is an explicit
root diagnostic escape hatch, with no timeout or evidence wrapper. Prefer `exec`
for tests and `run` for end-to-end CRUX execution.

Mutating/execution commands are serialized per instance. Fixture controls, status,
logs and reports remain available during a run. Interrupt a foreground command
before invoking `down`. A machine started by a root diagnostic command is also
stopped by `down`.

## Local services and fixtures

| Component | Provided behavior |
| --- | --- |
| Run box | Isolated Ubuntu 24.04, selected production installer/configuration/systemd service |
| AgentRQ / ACP | Pinned local controller, production gateway, Codex or Claude Code; real provider inference |
| SDK/Codex | Selected source, actual provider inference, production sandbox |
| Langfuse | Web/worker, PostgreSQL, ClickHouse, Redis and S3 storage |
| Cost tracker | Selected checkout's actual Lambda behind an HTTP adapter; unavailable when absent |
| Artifact storage | Local S3-compatible `storage:9000`, bucket `run-archives` |
| Steering fixture | Stateful HTTP service and Slack MCP tool/CSV contract |
| Mailbox fixture | Authenticated inbox and downloadable CLI |
| Parameter Store fixture | GetParameter subset used by production configuration |
| Cloud fixtures | STS identity, Cost Explorer, EC2 listing and Runpod pod/billing subsets |

Container images are pinned by digest. Production provisioning determines SDK,
OS and tool installation; this is not a fully locked distribution. Machines have
2 CPUs and 4 GiB RAM and still share OrbStack's Linux kernel. This does not prove
EC2, IAM or real GPU behavior.

Instance TLS trust and hostname mappings apply only inside the machine and
service network. macOS trust/DNS are unchanged. `up` refreshes container addresses
on the machine after restart. AWS uses explicit local `ciab-local` and
`ciab-storage` profiles, never host profiles. S3 access ID is `ciab` and its secret
is the generated `CIAB_STORAGE_PASSWORD` in the machine's environment.

Slack/email steering is unchanged. Declare `/devenv/services/slack_mcp.py` in the
upstream drop-in, using `/opt/crux-sdk-scaffold/.venv/bin/python` and passing
`CIAB_FIXTURE_URL`, `CIAB_FIXTURE_TOKEN` and `SSL_CERT_FILE`. The fixture supports
channel/thread messages, retained duplicate identities and injected HTTP errors.
It is a limited protocol fixture, not Slack itself.

```sh
./devctl --name sdk fixture show
./devctl --name sdk fixture message 'Operator message'
./devctl --name sdk fixture fail slack
./devctl --name sdk fixture recover slack
```

The mailbox CLI is served at `https://fixtures.test/downloads/mailbox`. It reads
`auth.json` in `CIAB_MAILBOX_HOME` with the fixture URL and token. Caller manifests
own its installation/checksum/authentication when supported by the CRUX revision.
No interactive email MCP has been added.

Authenticated fixture routes are `/messages`, `/mail`, `/state`, `/reset`, `/fault`
and `/cloud`. `/fault` accepts `service` and HTTP `status` (zero recovers).
`POST /cloud` replaces caller-owned `account`, `aws_billing`, `instances` and
`pods` records. Fixtures never create cloud resources or forward vendor messages.
The SSM fixture accepts local `CIABLOCAL` credentials and
`/crux/local/system/env`; it does not implement IAM/signature validation.

## Optional live services

Defaults are local except inference. Explicit per-service overrides apply during
provisioning; there is no automatic production fallback:

- `CIAB_LIVE_LANGFUSE_BASE_URL`, `CIAB_LIVE_LANGFUSE_PUBLIC_KEY`,
  `CIAB_LIVE_LANGFUSE_SECRET_KEY` select another Langfuse project.
- `CIAB_LIVE_COST_TRACKER_URL` and `CIAB_LIVE_COST_TRACKER_TOKEN` select another cost endpoint.
- `CIAB_USE_LIVE_RUNPOD=1` plus `RUNPOD_API_KEY` removes the machine's local
  `api.runpod.io` mapping and selects the real provider.
- Slack/mailbox endpoints and credentials are owned by the drop-in. Actual
  recipients require explicit authorization and dedicated test destinations.

Reprovision after changing these settings. Local services remain available when
one endpoint is overridden. Reported model spend may lag; use provider-side test
budgets and bounded runs.

## Evidence, cleanup and migration

Private host state is `~/.local/state/ciab-devenv/<name>`; `CIAB_STATE_ROOT`
overrides the parent. Reports and sanitized logs are cached in `reports/<id>`.
They record commits/local changes, commands, source/model settings, service
selection, outcomes, timing and artifact hashes. A zero exit code is command
success, not feature acceptance. Inspect actual artifacts and add assertions,
trace locations and remaining coverage gaps to the implementing CRUX PR.

The machine retains `/srv/crux-run/run-harness/workspace`, `/srv/crux-run/state`,
`/work/runs/<id>`, `/var/lib/ciab/reports/<id>` and the systemd journal. `report`
exports cached metadata/logs without starting the machine. Raw sessions, credentials
and generated artifacts are not automatically exported. Review evidence before sharing.

```sh
./devctl --name sdk logs langfuse-worker
./devctl --name sdk down
# Destructive: delete this machine, service volumes and private host state.
./devctl --name sdk reset --confirm sdk
```

Instances created before the dedicated local CA was introduced must be
reprovisioned before `up`; this updates machine trust without changing macOS trust.

For old container-based instances, use a fresh name/port or intentionally reset
before provisioning. The removed runner's legacy Docker work volume is not
migrated or automatically deleted; preserve/export any old evidence before
manually discarding that volume. Legacy machine subcommands `create`, `provision`
and `delete` are replaced by `bootstrap`/`provision` and confirmed `reset`.

## Environment development

Run the commands in [tests/README.md](tests/README.md), then practically exercise
changed startup/execution/recovery/cleanup paths. Keep feature-specific scripts
outside git. SDK and ACP adapters share local services, machine lifecycle and reporting.
Both invoke the selected worktree's production provisioning.

Prototype tracked by [AE-269](https://linear.app/agent-evals/issue/AE-269).
