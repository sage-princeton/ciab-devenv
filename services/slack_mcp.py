"""Emulate the pinned Slack MCP tool contract using the local fixture service."""
import csv
import io
import json
import os
import urllib.request

from mcp.server.mcpserver import MCPServer

server = MCPServer("ciab-local-slack")


def request(path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(os.environ["CIAB_FIXTURE_URL"] + path, data=data,
                                 headers={"Authorization": "Bearer " + os.environ["CIAB_FIXTURE_TOKEN"],
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.load(response)


def history(channel, thread=None):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["MsgID", "UserID", "Text", "ThreadTs", "Cursor"])
    for row in request("/messages"):
        if row["channel"] == channel and (thread is None or row["thread"] == thread or row["ts"] == thread):
            writer.writerow([row["ts"], row["user"], row["text"], row["thread"], ""])
    return output.getvalue()


@server.tool()
def conversations_history(channel_id: str, limit: str = "100", cursor: str = "") -> str:
    return history(channel_id)


@server.tool()
def conversations_replies(channel_id: str, thread_ts: str, limit: str = "100", cursor: str = "") -> str:
    return history(channel_id, thread_ts)


@server.tool()
def conversations_add_message(channel_id: str, payload: str, thread_ts: str = "", content_type: str = "text/markdown") -> str:
    return json.dumps(request("/messages", {"channel": channel_id, "text": payload, "thread": thread_ts, "user": "B_CIAB"}))


if __name__ == "__main__":
    server.run()
