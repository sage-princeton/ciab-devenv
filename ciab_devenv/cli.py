from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .config import DEFAULT_SOURCE, ROOT, DevError, Environment, source_info


def execute(argv: list[str], *, env: dict | None = None, timeout: int | None = None) -> int:
    try:
        return subprocess.run(argv, env=env, timeout=timeout, check=False).returncode
    except FileNotFoundError:
        raise DevError(f"{argv[0]} is not installed. See devctl --usage for prerequisites.") from None


def compose(instance: Environment, *args: str, timeout: int | None = None) -> int:
    return execute(["docker", "--context", "orbstack", "compose", "--project-name", instance.project,
                    "--file", str(ROOT / "compose.yaml"), *args], env=instance.process_env(), timeout=timeout)


def runtime_ready() -> None:
    if not shutil.which("orb"):
        raise DevError("OrbStack is missing. Install it, open the app once, then run devctl doctor.")
    result = subprocess.run(["docker", "--context", "orbstack", "info", "--format", "{{.OSType}}"],
                            capture_output=True, text=True)
    if result.returncode or result.stdout.strip() != "linux":
        raise DevError("OrbStack's Docker engine is unavailable. Finish OrbStack setup and start it; other Docker contexts are not used.")


def require_idle(instance: Environment) -> None:
    active = subprocess.check_output(["docker", "--context", "orbstack", "ps", "--quiet",
                                      "--filter", "label=com.docker.compose.project=" + instance.project,
                                      "--filter", "label=com.docker.compose.service=runner"], text=True).strip()
    if active:
        raise DevError("A runner is active in this instance. Wait for it to finish; status, logs and fixture controls remain available.")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run and test CRUX locally on OrbStack.", epilog=(
        "Credentials: use direnv with an ignored .envrc exporting OPENAI_API_KEY. "
        "Models default to gpt-5.4-mini / low; override CRUX_MODEL and CRUX_REASONING_EFFORT. "
        "All model calls use the real provider. Source stays read-only. "
        "State and credentials live in ~/.local/state/ciab-devenv/<name>."))
    p.add_argument("--name", default="dev", help="isolated instance name (default: dev)")
    p.add_argument("--usage", action="store_true", help="show the full command reference")
    sub = p.add_subparsers(dest="command")
    for command in ("setup", "bootstrap"):
        s = sub.add_parser(command, help="configure an instance" if command == "setup" else "configure, build, start and check")
        s.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="crux-in-a-box worktree to test")
        s.add_argument("--port", type=int, default=23100, help="localhost Langfuse port; use a distinct port per instance")
    s = sub.add_parser("select", help="select another single PR stack, retaining local services and prior evidence")
    s.add_argument("--source", type=Path, required=True)
    for command, help_text in (("up", "start local services"), ("build", "build the runner for the selected source"),
                               ("status", "show instance and service state"), ("doctor", "check runtime and local services"),
                               ("down", "stop services, preserving all data"), ("probe", "one real SDK call plus a Codex turn")):
        sub.add_parser(command, help=help_text)
    for command in ("logs", "restart"):
        s = sub.add_parser(command, help=f"{command} a local service")
        s.add_argument("service", nargs="?")
    for command in ("run", "check"):
        s = sub.add_parser(command, help=f"{command} a caller-supplied SDK drop-in")
        s.add_argument("--drop-in", type=Path, required=True)
        s.add_argument("--run", required=True, help="persistent local run name")
        s.add_argument("--timeout", type=int, default=900)
    s = sub.add_parser("exec", help="execute a command in an unprivileged runner")
    s.add_argument("--input", type=Path, help="stage a caller-supplied directory read-only at /input")
    s.add_argument("--timeout", type=int, default=900)
    s.add_argument("argv", nargs=argparse.REMAINDER)
    s = sub.add_parser("fixture", help="inspect or change the local service fixtures")
    s.add_argument("action", choices=("show", "reset", "message", "fail", "recover"))
    s.add_argument("value", nargs="?", default="")
    s = sub.add_parser("report", help="print or export evidence from a test run")
    s.add_argument("run_id", nargs="?", default="latest")
    s.add_argument("--output", type=Path)
    s = sub.add_parser("reset", help="delete ONLY this local instance's containers, volumes and configuration")
    s.add_argument("--confirm", required=True, help="must equal the instance name")
    s = sub.add_parser("machine", help="provisioning tests in an isolated OrbStack Ubuntu machine")
    s.add_argument("action", choices=("create", "status", "provision", "exec", "delete"))
    s.add_argument("--drop-in", type=Path, help="caller-supplied SDK drop-in for provisioning")
    s.add_argument("--manifest", type=Path, help="caller-supplied production provision.json")
    s.add_argument("--secrets-json", type=Path, help="optional private per-run secret bundle outside source")
    s.add_argument("--confirm", help="instance name, required for machine deletion")
    s.add_argument("argv", nargs="*", help="command for machine exec (use -- before command flags)")
    return p


