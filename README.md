# Lemlist Reply AI

An n8n automation that turns your Lemlist inbox into a one-click Slack approval queue, powered by an AI agent.

## What it does

1. A prospect replies to a Lemlist campaign.
2. An AI agent classifies the reply (`meeting_request`, `demo_information_request`, `redirection`, `not_interested`) and drafts a contextual response.
3. The draft is posted to a Slack channel with three buttons: **Approve**, **Edit**, **Decline**.
4. Approve sends the reply through the Lemlist API. Edit opens a modal. Decline leaves it for you to handle manually.

## What you need

- An n8n instance (self-hosted or cloud) with the **API enabled**. Settings → n8n API → Create API key.
- A Slack workspace where you can install apps.
- An OpenAI API key.
- A Lemlist account with API access.

## Two ways to install

### Option A — Automated with Claude Code (recommended)

If you have [Claude Code](https://claude.com/claude-code):

```bash
git clone https://github.com/iamachilles/lemlist-reply-ai
cd lemlist-reply-ai
claude
```

Then say: **"Deploy the Lemlist Reply AI workflow."**

Claude will ask you for the API keys one by one, set up everything, and print one final URL to paste in Slack. Full walkthrough: [INSTALL.md](./INSTALL.md).

### Option B — Manual in the n8n UI

Import `workflow.json` into n8n. Follow the numbered sticky notes (① → ⑧) in the workflow itself. Every step tells you which nodes to change and the exact UI paths in Slack, Lemlist, OpenAI, and n8n.

## Files in this package

| File | Purpose |
|---|---|
| `workflow.json` | The n8n workflow template (scrubbed of all client data). |
| `slack-app-manifest.yaml` | Slack app manifest — paste into api.slack.com/apps to create the app in 30 seconds. |
| `deploy.py` | Automated deployment script (used by Option A). |
| `.env.example` | Template for the deployment script config. |
| `INSTALL.md` | Claude Code install walkthrough. |
| `MANUAL-INSTALL.md` | Manual install walkthrough (same as the sticky notes in the workflow). |

## Cost

- OpenAI: ~$0.001 per reply with `gpt-4o-mini`.
- n8n: free if self-hosted, $20/mo for n8n Cloud starter.
- Slack app + Lemlist: free tier works.

## License

Free to use, modify, and redistribute. Attribution appreciated.
