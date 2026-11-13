"""One-time Google OAuth: run locally, writes data/google_token.json and lists your calendars.

Needs credentials.json (OAuth client ID of type "Desktop app") in the repo root.
    .venv/bin/python scripts/google_auth.py
"""
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.gcal import SCOPES  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TOKEN = ROOT / "data" / "google_token.json"

flow = InstalledAppFlow.from_client_secrets_file(str(ROOT / "credentials.json"), SCOPES)
creds = flow.run_local_server(port=8765, open_browser=False)
TOKEN.parent.mkdir(exist_ok=True)
TOKEN.write_text(creds.to_json())
print(f"\nSaved {TOKEN}\n\nYour calendars (put the ID of the target one in GOOGLE_CALENDAR_ID):")

service = build("calendar", "v3", credentials=creds, cache_discovery=False)
for cal in service.calendarList().list().execute()["items"]:
    print(f"  {cal['id']:60}  {cal['summary']}  [{cal['accessRole']}]")
