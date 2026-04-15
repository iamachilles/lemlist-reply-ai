#!/usr/bin/env python3
"""
Deploy the Lemlist Reply AI workflow to an n8n instance.

End-to-end automation:
  1. Finds or creates 4 n8n credentials (Slack header, Slack native, OpenAI, Lemlist).
     Credential IDs are persisted to .env after first run for idempotent reruns.
  2. Imports workflow.json with credentials pre-assigned and Config filled.
  3. Activates the workflow.
  4. Registers the Lemlist webhook (type configurable via LEMLIST_WEBHOOK_TYPE).
  5. Prints the final Slack Interaction URL to paste into your Slack app.

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
ENV_PATH = ROOT / ".env"


# ─── Env loading / saving ─────────────────────────────────────────────────
def load_env() -> dict:
    if not ENV_PATH.exists():
        print(f"Missing {ENV_PATH}. Copy .env.example to .env and fill it in.", file=sys.stderr)
        sys.exit(1)

    env: dict[str, str] = {}
    current_key: str | None = None
    for raw in ENV_PATH.read_text().splitlines():
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
    env.setdefault("LEMLIST_WEBHOOK_TYPE", "emailsReplied")
    return env


def persist_credential_ids(new_ids: dict[str, str]):
    """Append/update CRED_ID_* entries in .env so reruns are idempotent."""
    text = ENV_PATH.read_text()
    lines = text.splitlines()
    existing_keys = {l.partition("=")[0].strip() for l in lines if "=" in l and not l.startswith("#")}

    updated = []
    key_map = {
        "slack_header": "N8N_CRED_ID_SLACK_HEADER",
        "slack_native": "N8N_CRED_ID_SLACK_NATIVE",
        "openai":       "N8N_CRED_ID_OPENAI",
        "lemlist":      "N8N_CRED_ID_LEMLIST",
    }
    for line in lines:
        handled = False
        for cred_key, env_key in key_map.items():
            if line.startswith(f"{env_key}=") and cred_key in new_ids:
                updated.append(f"{env_key}={new_ids[cred_key]}")
                handled = True
                break
        if not handled:
            updated.append(line)

    # Append any that weren't already in the file
    appends = []
    for cred_key, env_key in key_map.items():
        if cred_key in new_ids and env_key not in existing_keys:
            appends.append(f"{env_key}={new_ids[cred_key]}")
    if appends:
        if updated and updated[-1].strip():
            updated.append("")
        updated.append("# ─── Credential IDs (auto-written by deploy.py) ───")
        updated.extend(appends)

    ENV_PATH.write_text("\n".join(updated) + "\n")


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

    def create_credential(self, name: str, type_: str, data: dict) -> tuple[str | None, str | None]:
        body = {"name": name, "type": type_, "data": data}
        r = self._req("POST", "/credentials", raise_on_error=False, json=body)
        if r.ok:
            return r.json().get("id"), None
        return None, r.text

    def credential_exists(self, cred_id: str) -> bool:
        # n8n public API doesn't expose GET /credentials/:id — assume valid if provided.
        # If it's been deleted manually the workflow import will fail loudly and the user
        # can clear the ID from .env.
        return bool(cred_id)

    def create_workflow(self, wf: dict) -> str:
        clean = {k: wf[k] for k in ("name", "nodes", "connections", "settings") if k in wf}
        clean.setdefault("settings", {})
        r = self._req("POST", "/workflows", json=clean)
        return r.json()["id"]

    def activate_workflow(self, wf_id: str):
        self._req("POST", f"/workflows/{wf_id}/activate")

    def deactivate_workflow(self, wf_id: str):
        self._req("POST", f"/workflows/{wf_id}/deactivate", raise_on_error=False)

    def update_workflow(self, wf_id: str, wf: dict):
        # n8n silently ignores PUT changes while a workflow is active.
        # Deactivate first, update, then reactivate.
        self.deactivate_workflow(wf_id)
        clean = {k: wf[k] for k in ("name","nodes","connections","settings") if k in wf}
        clean.setdefault("settings", {})
        self._req("PUT", f"/workflows/{wf_id}", json=clean)


# ─── Node → credential mapping ────────────────────────────────────────────
SLACK_HEADER_NODES = {"Slack Post Message (HTTP)", "Open Edit Modal"}
SLACK_NATIVE_NODES = {"Update Slack - Sent", "Update Slack - Manual", "Update Slack - Edited & Sent"}
LEMLIST_NODES = {"Send Reply via Lemlist", "Send Edited Reply via Lemlist"}
OPENAI_NODES = {"OpenAI Chat Model", "OpenAI Chat Model1"}


def patch_workflow(wf: dict, cred_ids: dict, env: dict):
    for node in wf["nodes"]:
        name = node["name"]
        if name in SLACK_HEADER_NODES:
            node["credentials"] = {"httpHeaderAuth": {"id": cred_ids["slack_header"], "name": "Slack Bot Token"}}
        elif name in SLACK_NATIVE_NODES:
            node["credentials"] = {"slackApi": {"id": cred_ids["slack_native"], "name": "Slack Bot (native)"}}
        elif name in LEMLIST_NODES:
            node["credentials"] = {"httpBasicAuth": {"id": cred_ids["lemlist"], "name": "Lemlist API"}}
        elif name in OPENAI_NODES:
            node["credentials"] = {"openAiApi": {"id": cred_ids["openai"], "name": "OpenAI"}}
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
def register_lemlist_webhook(api_key: str, team_name: str, webhook_url: str, event_type: str):
    r = requests.post(
        "https://api.lemlist.com/api/hooks",
        auth=(team_name, api_key),
        json={"targetUrl": webhook_url, "type": event_type},
        timeout=20,
    )
    if r.status_code == 409:
        return True  # idempotent
    if not r.ok:
        print(f"⚠️  Lemlist webhook registration failed: {r.status_code} {r.text}", file=sys.stderr)
        print("    Fallback: register manually in Lemlist → Settings → Integrations → Webhooks", file=sys.stderr)
        return False
    return True


# ─── Credential resolution ────────────────────────────────────────────────
CRED_SPECS = [
    # key, display name, n8n type, data-builder
    # Schema quirks: slackApi needs `notice:""`; openAiApi needs `header:False`.
    ("slack_header", "Slack Bot Token", "httpHeaderAuth",
        lambda e: {"name": "Authorization", "value": f"Bearer {e['SLACK_BOT_TOKEN']}"}),
    ("slack_native", "Slack Bot (native)", "slackApi",
        lambda e: {"accessToken": e["SLACK_BOT_TOKEN"], "notice": ""}),
    ("openai", "OpenAI", "openAiApi",
        lambda e: {"apiKey": e["OPENAI_API_KEY"], "header": False}),
    ("lemlist", "Lemlist API", "httpBasicAuth",
        lambda e: {"user": e["LEMLIST_TEAM_NAME"], "password": e["LEMLIST_API_KEY"]}),
]

ENV_ID_KEY = {
    "slack_header": "N8N_CRED_ID_SLACK_HEADER",
    "slack_native": "N8N_CRED_ID_SLACK_NATIVE",
    "openai":       "N8N_CRED_ID_OPENAI",
    "lemlist":      "N8N_CRED_ID_LEMLIST",
}


def resolve_credentials(n8n: N8N, env: dict) -> tuple[dict, list[str]]:
    cred_ids: dict[str, str] = {}
    failures: list[str] = []
    newly_created: dict[str, str] = {}

    for key, cred_name, cred_type, build_data in CRED_SPECS:
        existing_id = env.get(ENV_ID_KEY[key])
        if existing_id and n8n.credential_exists(existing_id):
            cred_ids[key] = existing_id
            print(f"     ✓ reusing '{cred_name}' from .env (id {existing_id[:8]}…)")
            continue
        new_id, err = n8n.create_credential(cred_name, cred_type, build_data(env))
        if new_id:
            cred_ids[key] = new_id
            newly_created[key] = new_id
            print(f"     ✓ created '{cred_name}' (id {new_id[:8]}…)")
        else:
            failures.append(f"Could not create '{cred_name}' (type {cred_type}): {err}")

    if newly_created:
        persist_credential_ids(newly_created)
        print(f"     → wrote {len(newly_created)} credential IDs to .env for idempotent reruns")

    return cred_ids, failures


# ─── Main ─────────────────────────────────────────────────────────────────
def main():
    env = load_env()
    n8n = N8N(env["N8N_BASE_URL"], env["N8N_API_KEY"])

    print("1/5  Resolving credentials in n8n…")
    cred_ids, failures = resolve_credentials(n8n, env)

    if failures:
        print()
        print("─" * 72)
        print("⚠️  Some credentials could not be created via API.")
        print("─" * 72)
        for f in failures:
            print(f"    {f}")
        print()
        print("Fallback: create the missing credentials manually in n8n UI, then")
        print("paste the IDs into .env as N8N_CRED_ID_* vars and rerun.")
        sys.exit(1)

    print("2/5  Loading and patching workflow.json…")
    wf = json.loads(WORKFLOW_PATH.read_text())
    patch_workflow(wf, cred_ids, env)

    print("3/5  Importing workflow…")
    wf_id = n8n.create_workflow(wf)

    print("4/5  Activating workflow…")
    n8n.activate_workflow(wf_id)

    print(f"5/5  Registering Lemlist webhook (type: {env['LEMLIST_WEBHOOK_TYPE']})…")
    lemlist_webhook_url = find_production_url(wf, "Webhook", env["N8N_BASE_URL"])
    register_lemlist_webhook(
        env["LEMLIST_API_KEY"], env["LEMLIST_TEAM_NAME"],
        lemlist_webhook_url, env["LEMLIST_WEBHOOK_TYPE"]
    )

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
