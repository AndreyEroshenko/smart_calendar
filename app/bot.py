"""Telegram bot: forward it a message → it proposes calendar events → Add / Edit / Skip."""
import asyncio
import html
import logging
from datetime import date, datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from . import config
from .extract import Attachment, Extractor
from .gcal import Calendar
from .models import Event, Extraction
from .store import Store

log = logging.getLogger(__name__)

# Telegram file types we pass to Claude as-is.
SUPPORTED_DOCS = {"application/pdf", "image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_FILE_BYTES = 20 * 1024 * 1024  # Bot API download limit


class Bot:
    def __init__(self, settings: config.Settings):
        self.settings = settings
        self.store = Store(settings.db_path)
        self.extractor = Extractor(settings.claude_model, settings.timezone)
        self.calendar = Calendar(settings.google_token_path, settings.calendar_id)

    def build_app(self) -> Application:
        app = Application.builder().token(self.settings.telegram_token).build()
        allowed = filters.User(user_id=list(self.settings.allowed_user_ids))
        app.add_handler(CommandHandler("start", self.start))
        app.add_handler(CommandHandler("cancel", self.cancel, filters=allowed))
        app.add_handler(MessageHandler(
            allowed & ~filters.COMMAND & (filters.TEXT | filters.PHOTO | filters.Document.ALL), self.on_message
        ))
        app.add_handler(CallbackQueryHandler(self.on_button))
        app.add_error_handler(self.on_error)
        return app

    # --- commands -------------------------------------------------------------------------

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if user.id not in self.settings.allowed_user_ids:
            await update.message.reply_text(
                f"Hi! Your Telegram user ID is {user.id}. Ask the admin to add it to ALLOWED_TELEGRAM_USER_IDS."
            )
            return
        await update.message.reply_text(
            "Forward me an invitation, ticket or booking (text, photo or PDF) "
            "and I'll suggest calendar events for you to confirm."
        )

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        context.user_data.pop("editing", None)
        await update.message.reply_text("OK, cancelled.")

    # --- incoming messages ----------------------------------------------------------------

    async def on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message
        editing = context.user_data.pop("editing", None)
        if editing and msg.text and not msg.forward_origin:
            await self._apply_correction(msg, editing, msg.text)
            return

        attachments = await _download_attachments(msg)
        text = msg.text or msg.caption
        if not text and not attachments:
            await msg.reply_text("I can read text, photos and PDFs. That file type isn't supported yet.")
            return

        status = await msg.reply_text("⏳ Reading…")
        await msg.chat.send_action(ChatAction.TYPING)
        sent_at = msg.forward_origin.date if msg.forward_origin else msg.date
        extraction = await self.extractor.extract(text, attachments, sent_at=sent_at)
        pending_id = self.store.add(msg.chat_id, msg.from_user.id, text, extraction)
        await _show(status, pending_id, extraction)

    async def _apply_correction(self, msg: Message, pending_id: int, correction: str) -> None:
        pending = self.store.get(pending_id)
        if pending is None or pending.status != "pending":
            await msg.reply_text("That suggestion is no longer open.")
            return
        status = await msg.reply_text("⏳ Updating…")
        extraction = await self.extractor.revise(pending.extraction, pending.source_text, correction)
        self.store.update_extraction(pending_id, extraction)
        await _show(status, pending_id, extraction)

    # --- buttons --------------------------------------------------------------------------

    async def on_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query.from_user.id not in self.settings.allowed_user_ids:
            await query.answer("Not allowed.")
            return
        action, _, raw_id = query.data.partition(":")
        pending = self.store.get(int(raw_id))
        if pending is None or pending.status != "pending":
            await query.answer("Already handled.")
            await query.edit_message_reply_markup(None)
            return

        if action == "skip":
            self.store.set_status(pending.id, "skipped")
            await query.answer("Skipped")
            await query.edit_message_text(
                _render(pending.extraction) + "\n\n<i>Skipped.</i>", parse_mode=ParseMode.HTML
            )
        elif action == "edit":
            context.user_data["editing"] = pending.id
            await query.answer()
            await query.message.reply_text(
                "What should I change? e.g. “it starts at 3pm” or “only the first event”. /cancel to stop."
            )
        elif action == "add":
            await query.answer("Adding…")
            links = [
                await asyncio.to_thread(self.calendar.create, event) for event in pending.extraction.events
            ]
            self.store.set_status(pending.id, "added", links)
            added = "\n".join(f'✅ <a href="{html.escape(link)}">Open in Google Calendar</a>' for link in links)
            await query.edit_message_text(
                _render(pending.extraction) + "\n\n" + added,
                parse_mode=ParseMode.HTML, disable_web_page_preview=True,
            )

    async def on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        log.exception("handler error", exc_info=context.error)
        if isinstance(update, Update) and update.effective_chat:
            await update.effective_chat.send_message(f"⚠️ Something went wrong: {context.error}")


# --- helpers ------------------------------------------------------------------------------

async def _download_attachments(msg: Message) -> list[Attachment]:
    if msg.photo:
        photo = msg.photo[-1]  # largest size
        data = await (await photo.get_file()).download_as_bytearray()
        return [Attachment("image/jpeg", bytes(data))]
    doc = msg.document
    if doc and doc.mime_type in SUPPORTED_DOCS and (doc.file_size or 0) <= MAX_FILE_BYTES:
        data = await (await doc.get_file()).download_as_bytearray()
        return [Attachment(doc.mime_type, bytes(data))]
    return []


async def _show(status: Message, pending_id: int, extraction: Extraction) -> None:
    """Replace the "Reading…" message with the proposal and its buttons."""
    if not extraction.events:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("✏️ Edit", callback_data=f"edit:{pending_id}")]])
    else:
        n = len(extraction.events)
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Add" if n == 1 else f"✅ Add all {n}", callback_data=f"add:{pending_id}"),
            InlineKeyboardButton("✏️ Edit", callback_data=f"edit:{pending_id}"),
            InlineKeyboardButton("✖️ Skip", callback_data=f"skip:{pending_id}"),
        ]])
    await status.edit_text(_render(extraction), parse_mode=ParseMode.HTML, reply_markup=keyboard)


def _render(extraction: Extraction) -> str:
    parts = [_render_event(e) for e in extraction.events] or ["🤷 No events found."]
    if extraction.note:
        parts.append(f"ℹ️ <i>{html.escape(extraction.note)}</i>")
    return "\n\n".join(parts)


def _render_event(event: Event) -> str:
    lines = [f"📅 <b>{html.escape(event.title)}</b>", f"🕒 {html.escape(_when(event))}"]
    if event.location:
        lines.append(f"📍 {html.escape(event.location)}")
    if event.description:
        lines.append(f"📝 {html.escape(event.description)}")
    return "\n".join(lines)


def _when(event: Event) -> str:
    start, end = event.start_value(), event.end_value()
    if event.all_day:
        days = _fmt_date(start) if end == start else f"{_fmt_date(start)} – {_fmt_date(end)}"
        return f"{days} (all day)"
    text = f"{_fmt_date(start)}, {start:%H:%M}"
    if event.end:
        text += f"–{end:%H:%M}" if end.date() == start.date() else f" – {_fmt_date(end)}, {end:%H:%M}"
    return f"{text} ({event.timezone})"


def _fmt_date(d: date | datetime) -> str:
    return f"{d:%a} {d.day} {d:%b %Y}"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # don't log the bot token in request URLs
    Bot(config.load()).build_app().run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
