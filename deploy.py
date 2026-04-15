#!/usr/bin/env python3
"""
Deploy the Lemlist Reply AI workflow to an n8n instance.

End-to-end automation:
  1. Finds or creates 4 n8n credentials (Slack header, Slack native, OpenAI, Lemlist).
  2. Imports workflow.json with credentials pre-assigned and Config filled.
  3. Activates the workflow.
  4. Registers the Lemlist webhook for lemlistReplyReceived.
  5. Prints the final Slack Interaction URL to paste into your Slack app.

No n8n UI clicks required unless the API rejects credential creation, in
which case the script prints a fallback with precise manual steps.

Usage:
  cp .env.example .env   # fill in values
  python3 deploy.py

Requires: requests (`pip install requests`)
"""
from __future__ import annotations

import json
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

    def _req(self, method: str, path: str, raise_on_error=True, **kw):
        r = requests.request(method, f"{self.base}/api/v1{path}", headers=self.h, timeout=30, **kw)
        if not r.ok and raise_on_error:
            print(f"n8n {method} {path} failed: {r.status_code} {r.text}", file=sys.stderr)
            sys.exit(1)
        return r

    def try_create_credential(self, name: str, type_: str, data: dict) -> tuple[str | None, str | None]:
        """Attempt to create a credential. Returns (id, error_message)."""
        # Some n8n builds require a `nodesAccess` array. It's been deprecated but still accepted.
        body = {"name": name, "type": type_, "data": data}
        r = self._req("POST", "/credentials", raise_on_error=False, json=body)
        if r.ok:
            return r.json().get("id"), None
        # Try once with nodesAccess: []
        body["nodesAccess"] = []
        r = self._req("POST", "/credentials", raise_on_error=False, json=body)
        if r.ok:
            return r.json().get("id"), None
        return None, r.text

    def list_credentials(self) -> list[dict]:
        r = self._req("GET", "/credentials", raise_on_error=False)
        if not r.ok:
            return []
        body = r.json()
        return body.get("data", body) if isinstance(body, dict) else body

    def find_credential_by_name(self, name: str) -> str | None:
        for c in self.list_credentials():
            if c.get("name") == name:
                return c.get("id")
        return None

    def create_workflow(self, wf: dict) -> str:
        clean = {k: wf[k] for k in ("name", "nodes", "connections", "settings") if k in wf}
        clean.setdefault("settings", {})
        r = self._req("POST", "/workflows", json=clean)
        return r.json()["id"]

    def activate_workflow(self, wf_id: str):
        self._req("POST", f"/workflows/{wf_id}/activate")


# ─── Node → credential mapping ────────────────────────────────────────────
SLACK_HEADER_NODES = {"Slack Post Message (HTTP)", "Open Edit Modal"}
SLACK_NATIVE_NODES = {"Update Slack - Sent", "Update Slack - Manual", "Update Slack - Edited & Sent"}
LEMLIST_NODES = {"Send Reply via Lemlist", "Send Edited Reply via Lemlist"}
OPENAI_NODES = {"OpenAI Chat Model", "OpenAI Chat Model1"}


def patch_workflow(wf: dict, cred_ids: dict, env: dict):
    for node in wf["nodes"]:
        name = node["name"]
        if name in SLACK_HEADER_NODES:
            node["credentials"] = {
                "httpHeaderAuth": {"id": cred_ids["slack_header"], "name": "Slack Bot Token"}
            }
        elif name in SLACK_NATIVE_NODES:
            node["credentials"] = {
                "slackApi": {"id": cred_ids["slack_native"], "name": "Slack Bot (native)"}
            }
        elif name in LEMLIST_NODES:
            node["credentials"] = {
                "httpBasicAuth": {"id": cred_ids["lemlist"], "name": "Lemlist API"}
            }
        elif name in OPENAI_NODES:
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


# ─── Lemlist webhook registration ─────────────────────────────────────────
def register_lemlist_webhook(api_key: str, team_name: str, webhook_url: str):
    r = requests.post(
        "https://api.lemlist.com/api/hooks",
        auth=(team_name, api_key),
        json={"targetUrl": webhook_url, "type": "lemlistReplyReceived"},
        timeout=20,
    )
    if r.status_code == 409:
        # Webhook already registered for this URL — idempotent success.
        return True
    if not r.ok:
        print(f"⚠️  Lemlist webhook registration failed: {r.status_code} {r.text}", file=sys.stderr)
        print("    You can register it manually: Lemlist → Settings → Integrations → Webhooks", file=sys.stderr)
        return False
    return True


