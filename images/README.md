# Runner image

`runner.Dockerfile` builds the disposable Ubuntu runner used for SDK execution
and caller-supplied commands. Local infrastructure services use images declared
in the root `compose.yaml` instead.

**Key points:** the selected worktree supplies SDK requirements; the image has no
credentials or feature scenarios. Source is mounted read-only at runtime. The
runner is unprivileged and has no host Docker socket or home-directory mount.

The image includes Python, Node/npm, Git, shell tooling, jq, AWS CLI, pytest and
Ruff. The Ubuntu base is pinned by digest and AWS CLI by version. SDK requirements
come from the explicit `scaffold` build context, staged by `devctl`. OS packages
and transitive Python dependencies are resolved during builds, so the prototype
is not a fully locked distribution.

From the repository root, rebuild after changing this Dockerfile or the selected
worktree's requirements:

```sh
./devctl --name sdk build
./devctl --name sdk doctor
```

The root `.dockerignore` excludes direnv files, local state, Git metadata and
caches. Runtime entry is `/devenv/services/runner.py`; its behavior is described
in [services/](../services/README.md). Additional test dependencies belong to the
implementing PR and can be installed into a caller-chosen writable directory.

Future runner types can add separate Dockerfiles/Compose profiles and reuse the
same local services and evidence interface. Do not embed their acceptance suites
or provider credentials in an image.
