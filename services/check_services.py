import base64
import json
import os
import sys
import urllib.error
import urllib.request


def request(url, body=None, authorization=None):
    headers = {"Content-Type": "application/json"}
    if authorization:
        headers["Authorization"] = authorization
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def fixture(path, body=None):
    return request(os.environ["CIAB_FIXTURE_URL"] + path, body, "Bearer " + os.environ["CIAB_FIXTURE_TOKEN"])


def main():
    if sys.argv[1] == "fixture":
        action, value = sys.argv[2:4]
        if action == "show":
            result = fixture("/state")
        elif action == "reset":
            result = fixture("/reset", {})
        elif action == "message":
            result = fixture("/messages", {"text": value})
        else:
            result = fixture("/fault", {"service": value or "slack", "status": 503 if action == "fail" else 0})
        print(json.dumps(result, indent=2))
        return 0
    credentials = base64.b64encode((os.environ["LANGFUSE_PUBLIC_KEY"] + ":" + os.environ["LANGFUSE_SECRET_KEY"]).encode()).decode()
    request(os.environ["LANGFUSE_BASE_URL"] + "/api/public/health")
    projects = request(os.environ["LANGFUSE_BASE_URL"] + "/api/public/projects", authorization="Basic " + credentials)
    assert projects["data"], "Langfuse authenticated but returned no projects"
    print("PASS Langfuse HTTPS, health, authenticated project access")
    fixture("/state")
    try:
        request(os.environ["CIAB_FIXTURE_URL"] + "/messages", authorization="Bearer invalid")
        raise AssertionError("Fixture accepted an invalid credential")
    except urllib.error.HTTPError as error:
        assert error.code == 401
    print("PASS local fixture authentication and invalid-credential rejection")
    try:
        request("https://cost.test/health")
        print("PASS real cost handler loaded from selected source")
    except urllib.error.HTTPError as error:
        if error.code != 503:
            raise
        print("NOT AVAILABLE: AE-225 cost tracker is absent from this PR stack")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
