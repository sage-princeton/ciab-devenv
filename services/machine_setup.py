"""Invoke production provisioning hooks with caller-owned configuration."""
import json
import os
import shutil
import subprocess
from pathlib import Path


def run(argv, **kwargs):
    subprocess.run(argv, check=True, **kwargs)


settings = json.loads(Path("/tmp/machine-settings.json").read_text())
hosts = [line for line in Path("/etc/hosts").read_text().splitlines() if "langfuse.test" not in line]
Path("/etc/hosts").write_text("\n".join(hosts) + "\n" + settings["edge_ip"] + " langfuse.test cost.test fixtures.test\n")
run(["apt-get", "update", "-qq"])
run(["apt-get", "install", "-y", "-qq", "ca-certificates", "curl", "python3", "jq", "unzip"])
shutil.copy2("/opt/local.crt", "/usr/local/share/ca-certificates/ciab-local.crt")
run(["update-ca-certificates"])
trust = Path("/etc/systemd/system.conf.d/ciab-local-trust.conf")
trust.parent.mkdir(parents=True, exist_ok=True)
trust.write_text("[Manager]\nDefaultEnvironment=SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt\n")
run(["systemctl", "daemon-reexec"])
source = Path("/opt/source/src/ec2-workspaces")
Path("/usr/local/lib/crux").mkdir(parents=True, exist_ok=True)
for name in ("run_provision.py", "run_service_auth.py"):
    if (source / name).is_file():
        shutil.copy2(source / name, Path("/usr/local/lib/crux") / name)
shutil.copy2(source / "scaffolds/sdk.sh", source / "scaffold.sh")
shutil.copytree("/opt/source/src/sdk-scaffold", "/opt/crux-sdk-scaffold", dirs_exist_ok=True)
if settings["has_manifest"]:
    shutil.copy2("/opt/input/provision.json", "/etc/crux-provision.json")
    Path("/etc/crux-provision.json").chmod(0o644)
else:
    Path("/etc/crux-provision.json").unlink(missing_ok=True)
environment = dict(os.environ, AGENT_PLATFORM="openai-agents", DEBIAN_FRONTEND="noninteractive")
run(["bash", str(source / "install-run.sh")], env=environment)
drop = Path("/srv/crux-run/run-harness")
existed = (drop / "workspace").exists()
if drop.exists():
    for child in drop.iterdir():
        if child.name != "workspace":
            shutil.rmtree(child) if child.is_dir() else child.unlink()
shutil.copytree("/opt/input/drop-in", drop, dirs_exist_ok=True,
                ignore=lambda path, names: ["workspace"] if path == "/opt/input/drop-in" and existed else [])
run(["chown", "-R", "ubuntu:ubuntu", "/srv/crux-run"])
aws = Path("/root/.aws")
aws.mkdir(mode=0o700, exist_ok=True)
(aws / "config").write_text("[profile ciab-local]\nregion=us-east-1\n")
(aws / "credentials").write_text("[ciab-local]\naws_access_key_id=CIABLOCAL\naws_secret_access_key=ciab-local-only\n")
(aws / "credentials").chmod(0o600)
environment.update(AWS_PROFILE="ciab-local", AWS_REGION="us-east-1", AWS_EC2_METADATA_DISABLED="true",
                   AWS_ENDPOINT_URL="https://fixtures.test", AWS_ENDPOINT_URL_SSM="https://fixtures.test",
                   AWS_CA_BUNDLE="/etc/ssl/certs/ca-certificates.crt",
                   RUN_SECRETS_PATH="/tmp/machine-secrets.json", SYSTEM_SSM_PARAM="/crux/local/system/env",
                   RUN_SLUG=settings["run_slug"], OPENAI_AGENTS_MODEL=settings["model"],
                   OPENAI_AGENTS_REASONING_EFFORT=settings["effort"])
run(["bash", str(source / "configure-run.sh")], env=environment)
print("Production installation/configuration completed. The caller owns starting and assessing the run.")
