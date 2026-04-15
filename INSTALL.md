# Install with Claude Code

This walkthrough deploys the Lemlist Reply AI workflow end-to-end in under 5 minutes. Claude Code handles n8n setup, credential creation, and Lemlist webhook registration. You handle the three things that require human hands.

## Before you start

Gather these (10 min, one-time):

### 1. n8n API key
- Open your n8n instance → **Settings** → **n8n API** → **Create API key**.
- Copy the key and your n8n base URL (e.g. `https://n8n.yourdomain.com` or `http://localhost:5678`).

### 2. Slack app + Bot token
- Go to https://api.slack.com/apps → **Create New App** → **From a manifest**.
- Pick your workspace → **Next**.
- Delete the YAML box contents, paste the contents of `slack-app-manifest.yaml` → **Next** → **Create**.
- Left sidebar → **Install App** → **Install to Workspace** → **Allow**.
- Left sidebar → **OAuth & Permissions** → copy the **Bot User OAuth Token** (starts with `xoxb-`).
- In Slack, `/invite @Lemlist Reply AI` in the channel where you want drafts posted.
- Right-click that channel → **View channel details** → scroll to bottom → copy the **Channel ID** (starts with `C`).

### 3. OpenAI key
- Go to https://platform.openai.com/api-keys → **Create new secret key** → copy it (starts with `sk-`).

### 4. Lemlist API key
- Lemlist → bottom-left profile → **Settings** → **Integrations** → **API** → copy the key.
- Note your Lemlist **team name** (visible top-left in Lemlist).

## Deploy

1. `cd` into this folder.
2. Copy the env template:
   ```bash
   cp .env.example .env
   ```
3. Open `.env` in an editor and fill in every field with the values from the section above.
4. Open Claude Code in this folder and say:
   > Deploy the Lemlist Reply AI workflow using `deploy.py`.

   Or just run it directly:
   ```bash
   pip install requests
   python3 deploy.py
   ```

The script prints progress for each step (1/7 → 7/7). At the end it gives you **one URL to paste** — the Slack Interaction URL — along with the exact click path in Slack.

## The final manual step

The script can't reach into your Slack app settings, so the last thing you do is:

1. Back to api.slack.com/apps → your **Lemlist Reply AI** app.
2. Left sidebar → **Interactivity & Shortcuts**.
3. Replace the placeholder **Request URL** with the URL the script printed.
4. **Save Changes**.

## Test it

Send a manual reply from a test address to one of your Lemlist campaigns. Within a few seconds, a Slack message appears in the channel you configured, with the AI-drafted response and the three buttons. Click **Approve** — the reply goes out via Lemlist.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `n8n … failed: 401` | Check `N8N_API_KEY` and `N8N_BASE_URL`. The key must come from n8n Settings → n8n API. |
| `Lemlist webhook registration failed` | Verify `LEMLIST_TEAM_NAME` matches the team name shown in Lemlist. |
| No Slack message appears after a reply | In n8n, open the workflow → **Executions** tab → check for errors. Usually a bad `SLACK_CHANNEL_ID` or the bot isn't invited to the channel. |
| Approve button does nothing | Interactivity URL not updated in Slack app (step "final manual step" above). |
| `Cannot find credential type: slackApi` | You're on an older n8n version. Upgrade to n8n 1.0+. |

## What the script does under the hood

Step-by-step:

1. Creates 4 n8n credentials: Slack header auth, Slack native (for update nodes), OpenAI, Lemlist basic auth.
2. Loads `workflow.json` and patches every node to reference the right credential.
3. Fills the `Config` node with your company name, context, Slack channel, and language.
4. Creates the workflow via `POST /api/v1/workflows`.
5. Activates it via `POST /api/v1/workflows/:id/activate`.
6. Registers the Lemlist webhook for `lemlistReplyReceived` via Lemlist's `/api/hooks` endpoint.
7. Prints the Slack Interaction URL for the final paste.

Everything is ~200 lines of Python. Read `deploy.py` if you want to see exactly what runs.
