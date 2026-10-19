"""Run the selected PR's existing contracts without model or external network calls."""

import os
import subprocess
from pathlib import Path

root = Path("/source")
sdk = root / "src/sdk-scaffold"
environment = {
    k: v
    for k, v in os.environ.items()
    if k
    not in (
        "OPENAI_API_KEY",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_BASE_URL",
    )
}
commands = [
    (sdk, ["ruff", "check", ".", "--no-cache"]),
    (sdk, ["python", "-m", "pytest", "-q", "-o", "cache_dir=/tmp/pytest-cache"]),
    (
        sdk,
        [
            "python",
            "-m",
            "unittest",
            "discover",
            "-s",
            "examples/web-cms-product-change/workspace/site",
        ],
    ),
    (sdk, ["shellcheck", *map(str, (sdk / "docker").glob("*.sh"))]),
]
for directory in ("tests/workspace-provisioning", "lambda/langfuse_cost_tracker/tests"):
    if any((root / directory).glob("test*.py")):
        commands.append(
            (root, ["python", "-m", "unittest", "discover", "-s", directory, "-v"])
        )
failed = []
for cwd, command in commands:
    print("Running:", " ".join(command), flush=True)
    result = subprocess.run(command, cwd=cwd, env=environment)
    if result.returncode:
        failed.append(command)
raise SystemExit(bool(failed))
