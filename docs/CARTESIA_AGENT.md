# Cartesia voice agent setup (ESC-3)

ollo can call the backup caregiver with a Cartesia voice agent that understands "I'm on it" instead of a keypad press. The server side is built and tested with mocked HTTP. The agent itself lives in your Cartesia account; create it once, as described below. The field names come from Cartesia's docs (webhook tools, dynamic variables, outbound calls), but check them against the console when you set it up, because this setup has not been run against a real account.

## 1. Environment (`.env`)

```sh
CALLS_ENABLED=true
CALL_PROVIDER=cartesia_agent
CALL_ALLOWLIST=+1XXXXXXXXXX,+1YYYYYYYYYY   # primary, backup: consenting teammates only
PUBLIC_CALLBACK_BASE_URL=https://<your-tunnel>   # must be HTTPS; expose only /webhooks/*
CARTESIA_API_KEY=...
CARTESIA_VERSION=2026-08-14
CARTESIA_AGENT_ID=agent_...
CARTESIA_FROM_NUMBER_ID=ap_...                  # a phone number on your Cartesia account
VOICE_WEBHOOK_SECRET=<long random string>       # also entered in the tool's bearer auth
```

If Twilio and Cartesia TTS are also configured, a failed agent call falls back to the keypad call for the same step.

## 2. Agent

**Welcome message:**

> This is ollo for {{caregiver}}. {{alert}} in the {{room}}. Can you check on it now?

**Instructions:**

> You are calling a daycare caregiver about a safety alert from a camera. Say what the alert is and which room, then ask whether they can check now. If they say yes, or anything like "I'm on it", call `acknowledge_alert` with decision "acknowledge". If they say they cannot, call it with decision "decline". Then repeat the tool's reply to them and end the call. Never describe the alert as a diagnosis, and never give medical advice. If they ask what happened, say only what the alert says.

ollo fills `{{caregiver}}`, `{{alert}}` and `{{room}}` for each call through `dynamic_variables`.

## 3. Webhook tool `acknowledge_alert`

| Field | Value |
|---|---|
| `type` | `webhook` |
| `name` | `acknowledge_alert` |
| `description` | Record whether the caregiver will handle the alert. |
| `api_schema.url` | `https://<your-tunnel>/webhooks/voice/ack` |
| `api_schema.method` | `POST` |
| `api_schema.authentication` | bearer, token = `VOICE_WEBHOOK_SECRET` |
| `request_body_schema.token` | string, value source: dynamic variable `ack_token` |
| `request_body_schema.decision` | string, model-provided, enum `acknowledge` or `decline` |
| `response_timeout_secs` | 10 |

The server replies with one plain sentence for the agent to say, such as "Acknowledged. Maya Chen is now responsible for this alert…" or "This alert is already handled by Dana…". Each call's `ack_token` works once; only its SHA-256 hash is stored.

## 4. Check before the demo

1. Arm calls in the dashboard, then trigger the restricted-area demo scenario.
2. Let the primary step pass without acknowledging.
3. Answer on the backup phone and say "I'm on it".
4. The event trace should show "Handled by ⟨backup name⟩ via voice" within about 2 s.
