"""Stateful, authenticated local steering and mailbox fixtures; never contacts vendors."""
import hmac
import json
import os
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from xml.sax.saxutils import escape

DATABASE = Path(os.environ.get("CIAB_FIXTURE_DB", "/data/fixtures.sqlite"))


def database():
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    connection.executescript("""
      CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, ts TEXT, channel TEXT, user TEXT, text TEXT, thread TEXT);
      CREATE TABLE IF NOT EXISTS faults (service TEXT PRIMARY KEY, status INTEGER);
      CREATE TABLE IF NOT EXISTS mail (id INTEGER PRIMARY KEY, subject TEXT, body TEXT);
      CREATE TABLE IF NOT EXISTS configuration (name TEXT PRIMARY KEY, value TEXT);
    """)
    return connection


class Server(BaseHTTPRequestHandler):
    def authorized(self):
        expected = "Bearer " + os.environ["CIAB_FIXTURE_TOKEN"]
        return hmac.compare_digest(self.headers.get("Authorization", ""), expected)

    def do_GET(self):
        if self.path == "/health":
            return self.respond(200, {"ok": True})
        if self.path == "/downloads/mailbox":
            data = Path(__file__).with_name("mailbox_cli.py").read_bytes()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if not self.authorized():
            return self.respond(401, {"error": "invalid fixture credentials"})
        with database() as db:
            service = "runpod" if self.path.startswith("/v2/") else ("mailbox" if self.path.startswith("/mail") else "slack")
            fault = db.execute("SELECT status FROM faults WHERE service=?", (service,)).fetchone()
            if fault and self.path != "/state":
                return self.respond(fault[0], {"error": "injected " + service + " failure"})
            if self.path == "/state":
                return self.respond(200, {"messages": [dict(r) for r in db.execute("SELECT * FROM messages")],
                                          "faults": [dict(r) for r in db.execute("SELECT * FROM faults")]})
            if self.path == "/cloud":
                return self.respond(200, self.cloud(db))
            if self.path.startswith("/v2/"):
                return self.runpod(db)
            if self.path == "/messages":
                return self.respond(200, [dict(r) for r in db.execute("SELECT * FROM messages ORDER BY id")])
            if self.path == "/mail":
                return self.respond(200, [dict(r) for r in db.execute("SELECT * FROM mail ORDER BY id")])
        self.respond(404, {"error": "unknown fixture path"})

    def do_POST(self):
        if self.headers.get("X-Amz-Target") == "AmazonSSM.GetParameter":
            if "Credential=CIABLOCAL/" not in self.headers.get("Authorization", ""):
                return self.respond(403, {"__type": "AccessDeniedException"})
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            if body.get("Name") != "/crux/local/system/env":
                return self.respond(400, {"__type": "ParameterNotFound"})
            values = {key: os.environ[key] for key in ("LANGFUSE_BASE_URL", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")}
            return self.respond(200, {"Parameter": {"Name": body["Name"], "Type": "SecureString", "Value": json.dumps(values)}})
        if "Credential=CIABLOCAL/" in self.headers.get("Authorization", ""):
            return self.aws()
        if not self.authorized():
            return self.respond(401, {"error": "invalid fixture credentials"})
        size = int(self.headers.get("Content-Length", 0))
        if size > 65536:
            return self.respond(413, {"error": "request too large"})
        try:
            body = json.loads(self.rfile.read(size) or b"{}")
            with database() as db:
                if self.path == "/reset":
                    for table in ("messages", "mail", "faults", "configuration"):
                        db.execute("DELETE FROM " + table)
                    db.execute("INSERT INTO mail(subject,body) VALUES (?,?)", ("Review received", "Check the evidence and reproducibility."))
                elif self.path == "/cloud":
                    db.execute("INSERT OR REPLACE INTO configuration VALUES ('cloud', ?)", (json.dumps(body),))
                elif self.path == "/fault":
                    if body.get("status"):
                        db.execute("INSERT OR REPLACE INTO faults VALUES (?,?)", (body["service"], body["status"]))
                    else:
                        db.execute("DELETE FROM faults WHERE service=?", (body["service"],))
                elif self.path == "/messages":
                    fault = db.execute("SELECT status FROM faults WHERE service='slack'").fetchone()
                    if fault:
                        return self.respond(fault[0], {"error": "injected slack failure"})
                    ts = body.get("ts", f"{time.time():.6f}")
                    db.execute("INSERT INTO messages(ts,channel,user,text,thread) VALUES (?,?,?,?,?)",
                               (ts, body.get("channel", "C_LOCAL"), body.get("user", "U_OPERATOR"), body["text"], body.get("thread", "")))
                    body = {"ts": ts}
                elif self.path == "/mail":
                    db.execute("INSERT INTO mail(subject,body) VALUES (?,?)", (body["subject"], body["body"]))
                else:
                    return self.respond(404, {"error": "unknown fixture path"})
            self.respond(200, body)
        except (ValueError, KeyError, TypeError):
            self.respond(400, {"error": "invalid fixture request"})

    def cloud(self, db):
        row = db.execute("SELECT value FROM configuration WHERE name='cloud'").fetchone()
        return json.loads(row[0]) if row else {}

    def runpod(self, db):
        url = urlsplit(self.path)
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        pods = self.cloud(db).get("pods", {})
        if url.path.startswith("/v2/pods/"):
            pod = pods.get(url.path.removeprefix("/v2/pods/"))
            return self.respond(200, pod["live"]) if pod and pod.get("live") else self.respond(404, {"error": "pod missing"})
        if url.path == "/v2/billing/pods" and {"podId", "startTime", "endTime", "bucketSize"} <= query.keys():
            billing = pods.get(query["podId"], {}).get("billing")
            records = [] if billing is None else [{"podId": query["podId"], "startTime": query["startTime"],
                                                    "endTime": query["endTime"], **billing}]
            return self.respond(200, {"records": records, "metadata": {"recordCount": len(records), "query": query}})
        return self.respond(404, {"error": "unsupported Runpod fixture operation"})

    def aws(self):
        size = int(self.headers.get("Content-Length", 0))
        if size > 65536:
            return self.respond(413, {"error": "request too large"})
        raw = self.rfile.read(size).decode()
        with database() as db:
            fault = db.execute("SELECT status FROM faults WHERE service='aws'").fetchone()
            if fault:
                return self.respond(fault[0], {"__type": "AccessDeniedException"})
            cloud = self.cloud(db)
        if self.headers.get("X-Amz-Target", "").endswith(".GetCostAndUsage"):
            query = json.loads(raw)
            tag = next(part["Tags"]["Values"][0] for part in query["Filter"]["And"] if "Tags" in part)
            return self.respond(200, {"ResultsByTime": [{"TimePeriod": query["TimePeriod"], "Estimated": True,
                                                        "Groups": cloud.get("aws_billing", {}).get(tag, [])}]})
        query = {key: values[0] for key, values in parse_qs(raw).items()}
        if query.get("Action") == "GetCallerIdentity":
            account = escape(str(cloud.get("account", "000000000000")))
            return self.respond(200, '<GetCallerIdentityResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/">'
                                '<GetCallerIdentityResult><Arn>arn:aws:iam::' + account + ':user/local</Arn><UserId>local</UserId>'
                                '<Account>' + account + '</Account></GetCallerIdentityResult>'
                                '<ResponseMetadata><RequestId>local</RequestId></ResponseMetadata></GetCallerIdentityResponse>', xml=True)
        if query.get("Action") == "DescribeInstances":
            tag = query.get("Filter.1.Value.1", "")
            rows = []
            for item in cloud.get("instances", []):
                if item.get("tag") == tag:
                    rows.append('<item><instanceId>' + escape(item["id"]) + '</instanceId><instanceState><code>16</code>'
                                '<name>running</name></instanceState><tagSet><item><key>Name</key><value>' + escape(tag) +
                                '</value></item></tagSet></item>')
            return self.respond(200, '<DescribeInstancesResponse xmlns="http://ec2.amazonaws.com/doc/2016-11-15/">'
                                '<requestId>local</requestId><reservationSet><item><reservationId>r-local</reservationId>'
                                '<instancesSet>' + ''.join(rows) + '</instancesSet></item></reservationSet></DescribeInstancesResponse>', xml=True)
        return self.respond(400, {"error": "unsupported AWS fixture operation"})

    def respond(self, status, body, xml=False):
        data = body.encode() if xml else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/xml" if xml else "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args):
        pass


if __name__ == "__main__":
    if not os.environ.get("CIAB_FIXTURE_TOKEN"):
        raise SystemExit("CIAB_FIXTURE_TOKEN is required")
    ThreadingHTTPServer(("0.0.0.0", 8080), Server).serve_forever()
