"""Turn a forwarded message (text, images, PDFs) into calendar events with Claude."""
import base64
import logging
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import anthropic

from .models import Extraction

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You extract calendar events for a family's shared Google Calendar. Family members forward you \
messages from email, WhatsApp, Telegram etc.: party invitations, concert and event tickets, \
travel bookings, school and club notices, appointment confirmations.

The family's home timezone is {tz}. Right now it is {now}.
{sent_line}
Guidelines:
- Resolve relative dates ("this Saturday", "tomorrow", "the 5th") against the time the message \
was originally sent. If a year is missing, pick the next upcoming occurrence.
- Create one event per distinct occasion. For travel, create one event per flight/train/ferry \
leg (title like "Flight QF401 MEL → SYD", times in the departure city's timezone; put the \
arrival time and booking reference in the description) and one all-day event spanning a hotel \
or accommodation stay.
- If no time is given, make it an all-day event. If no end time is given, leave end null.
- Use the venue's timezone if it is clearly elsewhere; otherwise use the home timezone.
- Titles should make sense at a glance on a shared family calendar; mention whose event it is \
when the message makes that clear.
- If the message contains no event (or only a past one that is clearly over), return no events \
and say why in the note.
- When you had to guess something important (AM/PM, year, which date), make your best guess and \
say so in the note."""


@dataclass
class Attachment:
    media_type: str  # image/jpeg, image/png, application/pdf, ...
    data: bytes


class Extractor:
    def __init__(self, model: str, timezone: ZoneInfo):
        self._client = anthropic.AsyncAnthropic()
        self._model = model
        self._tz = timezone

    async def extract(
        self,
        text: str | None,
        attachments: list[Attachment] = (),
        sent_at: datetime | None = None,
    ) -> Extraction:
        content: list[dict] = [_attachment_block(a) for a in attachments]
        content.append({"type": "text", "text": text or "(no text, see attachment)"})
        return await self._run(content, sent_at)

    async def revise(self, previous: Extraction, source_text: str | None, correction: str) -> Extraction:
        """Apply a user's free-text correction ("it's at 3pm, not 2") to an earlier extraction."""
        content = [{
            "type": "text",
            "text": f"Original message:\n{source_text or '(attachment only)'}\n\n"
            f"Events you extracted:\n{previous.model_dump_json(indent=2)}\n\n"
            f"The user says: {correction}\n\n"
            "Return the full corrected list of events.",
        }]
        return await self._run(content, None)

    async def _run(self, content: list[dict], sent_at: datetime | None) -> Extraction:
        now = datetime.now(self._tz)
        sent_line = (
            f"The forwarded message was originally sent at {sent_at.astimezone(self._tz):%A %d %B %Y, %H:%M}.\n"
            if sent_at else ""
        )
        system = SYSTEM_PROMPT.format(tz=self._tz.key, now=f"{now:%A %d %B %Y, %H:%M}", sent_line=sent_line)

        response = await self._client.beta.messages.parse(
            model=self._model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            # On a policy decline, the API retries on a fallback model within the same call.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=system,
            messages=[{"role": "user", "content": content}],
            output_format=Extraction,
        )
        log.info("claude usage: %s", response.usage)
        if response.stop_reason == "refusal" or response.parsed_output is None:
            return Extraction(events=[], note=f"Couldn't process this message ({response.stop_reason}).")
        return response.parsed_output


def _attachment_block(a: Attachment) -> dict:
    kind = "document" if a.media_type == "application/pdf" else "image"
    return {
        "type": kind,
        "source": {"type": "base64", "media_type": a.media_type, "data": base64.b64encode(a.data).decode()},
    }
