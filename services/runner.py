from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path


def trust_local_services():
    certificate = Path("/certs/server.crt")
    if certificate.exists():
        bundle = Path("/tmp/ciab-ca.pem")
        bundle.write_bytes(Path("/etc/ssl/certs/ca-certificates.crt").read_bytes() + b"\n" + certificate.read_bytes())
        os.environ["SSL_CERT_FILE"] = str(bundle)
        os.environ["REQUESTS_CA_BUNDLE"] = str(bundle)


def local_aws():
    config = Path("/tmp/ciab-aws-config")
    credentials = Path("/tmp/ciab-aws-credentials")
    config.write_text("[profile ciab-local]\nregion=us-east-1\n[profile ciab-storage]\nregion=us-east-1\ns3 =\n    addressing_style = path\n")
    credentials.write_text("[ciab-local]\naws_access_key_id=CIABLOCAL\naws_secret_access_key=local-fixture-only\n"
                           "[ciab-storage]\naws_access_key_id=ciab\naws_secret_access_key=" +
                           os.environ["CIAB_STORAGE_PASSWORD"] + "\n")
    os.environ.update(AWS_CONFIG_FILE=str(config), AWS_SHARED_CREDENTIALS_FILE=str(credentials),
                      AWS_PROFILE="ciab-local", AWS_EC2_METADATA_DISABLED="true", AWS_DEFAULT_REGION="us-east-1",
                      AWS_ENDPOINT_URL="https://fixtures.test", AWS_ENDPOINT_URL_STS="https://fixtures.test",
                      AWS_ENDPOINT_URL_COST_EXPLORER="https://fixtures.test",
                      AWS_ENDPOINT_URL_EC2="https://fixtures.test", AWS_ENDPOINT_URL_SSM="https://fixtures.test",
                      AWS_ENDPOINT_URL_S3="http://storage:9000", AWS_CA_BUNDLE=os.environ["SSL_CERT_FILE"])


def scrub(text):
    for name, value in os.environ.items():
        if len(value) > 6 and any(part in name for part in ("KEY", "TOKEN", "PASSWORD", "SECRET")):
            text = text.replace(value, "[REDACTED]")
    return re.sub(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{16,}", "[REDACTED]", text)


def report(run_id):
    reports = Path("/work/reports")
    if run_id == "latest":
        paths = sorted(reports.glob("*/report.json"))
        if not paths:
            raise RuntimeError("No test reports yet")
        path = paths[-1]
    else:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
            raise RuntimeError("Invalid report ID")
        path = reports / run_id / "report.json"
    print(path.read_text())
    export = Path("/work/export")
    if export.exists():
        shutil.rmtree(export)
    shutil.copytree(path.parent, export)
    return 0


def main():
    os.umask(0o077)
    trust_local_services()
    local_aws()
    args = sys.argv[1:]
    suite = args[0] if args else "services"
    if suite == "report":
        return report(args[1])
    run_id = os.environ.get("CIAB_RUN_ID", str(int(time.time())))
    output = Path("/work/reports") / run_id
    output.mkdir(parents=True)
    run_dir = Path("/work/runs") / run_id
    run_dir.mkdir(parents=True)
    os.environ["CIAB_RUN_DIR"] = str(run_dir)
    os.environ["RUN_SLUG"] = "dev-" + run_id.lower()
    timeout = int(os.environ.get("CIAB_TIMEOUT", "900"))
    data = {"run_id": run_id, "suite": suite, "source": json.loads(os.environ.get("CIAB_SOURCE_INFO", "{}")),
            "devenv": json.loads(os.environ.get("CIAB_DEVENV_INFO", "{}")),
            "inputs": json.loads(os.environ.get("CIAB_INPUT_INFO", "null")),
            "model": os.environ.get("CRUX_MODEL"), "effort": os.environ.get("CRUX_REASONING_EFFORT"),
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "status": "running",
            "coverage": "Caller owns test scenarios, assertions and acceptance interpretation.",
            "artifacts": str(run_dir), "run_slug": os.environ["RUN_SLUG"],
            "services": {"langfuse": os.environ.get("LANGFUSE_BASE_URL"), "cost": os.environ.get("COST_TRACKER_URL"),
                         "fixtures": os.environ.get("CIAB_FIXTURE_URL"), "aws": "local protocol fixture",
                         "runpod": "local protocol fixture" if os.environ.get("RUNPOD_API_KEY") == os.environ.get("CIAB_FIXTURE_TOKEN") else "live provider"},
            "gaps": ["Local Slack/mailbox fixtures do not establish vendor OAuth, delivery or rate-limit behavior.",
                     "Cloud emulation does not establish AWS IAM, EC2 or real GPU behavior."]}
    path = output / "report.json"
    path.write_text(json.dumps(data, indent=2))
    cwd = "/work"
    if suite in ("services", "fixture"):
        command = ["python", "/devenv/services/check_services.py", *args]
        data["coverage"] = "real local services; no inference"
    elif suite == "exec":
        command = args[1:]
    elif suite == "probe":
        command = ["python", "-m", "crux_scaffold", "probe", "--coding-agent", "codex"]
    elif suite in ("run", "check"):
        name = args[1]
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,35}", name):
            raise ValueError("Invalid persistent run name")
        run_dir = Path("/work/dropins") / name
        dropin = run_dir / "drop-in"
        existed = (dropin / "workspace").exists()
        if dropin.exists():
            for child in dropin.iterdir():
                if child.name != "workspace":
                    shutil.rmtree(child) if child.is_dir() else child.unlink()
        shutil.copytree("/input", dropin, dirs_exist_ok=True,
                        ignore=lambda path, names: ["workspace"] if path == "/input" and existed else [])
        os.environ["RUN_SLUG"] = os.environ.get("CIAB_PROJECT", "ciab") + "-" + name
        data.update(artifacts=str(run_dir), run_slug=os.environ["RUN_SLUG"])
        command = ["python", "-m", "crux_scaffold", suite, "--drop-in", str(dropin),
                   "--state-dir", str(run_dir / "state")]
    else:
        raise ValueError("Unsupported runner operation: " + suite)
    data["command"] = command
    started = time.monotonic()
    with (output / "output.raw").open("w") as log:
        process = subprocess.Popen(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        def stop(_signum, _frame):
            os.killpg(process.pid, signal.SIGTERM)
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            code = 124
    clean = scrub((output / "output.raw").read_text(errors="replace"))
    (output / "output.log").write_text(clean)
    (output / "output.raw").unlink()
    for evidence in output.glob("*.xml"):
        evidence.write_text(scrub(evidence.read_text()))
    print(clean)
    data.update(status="succeeded" if code == 0 else "failed", exit_code=code,
                elapsed_seconds=round(time.monotonic() - started, 2))
    data["files"] = [{"path": str(p.relative_to(run_dir)), "bytes": p.stat().st_size,
                      "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                     for p in run_dir.rglob("*") if p.is_file() and not p.is_symlink()]
    path.write_text(scrub(json.dumps(data, indent=2)) + "\n")
    print(f"Evidence: {path}; status={data['status']}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
