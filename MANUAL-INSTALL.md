# Manual install (no Claude Code)

Prefer to click through it yourself? Import `workflow.json` into n8n and follow the numbered sticky notes inside the workflow — they contain the same instructions as below.

## Prerequisites

Same as the Claude Code install: n8n instance, Slack workspace admin, OpenAI key, Lemlist API access.

## Setup order

**Do steps ① → ⑧ in order. The workflow won't activate until every credential is set.**

### ① Create the Slack app
1. Open https://api.slack.com/apps → **Create New App** → **From a manifest**.
2. Pick your workspace → **Next**.
3. Delete YAML box content, paste `slack-app-manifest.yaml` → **Next** → **Create**.
4. Left sidebar → **Install App** → **Install to Workspace** → **Allow**.
5. Left sidebar → **OAuth & Permissions** → copy the **Bot User OAuth Token** (`xoxb-…`).

### ② Slack credential in n8n
Nodes to update: `Slack Post Message (HTTP)`, `Open Edit Modal`, `Update Slack - Sent`, `Update Slack - Manual`, `Update Slack - Edited & Sent`.

1. n8n → **Credentials** → **Add credential** → **Header Auth**.
2. Name: `Slack Bot Token`. Header name: `Authorization`. Value: `Bearer xoxb-…`. Save.
3. Create a second credential → **Slack API** → paste the same `xoxb-…` token.
4. Assign the Header Auth credential to `Slack Post Message (HTTP)` and `Open Edit Modal`.
5. Assign the Slack API credential to the three `Update Slack - *` nodes.

### ③ OpenAI credential
Nodes to update: `OpenAI Chat Model`, `OpenAI Chat Model1`.

1. Get key at https://platform.openai.com/api-keys.
2. n8n → **Credentials** → **Add credential** → **OpenAI API** → paste key → Save.
3. Assign to both Chat Model nodes.

### ④ Lemlist Basic Auth
Nodes to update: `Send Reply via Lemlist`, `Send Edited Reply via Lemlist`.

1. Lemlist → **Settings** → **Integrations** → **API** → copy key.
2. n8n → **Credentials** → **Add credential** → **HTTP Basic Auth**.
3. Username: Lemlist team name. Password: API key. Save.
4. Assign to both Lemlist send nodes.

### ⑤ Fill the Config node
Node: `Config`.

- `companyName` — your brand.
- `companyContext` — what you do, for whom, value props, tone (3–5 lines).
- `slackChannelId` — right-click channel in Slack → View channel details → bottom → copy ID (starts with `C`).
- `defaultLanguage` — `en` or `fr`.

### ⑥ Activate the workflow
Top-right of the n8n editor → toggle **Active**. If it fails, re-check credentials in ①–④.

### ⑦ Paste Interaction URL into Slack
1. Open the `Slack Interaction Webhook` node → copy **Production URL**.
2. api.slack.com/apps → your app → **Interactivity & Shortcuts**.
3. Replace the placeholder with the URL → **Save Changes**.

### ⑧ Register Lemlist webhook
1. Open the top `Webhook` node → copy **Production URL**.
2. Lemlist → **Settings** → **Integrations** → **Webhooks** → **+ Add webhook**.
3. Paste URL. Event: `lemlistReplyReceived`. Save.

## Test

Send a manual reply to one of your campaigns. Within seconds a Slack message should appear with the AI draft and Approve / Edit / Decline buttons.
