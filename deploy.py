#!/usr/bin/env python3
"""
Deploy the Lemlist Reply AI workflow to an n8n instance.

What this does (calls n8n REST API):
  1. Creates 3 credentials (Slack header auth, OpenAI, Lemlist basic auth)
  2. Imports workflow.json
  3. Patches all nodes that need credentials
  4. Patches the Config node with company / Slack channel / language
  5. Activates the workflow
  6. Registers the Lemlist webhook for `lemlistReplyReceived` via Lemlist API
  7. Prints the Slack Interaction URL (last manual step: paste into Slack app)

Usage:
  cp .env.example .env   # fill in values
  python3 deploy.py

Requires: requests (`pip install requests`)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("Missing dependency. Run: pip install requests", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).parent
WORKFLOW_PATH = ROOT / "workflow.json"


# ─── Env loading ──────────────────────────────────────────────────────────
def load_env() -> dict:
    env_path = ROOT / ".env"
    if not env_path.exists():
        print(f"Missing {env_path}. Copy .env.example to .env and fill it in.", file=sys.stderr)
        sys.exit(1)

    env: dict[str, str] = {}
    current_key: str | None = None
    for raw in env_path.read_text().splitlines():
        if not raw or raw.startswith("#"):
            continue
        if "=" in raw and not raw.startswith(" "):
            key, _, val = raw.partition("=")
            env[key.strip()] = val.strip().strip('"').strip("'")
            current_key = key.strip()
        elif current_key:
            env[current_key] += "\n" + raw

    required = [
        "N8N_BASE_URL", "N8N_API_KEY",
        "SLACK_BOT_TOKEN", "SLACK_CHANNEL_ID",
        "OPENAI_API_KEY",
        "LEMLIST_API_KEY", "LEMLIST_TEAM_NAME",
        "COMPANY_NAME", "COMPANY_CONTEXT",
    ]
    missing = [k for k in required if not env.get(k)]
    if missing:
        print(f"Missing in .env: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)
    env.setdefault("DEFAULT_LANGUAGE", "en")
    return env


# ─── n8n API wrapper ──────────────────────────────────────────────────────
class N8N:
    def __init__(self, base_url: str, api_key: str):
        self.base = base_url.rstrip("/")
        self.h = {"X-N8N-API-KEY": api_key, "Content-Type": "application/json"}

    def _req(self, method: str, path: str, **kw):
        r = requests.request(method, f"{self.base}/api/v1{path}", headers=self.h, **kw)
        if not r.ok:
            print(f"n8n {method} {path} failed: {r.status_code} {r.text}", file=sys.stderr)
            sys.exit(1)
        return r.json() if r.text else {}

    def create_credential(self, name: str, type_: str, data: dict) -> str:
        body = {"name": name, "type": type_, "data": data}
        return self._req("POST", "/credentials", json=body)["id"]

    def create_workflow(self, wf: dict) -> str:
        # n8n API rejects extra keys like 'active', 'pinData', 'tags' on create
        clean = {k: wf[k] for k in ("name", "nodes", "connections", "settings") if k in wf}
        clean.setdefault("settings", {})
        return self._req("POST", "/workflows", json=clean)["id"]

    def update_workflow(self, wf_id: str, wf: dict):
        clean = {k: wf[k] for k in ("name", "nodes", "connections", "settings") if k in wf}
        clean.setdefault("settings", {})
        self._req("PUT", f"/workflows/{wf_id}", json=clean)

    def activate_workflow(self, wf_id: str):
        self._req("POST", f"/workflows/{wf_id}/activate")

    def get_workflow(self, wf_id: str) -> dict:
        return self._req("GET", f"/workflows/{wf_id}")


# ─── Transformations ──────────────────────────────────────────────────────
SLACK_NODE_NAMES = {
    "Slack Post Message (HTTP)",
    "Open Edit Modal",
}
SLACK_NATIVE_NODE_NAMES = {
    "Update Slack - Sent",
    "Update Slack - Manual",
    "Update Slack - Edited & Sent",
}
LEMLIST_NODE_NAMES = {
    "Send Reply via Lemlist",
    "Send Edited Reply via Lemlist",
}
OPENAI_NODE_NAMES = {
    "OpenAI Chat Model",
    "OpenAI Chat Model1",
}


def patch_workflow(wf: dict, cred_ids: dict, env: dict):
    """Assign credentials and fill Config node values in place."""
    for node in wf["nodes"]:
        name = node["name"]

        if name in SLACK_NODE_NAMES:
            node["credentials"] = {
                "httpHeaderAuth": {"id": cred_ids["slack_header"], "name": "Slack Bot Token"}
            }
        elif name in SLACK_NATIVE_NODE_NAMES:
            node["credentials"] = {
                "slackApi": {"id": cred_ids["slack_native"], "name": "Slack Bot (native)"}
            }
        elif name in LEMLIST_NODE_NAMES:
            node["credentials"] = {
                "httpBasicAuth": {"id": cred_ids["lemlist"], "name": "Lemlist API"}
            }
        elif name in OPENAI_NODE_NAMES:
            node["credentials"] = {
                "openAiApi": {"id": cred_ids["openai"], "name": "OpenAI"}
            }
        elif name == "Config":
            for a in node["parameters"]["assignments"]["assignments"]:
                if a["name"] == "companyName":
                    a["value"] = env["COMPANY_NAME"]
                elif a["name"] == "companyContext":
                    a["value"] = env["COMPANY_CONTEXT"]
                elif a["name"] == "slackChannelId":
                    a["value"] = env["SLACK_CHANNEL_ID"]
                elif a["name"] == "defaultLanguage":
                    a["value"] = env["DEFAULT_LANGUAGE"]


def find_production_url(wf: dict, node_name: str, base_url: str) -> str | None:
    for node in wf["nodes"]:
        if node["name"] == node_name and node["type"] == "n8n-nodes-base.webhook":
            path = node["parameters"].get("path")
            if path:
                return f"{base_url.rstrip('/')}/webhook/{path}"
    return None


# ─── Lemlist webhook registration (direct API, no MCP) ────────────────────
def register_lemlist_webhook(api_key: str, team_name: str, webhook_url: str):
    r = requests.post(
        "https://api.lemlist.com/api/hooks",
        auth=(team_name, api_key),
        json={"targetUrl": webhook_url, "type": "lemlistReplyReceived"},
        timeout=20,
    )
    if not r.ok:
        print(f"Lemlist webhook registration failed: {r.status_code} {r.text}", file=sys.stderr)
        sys.exit(1)
    return r.json()


def patch_config_only(wf: dict, env: dict):
    """Fill Config node values. Leave credentials empty — user wires them in UI."""
    for node in wf["nodes"]:
        if node["name"] == "Config":
            for a in node["parameters"]["assignments"]["assignments"]:
                if a["name"] == "companyName":
                    a["value"] = env["COMPANY_NAME"]
                elif a["name"] == "companyContext":
                    a["value"] = env["COMPANY_CONTEXT"]
                elif a["name"] == "slackChannelId":
                    a["value"] = env["SLACK_CHANNEL_ID"]
                elif a["name"] == "defaultLanguage":
                    a["value"] = env["DEFAULT_LANGUAGE"]


# ─── Main ─────────────────────────────────────────────────────────────────
def main():
    env = load_env()
    n8n = N8N(env["N8N_BASE_URL"], env["N8N_API_KEY"])

    print("1/5  Loading workflow.json and filling Config node…")
    wf = json.loads(WORKFLOW_PATH.read_text())
    patch_config_only(wf, env)

    print("2/5  Importing workflow…")
    wf_id = n8n.create_workflow(wf)

    print("3/5  Registering Lemlist webhook for lemlistReplyReceived…")
    lemlist_webhook_url = find_production_url(wf, "Webhook", env["N8N_BASE_URL"])
    register_lemlist_webhook(env["LEMLIST_API_KEY"], env["LEMLIST_TEAM_NAME"], lemlist_webhook_url)

    print("4/5  Workflow imported, Lemlist webhook registered.")
    print("5/5  Two manual steps remain — see below.\n")

    slack_interaction_url = find_production_url(wf, "Slack Interaction Webhook", env["N8N_BASE_URL"])
    wf_url = f"{env['N8N_BASE_URL']}/workflow/{wf_id}"

    print("─" * 72)
    print("MANUAL STEP A — Create 4 credentials in n8n and assign them")
    print("─" * 72)
    print(f"Open the workflow: {wf_url}")
    print()
    print("In n8n → Credentials → Add credential, create these 4:")
    print()
    print("  1. Slack Bot Token  (type: Header Auth)")
    print(f"       Header name  : Authorization")
    print(f"       Header value : Bearer {env['SLACK_BOT_TOKEN'][:8]}… (from .env)")
    print("       Assign to   : Slack Post Message (HTTP), Open Edit Modal")
    print()
    print("  2. Slack Bot (native)  (type: Slack API)")
    print(f"       Access Token : {env['SLACK_BOT_TOKEN'][:8]}… (from .env, same xoxb-)")
    print("       Assign to   : Update Slack - Sent / Manual / Edited & Sent")
    print()
    print("  3. OpenAI  (type: OpenAI API)")
    print(f"       API Key     : {env['OPENAI_API_KEY'][:7]}… (from .env)")
    print("       Assign to   : OpenAI Chat Model, OpenAI Chat Model1")
    print()
    print("  4. Lemlist API  (type: HTTP Basic Auth)")
    print(f"       Username    : {env['LEMLIST_TEAM_NAME']}")
    print(f"       Password    : (Lemlist API key from .env)")
    print("       Assign to   : Send Reply via Lemlist, Send Edited Reply via Lemlist")
    print()
    print("Then toggle the workflow Active (top-right switch).")
    print()
    print("─" * 72)
    print("MANUAL STEP B — Paste this URL into your Slack app:")
    print("─" * 72)
    print(f"  {slack_interaction_url}")
    print()
    print("  1. api.slack.com/apps → your app → Interactivity & Shortcuts")
    print("  2. Replace the placeholder Request URL with the URL above")
    print("  3. Save Changes")
    print("─" * 72)


if __name__ == "__main__":
    main()
