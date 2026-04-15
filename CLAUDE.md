# Claude Code instructions — Lemlist Reply AI deploy

You are helping a user deploy the Lemlist Reply AI n8n workflow.

## Default behavior

If the user says something like "deploy", "install", "set this up", or "run it":

1. Check if `.env` exists.
   - If not, copy `.env.example` to `.env`, open it, and tell the user exactly which fields are still empty. Do not fill placeholder values — ask them.
2. Once `.env` is complete, run:
   ```bash
   pip install requests
   python3 deploy.py
   ```
3. Relay the script's output. The script ends with one URL the user must paste into their Slack app — surface that URL clearly and restate the 3 Slack clicks.

## What the user still has to do manually (do not promise to automate these)

- Create the Slack app from `slack-app-manifest.yaml` at api.slack.com/apps (Slack has no public API for app creation).
- Generate an OpenAI API key at platform.openai.com/api-keys.
- Paste the final Slack Interaction URL into the Slack app's Interactivity settings after `deploy.py` finishes.

## If the user asks for the manual install

Point them at `MANUAL-INSTALL.md` or tell them to import `workflow.json` into n8n and follow the numbered sticky notes ① → ⑧ inside the workflow.

## Do not

- Do not modify `workflow.json` unless the user explicitly asks to customize it. The file was carefully scrubbed of all prior client data; re-introducing real IDs or credentials would break that guarantee.
- Do not commit `.env` to git.
- Do not run `deploy.py` without a populated `.env`.
