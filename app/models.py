"""Event schema shared by the extractor, the store and the calendar client."""
from datetime import date, datetime, timedelta

from pydantic import BaseModel, Field


class Event(BaseModel):
    title: str = Field(description="Short, descriptive title, e.g. 'Mia – Sophie's 7th birthday party'")
    all_day: bool = Field(description="True when no specific time is known or the event spans whole days")
    start: str = Field(
        description="Local wall-clock start in the event's timezone, no offset. "
        "'YYYY-MM-DDTHH:MM' for timed events, 'YYYY-MM-DD' for all-day events"
    )
    end: str | None = Field(
        description="Same format as start. For all-day events this is the LAST day (inclusive). "
        "Null if unknown"
    )
    timezone: str = Field(description="IANA timezone of start/end, e.g. 'Australia/Melbourne'")
    location: str | None = Field(description="Venue name and/or address, null if unknown")
    description: str | None = Field(
        description="Useful details: RSVP by/contact, what to bring, booking refs, dress code. Concise"
    )

    def start_value(self) -> date | datetime:
        return date.fromisoformat(self.start) if self.all_day else datetime.fromisoformat(self.start)

    def end_value(self) -> date | datetime:
        """End, defaulting to same day (all-day) or +1h (timed)."""
        if self.end:
            return date.fromisoformat(self.end) if self.all_day else datetime.fromisoformat(self.end)
        start = self.start_value()
        return start if self.all_day else start + timedelta(hours=1)


class Extraction(BaseModel):
    events: list[Event] = Field(description="Events found; empty if the message contains none")
    note: str | None = Field(
        description="Brief note to the user about assumptions or ambiguity (guessed year, AM/PM, "
        "missing time), or why no event was found. Null if nothing to flag"
    )