# ─── Credential resolution (find-or-create) ──────────────────────────────
CRED_SPECS = [
    # key, display name, n8n type, data-builder (takes env dict)
    # Payloads tuned to n8n's schema quirks: slackApi needs `notice` when
    # signatureSecret is absent; openAiApi needs explicit `header: false`
    # to avoid the if-then branch that demands headerName/headerValue.
    ("slack_header", "Slack Bot Token", "httpHeaderAuth",
        lambda e: {"name": "Authorization", "value": f"Bearer {e['SLACK_BOT_TOKEN']}"}),
    ("slack_native", "Slack Bot (native)", "slackApi",
        lambda e: {"accessToken": e["SLACK_BOT_TOKEN"], "notice": ""}),
    ("openai", "OpenAI", "openAiApi",
        lambda e: {"apiKey": e["OPENAI_API_KEY"], "header": False}),
    ("lemlist", "Lemlist API", "httpBasicAuth",
        lambda e: {"user": e["LEMLIST_TEAM_NAME"], "password": e["LEMLIST_API_KEY"]}),
]


def resolve_credentials(n8n: N8N, env: dict) -> tuple[dict, list[str]]:
    """Returns (cred_ids dict, list of failure messages). If all succeed, failures is empty."""
    cred_ids: dict[str, str] = {}
    failures: list[str] = []

    # First try to find existing credentials by name (idempotent)
    existing: dict[str, str] = {}
    for c in n8n.list_credentials():
        existing[c.get("name", "")] = c.get("id", "")

    for key, cred_name, cred_type, build_data in CRED_SPECS:
        if cred_name in existing:
            cred_ids[key] = existing[cred_name]
            print(f"     ✓ reusing existing credential '{cred_name}'")
            continue
        new_id, err = n8n.try_create_credential(cred_name, cred_type, build_data(env))
        if new_id:
            cred_ids[key] = new_id
            print(f"     ✓ created credential '{cred_name}'")
        else:
            failures.append(f"Could not create '{cred_name}' (type {cred_type}): {err}")

    return cred_ids, failures


# ─── Main ─────────────────────────────────────────────────────────────────
def main():
    env = load_env()
    n8n = N8N(env["N8N_BASE_URL"], env["N8N_API_KEY"])

    print("1/5  Resolving credentials in n8n (find or create)…")
    cred_ids, failures = resolve_credentials(n8n, env)

    if failures:
        print()
        print("─" * 72)
        print("⚠️  Some credentials could not be created via API.")
        print("    This is usually an n8n version-specific schema issue.")
        print("─" * 72)
        for f in failures:
            print(f"    {f}")
        print()
        print("Fallback: create the missing credentials manually in n8n UI, then rerun.")
        print("n8n → Personal → Credentials tab → Add credential. Required:")
        print()
        print("  • Name: 'Slack Bot Token'        Type: Header Auth")
        print("      Header: Authorization = Bearer <your xoxb- token>")
        print("  • Name: 'Slack Bot (native)'     Type: Slack API")
        print("      Access Token = <same xoxb- token>")
        print("  • Name: 'OpenAI'                 Type: OpenAI API")
        print("      API Key = <your sk- key>")
        print("  • Name: 'Lemlist API'            Type: HTTP Basic Auth")
        print("      User = <team name>, Password = <Lemlist API key>")
        print()
        print("Names must match exactly. Once created, rerun `python3 deploy.py`.")
        sys.exit(1)

    print("2/5  Loading and patching workflow.json…")
    wf = json.loads(WORKFLOW_PATH.read_text())
    patch_workflow(wf, cred_ids, env)

    print("3/5  Importing workflow…")
    wf_id = n8n.create_workflow(wf)

    print("4/5  Activating workflow…")
    n8n.activate_workflow(wf_id)

    print("5/5  Registering Lemlist webhook…")
    lemlist_webhook_url = find_production_url(wf, "Webhook", env["N8N_BASE_URL"])
    register_lemlist_webhook(env["LEMLIST_API_KEY"], env["LEMLIST_TEAM_NAME"], lemlist_webhook_url)

    slack_interaction_url = find_production_url(wf, "Slack Interaction Webhook", env["N8N_BASE_URL"])
    wf_url = f"{env['N8N_BASE_URL']}/workflow/{wf_id}"

    print()
    print("─" * 72)
    print("✅  Deploy complete. One last step (in Slack, not n8n):")
    print("─" * 72)
    print(f"  Paste this URL: {slack_interaction_url}")
    print()
    print("  1. api.slack.com/apps → your Lemlist Reply AI app")
    print("  2. Left sidebar → Interactivity & Shortcuts")
    print("  3. Replace the placeholder Request URL → Save Changes")
    print("─" * 72)
    print(f"\nWorkflow: {wf_url}")


if __name__ == "__main__":
    main()
