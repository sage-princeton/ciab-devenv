"""Resolve production components from the selected checkout's layout contract."""
import json
from pathlib import Path

LEGACY = {
    "workspace": "src/ec2-workspaces",
    "controller": "src/ec2-control",
    "sdk": "src/sdk-scaffold",
    "codex_tracing": "src/ec2-workspaces",
    "claude_tracing": "agentrq/claude/.claude/hooks",
    "cost": "lambda/langfuse_cost_tracker",
}


def source_path(source, component, *parts):
    source = Path(source).resolve()
    manifest = source / "devops/layout.json"
    layout = LEGACY
    if manifest.exists():
        data = json.loads(manifest.read_text())
        if data.get("version") != 1:
            raise ValueError("Unsupported production layout version")
        layout = data["components"]
    relative = Path(layout[component])
    target = source / relative / Path(*parts)
    if relative.is_absolute() or not target.resolve().is_relative_to(source):
        raise ValueError("Production component path leaves the selected checkout")
    return target


def required_path(source, name):
    if name.startswith("src/ec2-workspaces/"):
        tail = name.removeprefix("src/ec2-workspaces/")
        component = "codex_tracing" if tail.startswith(("codex-", "live_trace/")) else "workspace"
        return source_path(source, component, tail)
    for component, prefix in LEGACY.items():
        if name.startswith(prefix + "/"):
            return source_path(source, component, name.removeprefix(prefix + "/"))
    return Path(source) / name
