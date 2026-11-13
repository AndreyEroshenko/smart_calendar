"""Google Calendar client. Credentials come from scripts/google_auth.py (OAuth, run once locally)."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .models import Event

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
]


class Calendar:
    def __init__(self, token_path: Path, calendar_id: str):
        self._token_path = token_path
        self._calendar_id = calendar_id
        self._creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    def _service(self):
        if not self._creds.valid:
            self._creds.refresh(Request())
            self._token_path.write_text(self._creds.to_json())
        return build("calendar", "v3", credentials=self._creds, cache_discovery=False)

    def create(self, event: Event) -> dict:
        """Insert the event and return the created Google event resource (has "id" and "htmlLink")."""
        return self._service().events().insert(calendarId=self._calendar_id, body=to_body(event)).execute()

    def upcoming(self, days: int, limit: int = 30) -> list[dict]:
        """Events from now until `days` ahead, soonest first (Google event resources)."""
        now = datetime.now(timezone.utc)
        result = self._service().events().list(
            calendarId=self._calendar_id, timeMin=now.isoformat(), timeMax=(now + timedelta(days=days)).isoformat(),
            singleEvents=True, orderBy="startTime", maxResults=limit,
        ).execute()
        return result.get("items", [])

    def get(self, event_id: str) -> dict:
        return self._service().events().get(calendarId=self._calendar_id, eventId=event_id).execute()

    def delete(self, event_id: str) -> None:
        self._service().events().delete(calendarId=self._calendar_id, eventId=event_id).execute()


def to_body(event: Event) -> dict:
    start, end = event.start_value(), event.end_value()
    if event.all_day:
        # Google's all-day end date is exclusive.
        times = {"start": {"date": start.isoformat()}, "end": {"date": (end + timedelta(days=1)).isoformat()}}
    else:
        times = {
            "start": {"dateTime": start.isoformat(), "timeZone": event.timezone},
            "end": {"dateTime": end.isoformat(), "timeZone": event.timezone},
        }
    body = {"summary": event.title, **times}
    if event.location:
        body["location"] = event.location
    if event.description:
        body["description"] = event.description
    return body
