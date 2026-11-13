# smart_calendar

Family event assistant: forward an invitation, ticket or booking (text, photo or PDF) to a Telegram
bot. Claude extracts the events, the bot shows them with **Add / Edit / Skip** buttons, and on
**Add** they go into a shared Google Calendar.

```
Telegram (forward / share) ─► app/bot.py ─► app/extract.py (Claude) ─► confirm in chat ─► app/gcal.py ─► Google Calendar
                                    └─ app/store.py (SQLite: pending suggestions)
```

WhatsApp messages and screenshots get in the same way: use **Share → Telegram → the bot**.

## Setup (one-time)

1. **Telegram bot**: message [@BotFather](https://t.me/BotFather), `/newbot`, and copy the token.
2. **Anthropic API key** from <https://console.anthropic.com>.
3. **Google Calendar**:
   - In Google Cloud Console, create a project and enable the **Google Calendar API**.
   - Set up the **OAuth consent screen** (External), then **Publish app** so it is "In production".
     While the app is in *Testing*, Google expires refresh tokens after 7 days. You don't need
     verification for your own account, but you will click through an "unverified app" warning.
   - Under **Credentials**, create an **OAuth client ID** of type **Desktop app**, download it,
     and save it as `credentials.json` in the repo root.
   - Create a "Family" calendar in Google Calendar and share it with the family.
4. Run locally:
   ```bash
   python3 -m venv --without-pip .venv && curl -sS https://bootstrap.pypa.io/get-pip.py | .venv/bin/python
   .venv/bin/pip install -r requirements.txt
   .venv/bin/python scripts/google_auth.py   # open the printed URL and approve; it lists calendar IDs
   cp .env.example .env                      # fill in tokens + GOOGLE_CALENDAR_ID
   ```
5. Find each family member's Telegram user ID: run the bot, send it `/start`, and add the ID it
   replies with to `ALLOWED_TELEGRAM_USER_IDS`.

Run locally: `set -a; . ./.env; set +a; .venv/bin/python -m app.bot`

## Deploy

The bot runs on the Oracle VM (`ubuntu@130.162.197.224`) as a Docker container. It uses
long polling, so it opens no ports.

```bash
./deploy.sh --secrets   # first time, or after changing .env / re-running google_auth.py
./deploy.sh             # code changes
ssh ubuntu@130.162.197.224 'cd smart_calendar && docker compose logs -f'
```

## Using it

Commands (these work without an Anthropic key; leave `ANTHROPIC_API_KEY` empty to run in this mode):

- `/add <date> [time] <title> [@ place]`: for example `/add fri 15:30-17:00 Swimming @ Aquatic Centre`. With no
  time it's an all-day event, and without an end time it lasts an hour.
- `/list [days]`: upcoming events (14 days by default). Tap 🗑 and a number to delete one.
- `/help`: the full syntax.

With Claude switched on:

- Forward or paste a message, or send a photo or PDF of an invitation.
- **✏️ Edit**: reply in plain words ("it's 3pm not 2", "drop the hotel"), and the bot re-extracts.
- Relative dates ("this Saturday") are resolved against the forwarded message's original send time.

## Roadmap

1. ✅ Telegram bot → Claude extraction → confirm → Google Calendar
2. Gmail label polling + `.ics` attachments
3. Dedup / updates to existing events
4. WhatsApp Business Cloud API (optional), auto-add high-confidence events
