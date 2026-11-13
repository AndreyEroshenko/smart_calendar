"""Parse the /add command: `/add <date> [time[-time]] <title> [@ location]` → Event."""
import re
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from .models import Event

USAGE = (
    "Usage: /add &lt;date&gt; [time] &lt;title&gt; [@ place]\n\n"
    "Examples:\n"
    "<code>/add tomorrow 11am Dentist</code>\n"
    "<code>/add fri 15:30-17:00 Swimming @ Aquatic Centre</code>\n"
    "<code>/add 20 nov 6pm Sophie's birthday party</code>\n"
    "<code>/add 24/12 Christmas Eve</code>  (no time = all day)\n\n"
    "Dates: today, tomorrow, mon…sun, 20 nov, nov 20, 20/11, 20/11/2027, 2026-11-20.\n"
    "Times: 11am, 3:30pm, 15:30, ranges like 11am-12:30pm. Without an end time it lasts 1 hour."
)

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

_TIME = r"\d{1,2}(?::\d{2})?\s*(?:am|pm)?"
_TIME_RE = re.compile(rf"^(?P<start>{_TIME})(?:\s*[-–]\s*(?P<end>{_TIME}))?$", re.IGNORECASE)


def parse_add(text: str, today: date, tz: ZoneInfo) -> Event:
    """Raise ValueError with a user-facing message if the text can't be parsed."""
    text, _, location = text.partition("@")
    words = text.split()
    if not words:
        raise ValueError("Tell me the date and what the event is.")

    day, used = _parse_date(words, today)
    words = words[used:]

    times = None
    if words:
        times, used = _parse_times(words)
        words = words[used:]

    title = " ".join(words).strip()
    if not title:
        raise ValueError("The event needs a title after the date and time.")

    if times is None:
        start, end, all_day = day.isoformat(), None, True
    else:
        (sh, sm), end_time = times
        start, all_day = f"{day.isoformat()}T{sh:02d}:{sm:02d}", False
        end = None
        if end_time:
            eh, em = end_time
            end_day = day if (eh, em) > (sh, sm) else day + timedelta(days=1)  # e.g. 10pm-1am
            end = f"{end_day.isoformat()}T{eh:02d}:{em:02d}"

    return Event(
        title=title, all_day=all_day, start=start, end=end, timezone=tz.key,
        location=location.strip() or None, description=None,
    )


def _parse_date(words: list[str], today: date) -> tuple[date, int]:
    """Return the date and how many words it used."""
    first = words[0].lower()
    if first == "today":
        return today, 1
    if first == "tomorrow":
        return today + timedelta(days=1), 1
    if (weekday := _lookup(first, WEEKDAYS)) is not None:
        ahead = (weekday - today.weekday()) % 7
        return today + timedelta(days=ahead), 1

    if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", first):
        return _make_date(int(m[1]), int(m[2]), int(m[3])), 1
    if m := re.fullmatch(r"(\d{1,2})[/.](\d{1,2})(?:[/.](\d{2}|\d{4}))?", first):
        return _with_year(int(m[1]), int(m[2]), m[3], today), 1

    second = words[1].lower() if len(words) > 1 else ""
    if first.isdigit() and (month := _lookup(second, MONTHS)) is not None:  # 20 nov
        return _with_year(int(first), month + 1, None, today), 2
    if (month := _lookup(first, MONTHS)) is not None and second.isdigit():  # nov 20
        return _with_year(int(second), month + 1, None, today), 2

    raise ValueError(f"I don't understand the date “{words[0]}”.")


def _lookup(word: str, names: list[str]) -> int | None:
    """Index of the name that `word` abbreviates (at least 3 letters: "nov", "thurs"), else None."""
    if len(word) >= 3:
        for i, name in enumerate(names):
            if name.startswith(word):
                return i
    return None


def _with_year(day: int, month: int, year: str | None, today: date) -> date:
    if year:
        return _make_date(int(year) + (2000 if len(year) == 2 else 0), month, day)
    candidate = _make_date(today.year, month, day)
    return candidate if candidate >= today else _make_date(today.year + 1, month, day)


def _make_date(year: int, month: int, day: int) -> date:
    try:
        return date(year, month, day)
    except ValueError:
        raise ValueError(f"{day}/{month}/{year} isn't a valid date.") from None


def _parse_times(words: list[str]) -> tuple[tuple[tuple[int, int], tuple[int, int] | None] | None, int]:
    """Look for a time or time range in the first few words; return it and how many words it used."""
    for used in (3, 2, 1):  # "11am - 12pm", "11am -12pm", "11am-12pm"
        if len(words) < used:
            continue
        m = _TIME_RE.match(" ".join(words[:used]))
        if not m:
            continue
        start_raw, end_raw = m["start"], m["end"]
        if not _looks_like_time(start_raw) and not end_raw:
            return None, 0  # a bare number like "3" is part of the title
        end_ampm = _ampm(end_raw) if end_raw else None
        end = _to_hm(end_raw, end_ampm) if end_raw else None
        start = _to_hm(start_raw, _ampm(start_raw) or end_ampm)
        if end and end_ampm and not _ampm(start_raw) and start >= end:
            start = _to_hm(start_raw, "am" if end_ampm == "pm" else "pm")  # "11-12pm" is 11am-12pm
        return (start, end), used
    return None, 0


def _looks_like_time(raw: str) -> bool:
    return ":" in raw or _ampm(raw) is not None


def _ampm(raw: str) -> str | None:
    raw = raw.lower()
    return "am" if raw.endswith("am") else "pm" if raw.endswith("pm") else None


def _to_hm(raw: str, ampm: str | None) -> tuple[int, int]:
    digits = re.sub(r"[^\d:]", "", raw)
    hour, _, minute = digits.partition(":")
    h, m = int(hour), int(minute or 0)
    if ampm:
        if not 1 <= h <= 12:
            raise ValueError(f"“{raw}” isn't a valid time.")
        h = h % 12 + (12 if ampm == "pm" else 0)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"“{raw}” isn't a valid time.")
    return h, m