def runner(instance: Environment, args: list[str], timeout: int = 900, input_path: Path | None = None) -> int:
    if args[0] not in ("report", "fixture"):
        require_idle(instance)
        instance.stage_source()
    run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + os.urandom(3).hex()
    name = f"{instance.project}-test-{run_id.lower()}"
    mounts = []
    inputs = None
    if input_path:
        from .config import stage_directory
        staged = instance.root / "inputs" / run_id
        stage_directory(input_path, staged)
        mounts = ["--volume", str(staged) + ":/input:ro"]
        inputs = {"path": str(input_path.resolve()), "files": [
            {"path": str(file.relative_to(staged)), "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}
            for file in sorted(staged.rglob("*")) if file.is_file()]}
    command = ["run", "--rm", "--no-deps", "--name", name, *mounts,
               "-e", "CIAB_RUN_ID=" + run_id, "-e", "CIAB_SOURCE_INFO=" + json.dumps(source_info(instance.source)),
               "-e", "CIAB_DEVENV_INFO=" + json.dumps(source_info(ROOT)), "-e", "CIAB_INPUT_INFO=" + json.dumps(inputs),
               "-e", "CIAB_TIMEOUT=" + str(timeout), "runner", *args]
    try:
        return compose(instance, *command, timeout=timeout + 30)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        execute(["docker", "--context", "orbstack", "stop", "--time", "10", name])
        print(f"Run {run_id} interrupted; inspect its report before retrying.", file=sys.stderr)
        return 124


def main(argv: list[str] | None = None) -> int:
    p = parser()
    args = p.parse_args(argv)
    if args.usage or not args.command:
        p.print_help()
        if args.usage:
            for action in p._actions:
                if isinstance(action, argparse._SubParsersAction):
                    for command in action.choices.values():
                        print()
                        command.print_help()
        return 0
    operation_lock = None
    try:
        instance = Environment(args.name)
        changes_environment = args.command in {"setup", "bootstrap", "select", "up", "build", "down", "reset", "exec", "run", "check", "probe", "doctor"}
        changes_environment |= args.command == "machine" and args.action in {"create", "provision", "delete"}
        if changes_environment:
            instance.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            operation_lock = os.fdopen(os.open(instance.root / "operation.lock", os.O_CREAT | os.O_RDWR, 0o600), "w")
            try:
                fcntl.flock(operation_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise DevError("Another environment command is running for this instance. Status, logs, reports and fixture controls remain available.") from None
        if args.command in ("setup", "bootstrap"):
            if not 1024 <= args.port <= 65535:
                raise DevError("Choose a localhost port between 1024 and 65535.")
            instance.setup(args.source, args.port)
            print(f"Configured {instance.name}: {instance.source}; private state: {instance.root}")
            if args.command == "setup":
                return 0
        instance.source
        if args.command == "machine":
            from .machine import machine
            return machine(instance, args)
        runtime_ready()
        if args.command == "select":
            require_idle(instance)
            source = args.source.expanduser().resolve()
            if not (source / "src/sdk-scaffold/requirements.txt").is_file():
                raise DevError("Selected source does not contain the SDK scaffold.")
            source_info(source)
            previous = instance.data["source"]
            instance.data["source"] = str(source)
            from .config import private_write
            private_write(instance.path, json.dumps(instance.data, indent=2) + "\n")
            instance.stage_source()
            result = compose(instance, "build", "runner")
            if result:
                instance.data["source"] = previous
                private_write(instance.path, json.dumps(instance.data, indent=2) + "\n")
                instance.stage_source()
                return result
            return compose(instance, "up", "-d", "--no-deps", "--force-recreate", "cost")
        if args.command == "bootstrap":
            for command in (("build", "runner"), ("up", "-d", "--wait", "--wait-timeout", "300")):
                result = compose(instance, *command)
                if result:
                    return result
            return runner(instance, ["services"])
        if args.command in ("up", "build", "down"):
            require_idle(instance)
            if args.command != "down":
                instance.certificates()
                instance.stage_source()
            commands = {"up": ("up", "-d", "--wait", "--wait-timeout", "300"),
                        "build": ("build", "runner"), "down": ("down",)}
            return compose(instance, *commands[args.command])
        if args.command == "status":
            print(json.dumps({"instance": instance.name, "source": source_info(instance.source),
                              "langfuse": f"http://localhost:{instance.data['port']}",
                              "private_state": str(instance.root)}, indent=2))
            return compose(instance, "ps")
        if args.command == "doctor":
            print("OrbStack Docker: ready")
            print("Test API key: " + ("set" if os.environ.get("OPENAI_API_KEY") else "missing; export via direnv .envrc for live scenarios"))
            return runner(instance, ["services"])
        if args.command in ("logs", "restart"):
            command = [args.command]
            if args.command == "logs":
                command += ["--tail", "100"]
            if args.service:
                command.append(args.service)
            if args.command == "logs":
                result = subprocess.run(["docker", "--context", "orbstack", "compose", "--project-name", instance.project,
                                         "--file", str(ROOT / "compose.yaml"), *command], env=instance.process_env(),
                                        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                output = result.stdout
                for key, value in instance.process_env().items():
                    if len(value) > 6 and any(part in key for part in ("KEY", "TOKEN", "PASSWORD", "SECRET")):
                        output = output.replace(value, "[REDACTED]")
                print(output)
                return result.returncode
            return compose(instance, *command)
        if args.command in ("run", "check", "probe"):
            if args.command != "check" and not os.environ.get("OPENAI_API_KEY"):
                raise DevError("Inference requires OPENAI_API_KEY. Set it in the ignored .envrc and run direnv allow.")
            if args.command == "probe":
                return runner(instance, ["probe"])
            Environment(args.run)
            return runner(instance, [args.command, args.run], args.timeout, args.drop_in)
        if args.command == "exec":
            if not args.argv:
                raise DevError("Provide a command after exec.")
            return runner(instance, ["exec", *args.argv], args.timeout, args.input)
        if args.command == "fixture":
            return runner(instance, ["fixture", args.action, args.value])
        if args.command == "report":
            if args.output:
                container = instance.project + "-export"
                result = compose(instance, "run", "--name", container, "--no-deps", "runner", "report", args.run_id)
                if result:
                    return result
                args.output.mkdir(parents=True, exist_ok=True)
                result = execute(["docker", "--context", "orbstack", "cp", container + ":/work/export/.", str(args.output)])
                execute(["docker", "--context", "orbstack", "rm", container])
                return result
            return runner(instance, ["report", args.run_id])
        if args.command == "reset":
            require_idle(instance)
            if args.confirm != instance.name:
                raise DevError("--confirm must match the instance name. Reset deletes its local runs and service data.")
            result = compose(instance, "down", "--volumes", "--remove-orphans")
            if not result:
                shutil.rmtree(instance.root)
            return result
        raise DevError("Unsupported command")
    except (DevError, OSError, subprocess.CalledProcessError) as exc:
        print(f"devctl: {exc}", file=sys.stderr)
        return 2
    finally:
        if operation_lock is not None:
            operation_lock.close()
