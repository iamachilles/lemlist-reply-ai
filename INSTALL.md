# Install with Claude Code

The shortest path. You'll be done in about 5 minutes.

## Prerequisite

[Claude Code](https://claude.com/claude-code) installed and authenticated. Run `claude --version` in your terminal to confirm.

## 1. Clone and open

```bash
rm -rf lemlist-reply-ai && git clone https://github.com/iamachilles/lemlist-reply-ai && cd lemlist-reply-ai && claude
```

## 2. Say this to Claude

> Deploy the Lemlist Reply AI workflow.

That's it. Claude will read the instructions in this repo and guide you through the rest.

## 3. Answer Claude's questions

Claude will ask for:

- Your **n8n base URL and API key** (Settings → n8n API → Create API key)
- Your **Slack Bot Token and channel ID** (Claude walks you through creating the Slack app if you haven't yet)
- Your **OpenAI API key** (platform.openai.com/api-keys)
- Your **Lemlist API key and team name** (Settings → Integrations → API)
- A short description of **your company** (what you do, who you serve, tone)

You can either paste values in chat as Claude asks for them, or pre-fill `.env` (copy `.env.example` to `.env` and edit) and tell Claude "they're all in the .env file".

## 4. Paste one URL into Slack

When the script finishes, Claude will hand you a single URL and tell you where to paste it in your Slack app settings. That's the one thing Claude can't automate — Slack has no API for it.

## 5. Test it

Send a reply to one of your Lemlist campaigns. A message appears in your Slack channel with the AI-drafted response and Approve / Edit / Decline buttons.

---

Prefer to click through n8n yourself? See [MANUAL-INSTALL.md](./MANUAL-INSTALL.md).
