# Runtime adapters and local services

These files make the selected CRUX implementation runnable and observable on
local infrastructure. They provide generic execution, production-script adapters
and reusable protocol fixtures. The implementing CRUX PR description supplies
scenarios and acceptance assertions; test-specific drop-ins and scripts are
created temporarily outside git. Reusable verification helpers live in
[verification/](../verification/README.md).

**Key points:** Langfuse and S3 are real local services; Slack, mailbox and cloud
APIs are limited fixtures. Inference always reaches the model provider. Fixtures
never forward requests to vendors. Use the [root runbook](../README.md) to start
the stack and configure clients.

| File | Responsibility |
| --- | --- |
| `machine_job.py` | Bounded execution as ubuntu, production systemd run monitoring, timeout/interruption cleanup and sanitized reports |
| `check_services.py` | Infrastructure connectivity/authentication diagnostics and fixture-control commands |
| `Caddyfile` | Local HTTPS routing for Langfuse, cost and protocol fixtures |
| `cost.py` | HTTP/API Gateway adapter loading the selected checkout's actual cost Lambda |
| `fixtures.py` | Stateful SQLite-backed messages, mailbox, cloud fixture configuration and injected errors |
| `slack_mcp.py` | MCP tools translating the pinned Slack CSV/tool contract to the local message service |
| `mailbox_cli.py` | Downloadable CLI reading caller-provisioned mailbox authentication |
| `machine_setup.py` | Local CA/SSM setup and invocation of production install/configure hooks with caller-supplied inputs |

Compose mounts fixture code read-only. Restart a service container after changing
its Python code. Provisioning copies machine adapters and reusable helpers to
root-owned `/devenv`; reprovision after changing them. The cost
adapter requires its Lambda to exist in the selected stack; absence is reported
as unavailable. It does not substitute synthetic costs.

`fixtures.py` accepts authenticated `/messages`, `/mail`, `/state`, `/reset`,
`/fault` and `/cloud` operations. The root README documents their configuration.
SQLite data is in the instance's `fixtures` volume. Cloud records are supplied by
the caller; fixtures do not model IAM, actual compute, vendor OAuth or delivery.
Runpod's hardcoded hostname resolves locally only inside the instance network,
unless the explicit live override is selected.

Machine evidence lives in `/var/lib/ciab/reports/<id>` and is cached on the host
under the instance's `reports/<id>`. Generic command artifacts live in `/work/runs/<id>`.
The production workspace is `/srv/crux-run/run-harness/workspace`, with state in
`/srv/crux-run/state`. `machine_setup.py` invokes upstream install/configure hooks;
its systemd override adds local service settings without replacing production
ExecStart, user, restart policy or sandbox settings. A zero exit code records command
success, not feature acceptance. Reports export sanitized logs and metadata;
the caller inspects artifacts and records assertions in the implementing PR.

Verify adapters with [tests/](../tests/README.md), `doctor`, actual client calls
and the upstream PR's commands. Keep scenario-specific logic out of these files.
