"""Locate production source in current and pre-reorganization checkouts."""
from pathlib import Path


def source_path(root, relative):
    root = Path(root)
    for old, new in (
        ('src/sdk-scaffold', 'scaffolds/sdk'),
        ('src/ec2-workspaces', 'devops/ec2-workspaces'),
    ):
        if relative == old or relative.startswith(old + '/'):
            current = root / (new + relative[len(old):])
            return current if current.exists() or not (root / relative).exists() else root / relative
    return root / relative
