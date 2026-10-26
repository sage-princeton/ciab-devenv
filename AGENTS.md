# Working with ciab-devenv

This repository supplies a local development environment for crux-in-a-box. Use
`./devctl --usage` to discover commands. Begin with `status` and `doctor`. Use OrbStack explicitly; never silently
switch to another Docker engine or a cloud run box.

The owner has authorized prototype changes and pushes directly on this repo's
`main`. Changes in crux-in-a-box still require a worktree and that repo's guidance.
Test one PR stack at a time. Select its worktree with `setup --source` or `select --source`; do not
combine unrelated PRs to make a test pass. Reprovision after changing source, dependencies, model settings or service overrides.

## Development loop

This repo owns infrastructure, reusable service fixtures, generic execution and
observation. It must not store crux-in-a-box feature scenarios, acceptance
criteria, scenario catalogs or feature-specific assertions. Describe those in
the implementing crux-in-a-box PR descriptions or comments. Create PR-specific
verification scripts, drop-ins and evidence files temporarily outside git
checkouts; never commit them to any repository. Small scripts can be included in
the PR description. Keep reusable, feature-independent helper methods in
`verification/`. Normal product unit/regression tests remain in crux-in-a-box;
tests here verify this environment's own orchestration and fixtures.

1. Select a named environment and source worktree. Check the current commit and
   local changes before interpreting results.
2. Use `exec`, `run` and `check` to execute the implementation PR's commands and
   caller-supplied drop-ins. Unit tests alone do not establish E2E.
3. Inspect state, output, traces and actual generated artifacts. A model claiming
   success is insufficient. Check gates, service records and the work product.
4. Fix the responsible component. Environment behavior belongs here; production
   scaffold behavior belongs in crux-in-a-box. Reuse production implementations.
5. Record evidence and remaining gaps before reporting completion.
6. After testing each PR, export relevant reports, sanitized logs and artifacts to
   durable storage outside the disposable environment, and cite that evidence in
   the PR description/comment or another durable record. Then delete the local
   test environment with `./devctl --name NAME reset --confirm NAME`: remove its
   OrbStack machine/disk, containers, volumes and private local state. Do not keep
   stopped machines or their data after the evidence has been preserved and cited.
   On failure or interruption, first stop with `down` (or `orb stop ciab-NAME-run`
   if needed), preserve/cite the failure evidence, then reset. Verify that the
   named machine and containers/volumes are absent. Delete only resources owned
   by that test environment; preserve explicitly requested manual environments.

## Required evidence for every validation report

All future users and coding agents must record:

- The tested repository, branch, commit, and relevant uncommitted changes.
- Commands/scenarios executed, their assertions, outcomes, and elapsed time.
- Model/provider/effort and which services were local, emulated, or live.
- Run identifier and locations of logs, traces, reports and generated artifacts.
- Failed, skipped, unavailable and untested checks, plus limitations of emulation.

Use `devctl report` to retrieve machine-generated evidence and add any practical
verification it cannot infer. Export and cite failure reports before deleting local environment data; do not relabel unavailable
features or skipped tests as passing. A completed devenv does not imply AE-258 or
its unfinished upstream stories are complete.

## Credentials and containment

The user manages secrets with direnv. `.envrc`, `.envrc.*` and `.direnv/` are
ignored. Never print them, commit them, or copy them into source/input snapshots.
Use inherited environment variables; never source credentials through a shell
constructed by Python. Check only whether required variables are present.

All actual inference uses provider endpoints and test credentials. Default to the
configured cheap model and low effort; obey explicit overrides. Use bounded runs.
Reported Langfuse cost can lag; it is not a hard provider billing cap.

Keep raw sessions and generated authentication state outside the checkout.
Sanitize logs and scan files before commits or exports. Source and caller-supplied
inputs are copied root-owned into the isolated Ubuntu machine; `ubuntu` cannot
edit them. `run` starts the production systemd unit. The run workspace is disposable.
Never expose the host Docker socket, SSH agent, home directory or cloud credentials
to the test agent. OrbStack isolated machines still share its Linux kernel.

Live services are explicit per-service overrides, never automatic fallbacks.
Local reset operations must only delete the named local environment. Sending to
actual Slack/email recipients needs explicit authorization; local fixtures do not.

## Verification

Run `python3 -m unittest discover -s tests -v`, `python3 -m compileall -q
ciab_devenv devops monitoring services verification tests`, and exercise the changed environment commands. Run Ruff
inside the provisioned machine. Exercise CLI behavior, startup and recovery after changes to
orchestration. Do not commit design conversation notes under `docs/superpowers/`.

## Component ownership

Use the production repository's Box, Run, Scaffold, Invoker, Agent and Harness
terminology. The Invoker CLI lives in `ciab_devenv/`, Box configuration adapters in
`devops/`, execution/report collection in `monitoring/`, protocol fixtures in
`services/`, and reusable verification helpers in `verification/`. Resolve
production source through its versioned layout contract; retain support for
older PR sources without that contract. Do not revive archived OpenClaw paths.
