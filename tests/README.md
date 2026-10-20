# Environment tests

These tests verify `ciab-devenv` itself: private configuration, source/input
staging and local protocol fixture behavior. They do not define or establish
acceptance of CRUX scaffold features.

**Key points:** no inference keys are needed. The tests use temporary Git
repositories and a local HTTP server. Feature scenarios and assertions remain in
their implementing `crux-in-a-box` PR descriptions/comments. Their temporary
scripts execute through the environment and are never committed to any repo.
Reusable methods belong in [verification/](../verification/README.md).

| File | Coverage |
| --- | --- |
| `test_environment.py` | Tracked local edits, credential exclusions, named-instance isolation, private permissions, input staging and explicit endpoint overrides |
| `test_machine.py` | Provisioning capability/source drift, stopped-machine handling, evidence retrieval and credential redaction |
| `test_fixtures.py` | HTTP authentication, injected failures/recovery, retained message identities and caller-configured cloud responses |

Run from the repository root in a configured instance:

```sh
./devctl --name sdk exec python -m unittest discover -s /devenv/tests -v
./devctl --name sdk exec ruff check /devenv/ciab_devenv /devenv/services /devenv/verification /devenv/tests --no-cache
```

Host checks are `python3 -m unittest discover -s tests -v`,
`python3 -m compileall -q ciab_devenv services verification tests`, and `shellcheck devctl`.
The HTTP tests need permission to bind a local socket; use the provisioned machine when the
host sandbox disallows it.

For orchestration changes, also exercise the changed commands against OrbStack:
startup, health, execution, reporting, restart or instance-scoped cleanup as
applicable. Keep assertions here focused on environment behavior. Follow
[AGENTS.md](../AGENTS.md) when recording and sharing evidence.
