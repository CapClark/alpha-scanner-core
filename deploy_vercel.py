"""
Deploy public/index.html to Vercel via the REST API — no node, no CLI, no git.

The trading host is an always-on Mac with only python + curl: it is not a git repo
and has no Node runtime, so `vercel deploy` (a node package) and any git-integration
push are both impossible there. This script publishes the single static page using
Vercel's HTTP API and the same VERCEL_TOKEN that run_daily.sh already reads from .env.

Flow (the documented, robust upload path):
  1. Read public/index.html, compute its sha1.
  2. Upload the blob to POST /v2/files  (idempotent — a re-upload of the same sha is a no-op).
  3. Create a production deployment referencing that sha via POST /v13/deployments.

Cosmetic + non-fatal: any failure here prints a warning and exits 0 so it can never
fail the trading run. Requires VERCEL_TOKEN in env and public/.vercel/project.json
(projectId + orgId) copied alongside the page.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

import requests

PAGE = Path("public/index.html")
PROJECT_JSON = Path("public/.vercel/project.json")
API = "https://api.vercel.com"
TIMEOUT = 30


def _warn(msg: str) -> None:
    # Non-fatal: warn and succeed so a cosmetic publish never fails the daily run.
    print(f"  deploy_vercel: {msg} — skipping publish (non-fatal)")
    sys.exit(0)


def main() -> None:
    token = os.environ.get("VERCEL_TOKEN")
    if not token:
        _warn("VERCEL_TOKEN not set")
    if not PAGE.exists():
        _warn(f"{PAGE} not found (run publish.py first)")
    if not PROJECT_JSON.exists():
        _warn(f"{PROJECT_JSON} not found (project not linked)")

    link = json.loads(PROJECT_JSON.read_text())
    project_id = link.get("projectId")
    org_id = link.get("orgId")               # team_… → passed as teamId on every call
    if not project_id:
        _warn("projectId missing from project.json")

    body = PAGE.read_bytes()
    sha = hashlib.sha1(body).hexdigest()
    team_q = {"teamId": org_id} if org_id else {}
    auth = {"Authorization": f"Bearer {token}"}

    # 1. upload the blob (keyed by sha; harmless to repeat)
    up = requests.post(
        f"{API}/v2/files",
        params=team_q,
        headers={**auth, "Content-Type": "application/octet-stream",
                 "x-vercel-digest": sha},
        data=body,
        timeout=TIMEOUT,
    )
    if up.status_code not in (200, 201):
        _warn(f"file upload failed [{up.status_code}]: {up.text[:200]}")

    # 2. create a production deployment that references the uploaded file
    dep = requests.post(
        f"{API}/v13/deployments",
        params={**team_q, "forceNew": "1"},
        headers={**auth, "Content-Type": "application/json"},
        json={
            "name": link.get("projectName", "strategygrade"),
            "project": project_id,
            "target": "production",
            "files": [{"file": "index.html", "sha": sha, "size": len(body)}],
            # Pure static single file — no build step.
            "projectSettings": {
                "framework": None, "buildCommand": None,
                "outputDirectory": None, "installCommand": None,
            },
        },
        timeout=TIMEOUT,
    )
    if dep.status_code not in (200, 201):
        _warn(f"deployment create failed [{dep.status_code}]: {dep.text[:300]}")

    url = dep.json().get("url", "")
    print(f"  deploy_vercel: published → https://{url}  (production alias updates shortly)")


if __name__ == "__main__":
    main()
