from __future__ import annotations

import json
import hashlib
import os
import re
import secrets
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT.parent / "crux-in-a-box"
DEFAULT_MODEL = "gpt-5.4-mini"
NAME = re.compile(r"^[a-z][a-z0-9-]{0,35}$")


class DevError(Exception):
    pass


def private_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(text)


def source_info(source: Path) -> dict:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(source), *args], text=True).strip()
    diff = subprocess.check_output(["git", "-C", str(source), "diff", "HEAD", "--binary"])
    return {"path": str(source), "commit": git("rev-parse", "HEAD"), "diff_sha256": hashlib.sha256(diff).hexdigest(),
            "branch": git("branch", "--show-current"), "changes": git("status", "--porcelain")}


def stage_directory(source: Path, destination: Path) -> None:
    source = source.expanduser().resolve()
    if not source.is_dir():
        raise DevError(f"Input directory does not exist: {source}")
    if destination.resolve().is_relative_to(source):
        raise DevError("Input directory contains the private staging destination; choose a narrower input directory.")
    def excluded(directory, names):
        return [name for name in names if name in (".git", ".direnv", ".venv", "__pycache__", ".ssh", ".aws")
                or name.startswith(".env") or (Path(directory) / name).is_symlink()]
    shutil.copytree(source, destination, ignore=excluded)


class Environment:
    def __init__(self, name: str):
        if not NAME.fullmatch(name):
            raise DevError("Instance name must start with a lowercase letter and contain at most 36 letters, digits or hyphens.")
        self.name = name
        self.project = "ciab-" + name
        self.root = Path(os.environ.get("CIAB_STATE_ROOT", Path.home() / ".local/state/ciab-devenv")) / name
        self.path = self.root / "instance.json"
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {}

    @property
    def source(self) -> Path:
        if not self.data:
            raise DevError(f"Instance {self.name} is not configured. Run devctl --name {self.name} setup --source PATH.")
        return Path(self.data["source"])

    def setup(self, source: Path, port: int) -> None:
        source = source.expanduser().resolve()
        if not (source / "src/sdk-scaffold/requirements.txt").is_file():
            raise DevError(f"{source} has no SDK scaffold. Select a crux-in-a-box worktree with --source.")
        source_info(source)
        if self.data and (self.data["source"] != str(source) or self.data["port"] != port):
            raise DevError("This instance already targets a source/port. Use another --name or reset this instance first.")
        if not self.data:
            self.data = {"source": str(source), "port": port,
                         "langfuse_public_key": "pk-lf-" + secrets.token_hex(16),
                         "langfuse_secret_key": "sk-lf-" + secrets.token_hex(16),
                         "password": secrets.token_urlsafe(24), "salt": secrets.token_hex(32),
                         "encryption_key": secrets.token_hex(32),
                         "fixture_token": secrets.token_urlsafe(24), "cost_token": secrets.token_urlsafe(24)}
        private_write(self.path, json.dumps(self.data, indent=2) + "\n")
        self.certificates()
        self.stage_source()
        self.compose_env()

    def stage_source(self) -> None:
        target = self.root / "source"
        target.mkdir(parents=True, exist_ok=True)
        names = subprocess.check_output(["git", "-C", str(self.source), "ls-files", "-z"]).decode().split("\0")
        expected = set()
        for name in filter(None, names):
            path = self.source / name
            if not path.is_file():
                continue
            if not path.resolve().is_relative_to(self.source):
                raise DevError(f"Tracked source symlink leaves the checkout: {name}")
            if Path(name).name.startswith(".env"):
                continue
            expected.add(name)
            destination = target / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
        for path in target.rglob("*"):
            if path.is_file() and str(path.relative_to(target)) not in expected:
                path.unlink()
        for path in sorted(target.rglob("*"), reverse=True):
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()

    def certificates(self) -> None:
        certs = self.root / "certs"
        if (certs / "server.crt").exists() and "api.runpod.io" in (certs / "openssl.cnf").read_text():
            return
        certs.mkdir(parents=True, exist_ok=True, mode=0o700)
        config = """[req]
distinguished_name=dn
x509_extensions=extensions
prompt=no
[dn]
CN=ciab-devenv local services
[extensions]
basicConstraints=critical,CA:TRUE
keyUsage=critical,digitalSignature,keyEncipherment,keyCertSign
subjectAltName=DNS:langfuse.test,DNS:cost.test,DNS:fixtures.test,DNS:api.runpod.io,DNS:localhost,IP:127.0.0.1
"""
        private_write(certs / "openssl.cnf", config)
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "365",
                        "-keyout", str(certs / "server.key"), "-out", str(certs / "server.crt"),
                        "-config", str(certs / "openssl.cnf")], check=True, capture_output=True)
        (certs / "server.key").chmod(0o600)

    def compose_env(self) -> dict[str, str]:
        d = self.data
        result = {"CIAB_SOURCE": str(self.root / "source"), "CIAB_ROOT": str(ROOT), "CIAB_INSTANCE": str(self.root), "CIAB_PROJECT": self.project,
                  "CIAB_PORT": str(d["port"]), "CIAB_PASSWORD": d["password"],
                  "CIAB_SALT": d["salt"], "CIAB_ENCRYPTION_KEY": d["encryption_key"],
                  "CIAB_FIXTURE_TOKEN": d["fixture_token"], "COST_TRACKER_TOKEN": d["cost_token"],
                  "LANGFUSE_PUBLIC_KEY": d["langfuse_public_key"], "LANGFUSE_SECRET_KEY": d["langfuse_secret_key"],
                  "CIAB_LOCAL_LANGFUSE_PUBLIC_KEY": d["langfuse_public_key"], "CIAB_LOCAL_LANGFUSE_SECRET_KEY": d["langfuse_secret_key"],
                  "LANGFUSE_BASE_URL": "https://langfuse.test", "COST_TRACKER_URL": "https://cost.test/cost",
                  "CRUX_MODEL": os.environ.get("CRUX_MODEL", DEFAULT_MODEL),
                  "CRUX_REASONING_EFFORT": os.environ.get("CRUX_REASONING_EFFORT", "low")}
        live_runpod = os.environ.get("CIAB_USE_LIVE_RUNPOD") == "1"
        if live_runpod and not os.environ.get("RUNPOD_API_KEY"):
            raise DevError("CIAB_USE_LIVE_RUNPOD=1 requires an explicit RUNPOD_API_KEY.")
        result["CIAB_RUNPOD_HOST"] = "runpod-fixture.test" if live_runpod else "api.runpod.io"
        result["RUNPOD_API_KEY"] = os.environ["RUNPOD_API_KEY"] if live_runpod else d["fixture_token"]
        for key in ("LANGFUSE_BASE_URL", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "COST_TRACKER_URL", "COST_TRACKER_TOKEN"):
            if os.environ.get("CIAB_LIVE_" + key):
                result[key] = os.environ["CIAB_LIVE_" + key]
        return result

    def process_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update(self.compose_env())
        return env
