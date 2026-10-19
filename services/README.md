# Runtime adapters and local services

These files make the selected CRUX implementation runnable and observable on
local infrastructure. They provide generic execution, production-script adapters
and reusable protocol fixtures. The implementing CRUX PR supplies scenarios,
drop-ins and acceptance assertions.

**Key points:** Langfuse and S3 are real local services; Slack, mailbox and cloud
APIs are limited fixtures. Inference always reaches the model provider. Fixtures
never forward requests to vendors. Use the [root runbook](../README.md) to start
the stack and configure clients.

| File | Responsibility |
| --- | --- |
| `runner.py` | Unprivileged execution, local CA/AWS setup, persistent drop-in staging, process timeout, redacted logs and report metadata |
| `check_services.py` | Infrastructure connectivity/authentication diagnostics and fixture-control commands |
| `Caddyfile` | Local HTTPS routing for Langfuse, cost and protocol fixtures |
| `cost.py` | HTTP/API Gateway adapter loading the selected checkout's actual cost Lambda |
| `fixtures.py` | Stateful SQLite-backed messages, mailbox, cloud fixture configuration and injected errors |
| `slack_mcp.py` | MCP tools translating the pinned Slack CSV/tool contract to the local message service |
| `mailbox_cli.py` | Downloadable CLI reading caller-provisioned mailbox authentication |
| `machine_setup.py` | Local CA/SSM setup and invocation of production install/configure hooks with caller-supplied inputs |

Compose mounts these files read-only. Restart a long-running service after
changing its Python code; new runners load code on each execution. The cost
adapter requires its Lambda to exist in the selected stack; absence is reported
as unavailable. It does not substitute synthetic costs.

`fixtures.py` accepts authenticated `/messages`, `/mail`, `/state`, `/reset`,
`/fault` and `/cloud` operations. The root README documents their configuration.
SQLite data is in the instance's `fixtures` volume. Cloud records are supplied by
the caller; fixtures do not model IAM, actual compute, vendor OAuth or delivery.
Runpod's hardcoded hostname resolves locally only inside the instance network,
unless the explicit live override is selected.

Execution evidence lives in `/work/reports/<id>`; command workspaces live in
`/work/runs/<id>` or `/work/dropins/<name>`. A zero exit code records command
success, not feature acceptance. Reports export sanitized logs and metadata;
the caller inspects artifacts and records assertions in the implementing PR.

Verify adapters with [tests/](../tests/README.md), `doctor`, actual client calls
and the upstream PR's commands. Keep scenario-specific logic out of these files.
