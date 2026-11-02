"""Resolve production components from the selected checkout's directory structure."""
from pathlib import Path

LEGACY = {
    "workspace": "src/ec2-workspaces",
    "controller": "src/ec2-control",
    "sdk": "src/sdk-scaffold",
    "codex_tracing": "src/ec2-workspaces",
    "claude_tracing": "agentrq/claude/.claude/hooks",
    "cost": "lambda/langfuse_cost_tracker",
}


CURRENT = {
    "workspace": "devops/ec2-workspaces",
    "controller": "devops/ec2-control",
    "sdk": "scaffolds/sdk",
    "codex_tracing": "monitoring/tracing/codex",
    "claude_tracing": "monitoring/tracing/claude",
    "cost": "monitoring/costs/langfuse",
}


def source_path(source, component, *parts):
    """Resolve a production component inside the selected checkout.

    :param source: Trusted CRUX source directory.
    :param component: Canonical component key.
    :param parts: Optional child path components.
    :returns: Source-contained path using the current or older layout.
    """
    source = Path(source).resolve()
    layout = CURRENT if (source/'devops/ec2-workspaces').is_dir() else LEGACY
    relative = Path(layout[component])
    target = source / relative / Path(*parts)
    if relative.is_absolute() or not target.resolve().is_relative_to(source):
        raise ValueError("Production component path leaves the selected checkout")
    return target


def required_path(source, name):
    """Translate an older required-file path to the selected source layout.

    :param source: Selected CRUX checkout.
    :param name: Required repository-relative file path.
    :returns: Corresponding path inside the checkout.
    """
    if name.startswith("src/ec2-workspaces/"):
        tail = name.removeprefix("src/ec2-workspaces/")
        component = "codex_tracing" if tail.startswith(("codex-", "live_trace/")) else "workspace"
        return source_path(source, component, tail)
    for component, prefix in LEGACY.items():
        if name.startswith(prefix + "/"):
            return source_path(source, component, name.removeprefix(prefix + "/"))
    return Path(source) / name
