"""Shared helpers for explicitly invoked, paid SDK verification in ciab-devenv."""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import subprocess
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from devops.source import source_path



def http(url, body=None, authorization=None):
    headers = {"Content-Type": "application/json"}
    if authorization:
        headers["Authorization"] = authorization
    req = urllib.request.Request(
        url, data=None if body is None else json.dumps(body).encode(), headers=headers
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def fixture(path, body=None):
    return http(
        os.environ["CIAB_FIXTURE_URL"] + path,
        body,
        "Bearer " + os.environ["CIAB_FIXTURE_TOKEN"],
    )


def langfuse(path):
    key = os.environ["LANGFUSE_PUBLIC_KEY"] + ":" + os.environ["LANGFUSE_SECRET_KEY"]
    return http(
        os.environ["LANGFUSE_BASE_URL"] + path,
        authorization="Basic " + base64.b64encode(key.encode()).decode(),
    )


def require(path, text, issue):
    if text not in source_path("/source", "sdk", "crux_scaffold", path).read_text():
        raise AssertionError(
            f"UNAVAILABLE: this PR stack does not implement {issue}; select the implementing PR stack identified by the implementation PR"
        )


def case(
    name,
    prompt,
    *,
    agents="",
    extra="",
    runtime="",
    tools="",
    phases=None,
    gates=None,
    budget="",
    context="",
):
    root = Path(os.environ["CIAB_RUN_DIR"]) / name
    workspace = root / "workspace"
    workspace.mkdir(parents=True)
    (root / "persona.md").write_text(
        "You are conducting a bounded local scaffold verification run. Follow the task precisely. "
        "Use tools to produce and verify artifacts. Keep responses short. "
        "Work only inside the workspace. Do not change test or scaffold code."
    )
    (root / "PROMPT.md").write_text(prompt)
    (root / "continue.md").write_text(
        "Complete the requested work. Fix these failed checks:\n$feedback"
    )
    phases = (
        phases
        or """[[loop.phases]]
name = "work"
prompt = "PROMPT.md"
continue_prompt = "continue.md"
gates = ["done"]
max_iterations = 2
"""
    )
    gates = (
        gates
        or """[gates.done]
type = "command"
command = "test -s DONE.txt"
"""
    )
    (root / "scaffold.toml").write_text(f'''orchestrator = "pi"
{extra}
[runtime]
type = "openai-agents"
max_turns = 25
{runtime}
[context]
{context or 'type = "persistent"'}
[budget]
max_total_tokens = 120000
{budget}
[loop]
type = "phased"
{phases}
{gates}
[agents.pi]
persona = "persona.md"
tools = ["read_file", "write_file", "list_files", "budget_status"{tools}]
{agents}
''')
    return root


def invoke(root, command="run", expected=0):
    args = [
        "python",
        "-m",
        "crux_scaffold",
        command,
        "--drop-in",
        str(root),
        "--state-dir",
        str(state_dir(root)),
    ]
    env = dict(os.environ, RUN_SLUG=os.environ["RUN_SLUG"] + "-" + root.name)
    result = subprocess.run(
        args,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=500,
    )
    index = len(list(root.glob(command + "-*.log")))
    (root / f"{command}-{index}.log").write_text(result.stdout)
    assert result.returncode == expected, (
        f"Scaffold {command} exited {result.returncode}:\n{result.stdout[-12000:]}"
    )
    return result


def state(root):
    return json.loads((state_dir(root) / "state.json").read_text())


def state_dir(root):
    return root.parent / (root.name + "-state")


def conversation(root):
    result = []
    with sqlite3.connect(state_dir(root) / "sessions.sqlite") as db:
        for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            if not table.replace("_", "").isalnum():
                continue
            for row in db.execute('SELECT * FROM "' + table + '"'):
                for value in row:
                    if isinstance(value, str):
                        try:
                            result.append(json.loads(value))
                        except ValueError:
                            pass
    return result


def traced(root):
    slug = os.environ["RUN_SLUG"] + "-" + root.name
    for _ in range(30):
        now = datetime.now(timezone.utc)
        query = urllib.parse.urlencode(
            {
                "filter": json.dumps(
                    [
                        {
                            "type": "string",
                            "column": "sessionId",
                            "operator": "=",
                            "value": slug,
                        }
                    ]
                ),
                "fromStartTime": (now - timedelta(days=1)).isoformat(),
                "toStartTime": now.isoformat(),
                "fields": "core,basic,usage",
                "limit": 100,
            }
        )
        data = langfuse("/api/public/v2/observations?" + query)
        if data.get("data"):
            (root / "traces.json").write_text(json.dumps(data, indent=2))
            return data["data"]
        time.sleep(2)
    raise AssertionError("Run completed but no trace arrived in Langfuse within 60 seconds")
