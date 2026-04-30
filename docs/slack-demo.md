# Slack Demo Notes

Use Slack as a chat surface for Preconfin, not as a separate source of truth.

The production integration belongs in the backend app:

- route: `POST /api/slack/preconfin/command`
- source of truth: `precon_backend`
- responsibilities: Slack signature verification, org mapping, org scoping, read-only routing, audit-safe handling, and chart upload security

This examples repo is only for safe demo guidance. Do not move production Slack behavior here.

## Supported Slash Commands

Examples of supported commands:

- `/preconfin what is my current revenue`
- `/preconfin where can we cut spending`
- `/preconfin what is my burn rate`
- `/preconfin what needs attention`
- `/preconfin briefing`
- `/preconfin chart cashflow`
- `/preconfin chart operating`
- `/preconfin chart revenue`

## Safe Payload Example

Use placeholder values only. Do not commit real Slack secrets, bot tokens, or signed request samples.

```bash
curl -X POST "https://api.preconfin.com/api/slack/preconfin/command" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "X-Slack-Request-Timestamp: <unix-timestamp>" \
  -H "X-Slack-Signature: v0=<computed-signature>" \
  --data "command=%2Fpreconfin&team_id=T123&channel_id=C123&user_id=U123&text=briefing"
```

The backend must compute and verify Slack signatures using the real signing secret. Keep that secret server-side only.

## Chart Upload Notes

- Chart commands use canonical `get_people_charts` rows from the backend.
- The backend should upload chart files with Slack's external upload flow, not `files.upload`.
- If chart rendering is unavailable in the backend environment, return a concise text summary instead of failing the command.

## Setup Expectations

If Slack is not mapped to a Preconfin organization, the backend should return a setup message telling the user to connect or reconnect Slack from Preconfin.

That mapping must stay org-scoped and server-side.
