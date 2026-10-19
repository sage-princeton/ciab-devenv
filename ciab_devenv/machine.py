from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile

from .config import ROOT, DevError, private_write, stage_directory


def machine(instance, args):
    from .cli import execute
    name = instance.project + "-run"
    command = ["orb", "run", "--machine", name, "--user", "root", "--workdir", "/tmp"]
    if args.action == "create":
        return execute(["orb", "create", "--isolated", "--user", "ubuntu", "--memory", "4G", "--cpus", "2",
                        "ubuntu:24.04", name])
    if args.action == "status":
        return execute(["orb", "info", name])
    if args.action == "delete":
        if args.confirm != instance.name:
            raise DevError("Deleting the isolated machine requires --confirm " + instance.name)
        return execute(["orb", "delete", "--force", name])
    if args.action == "exec":
        if not args.argv:
            raise DevError("Provide a command after machine exec --")
        return execute([*command, *args.argv])
    if not args.drop_in:
        raise DevError("machine provision requires a caller-supplied --drop-in directory.")
    if not os.environ.get("OPENAI_API_KEY"):
        raise DevError("The production provisioning probe needs OPENAI_API_KEY from direnv.")
    instance.stage_source()
    staging = instance.root / "machine-input"
    shutil.rmtree(staging, ignore_errors=True)
    stage_directory(args.drop_in, staging / "drop-in")
    if args.manifest:
        shutil.copyfile(args.manifest, staging / "provision.json")
    archive = instance.root / "machine-source.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        output.add(instance.root / "source", arcname="source")
        output.add(staging, arcname="input")
        output.add(ROOT / "services/machine_setup.py", arcname="machine_setup.py")
        output.add(instance.root / "certs/server.crt", arcname="local.crt")
    values = json.loads(args.secrets_json.read_text()) if args.secrets_json else {}
    values.setdefault("OPENAI_API_KEY", os.environ["OPENAI_API_KEY"])
    secret = instance.root / "machine-secrets.json"
    private_write(secret, json.dumps(values))
    environment = instance.compose_env()
    edge = subprocess.check_output(["docker", "--context", "orbstack", "inspect", instance.project + "-edge-1",
                                    "--format", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}"], text=True).strip()
    settings = {"edge_ip": edge, "model": environment["CRUX_MODEL"], "effort": environment["CRUX_REASONING_EFFORT"],
                "run_slug": instance.project, "has_manifest": bool(args.manifest)}
    private_write(instance.root / "machine-settings.json", json.dumps(settings))
    try:
        for file in (archive, secret, instance.root / "machine-settings.json"):
            result = execute(["orb", "push", "--machine", name, str(file)])
            if result:
                return result
            result = execute([*command, "mv", "/home/ubuntu/" + file.name, "/tmp/" + file.name])
            if result:
                return result
        result = execute([*command, "tar", "-xzf", "/tmp/machine-source.tar.gz", "-C", "/opt"])
        if result:
            return result
        return execute([*command, "python3", "/opt/machine_setup.py"])
    finally:
        secret.unlink(missing_ok=True)
