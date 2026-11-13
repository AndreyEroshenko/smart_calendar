"""Telegram bot: forward it a message → it proposes calendar events → Add / Edit / Skip."""
import asyncio
import html
import logging
from datetime import date, datetime

from googleapiclient.errors import HttpError
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from . import config
from .extract import Attachment, Extractor
from .gcal import Calendar
from .models import Event, Extraction
from .quickadd import USAGE, parse_add
from .store import Store

log = logging.getLogger(__name__)

# Telegram file types we pass to Claude as-is.
SUPPORTED_DOCS = {"application/pdf", "image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_FILE_BYTES = 20 * 1024 * 1024  # Bot API download limit

COMMANDS = [
    BotCommand("add", "Add an event: /add tomorrow 11am Dentist"),
    BotCommand("list", "Upcoming events, with delete buttons (/list 30 for 30 days)"),
    BotCommand("help", "How to use the bot"),
]
LIST_DAYS = 14


class Bot:
    def __init__(self, settings: config.Settings):
        self.settings = settings
        self.store = Store(settings.db_path)
        self.extractor = Extractor(settings.claude_model, settings.timezone) if settings.claude_enabled else None
        self.calendar = Calendar(settings.google_token_path, settings.calendar_id)

    def build_app(self) -> Application:
        app = Application.builder().token(self.settings.telegram_token).post_init(_set_commands).build()
        allowed = filters.User(user_id=list(self.settings.allowed_user_ids))
        app.add_handler(CommandHandler("start", self.start))
        app.add_handler(CommandHandler("help", self.show_help, filters=allowed))
        app.add_handler(CommandHandler("add", self.add, filters=allowed))
        app.add_handler(CommandHandler("list", self.list_events, filters=allowed))
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
        await self.show_help(update, context)

    async def show_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        intro = (
            "Forward me an invitation, ticket or booking (text, photo or PDF) "
            "and I'll suggest calendar events for you to confirm. Or use the commands:"
            if self.extractor else "Commands:"
        )
        await update.message.reply_text(
            f"{intro}\n\n/add: add an event\n/list: upcoming events, tap 🗑 to delete one\n\n{USAGE}",
            parse_mode=ParseMode.HTML,
        )

    async def add(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args:
            await update.message.reply_text(USAGE, parse_mode=ParseMode.HTML)
            return
        today = datetime.now(self.settings.timezone).date()
        try:
            event = parse_add(" ".join(context.args), today, self.settings.timezone)
        except ValueError as e:
            await update.message.reply_text(f"⚠️ {html.escape(str(e))}\n\n{USAGE}", parse_mode=ParseMode.HTML)
            return
        created = await asyncio.to_thread(self.calendar.create, event)
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🗑 Delete", callback_data=f"del:{created['id']}")]])
        await update.message.reply_text(
            f'{_render_event(event)}\n\n✅ <a href="{html.escape(created["htmlLink"])}">Added to Google Calendar</a>',
            parse_mode=ParseMode.HTML, disable_web_page_preview=True, reply_markup=keyboard,
        )

    async def list_events(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        days = int(context.args[0]) if context.args and context.args[0].isdigit() else LIST_DAYS
        events = await asyncio.to_thread(self.calendar.upcoming, days)
        if not events:
            await update.message.reply_text(f"No events in the next {days} days.")
            return
        lines = [f"<b>Next {days} days</b>"]
        buttons = []
        for n, item in enumerate(events, start=1):
            lines.append(f"{n}. {html.escape(self._when_google(item))}: {html.escape(item.get('summary', '(no title)'))}")
            buttons.append(InlineKeyboardButton(f"🗑 {n}", callback_data=f"del:{item['id']}"))
        rows = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
        await update.message.reply_text(
            "\n".join(lines) + "\n\nTap a number to delete that event.",
            parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows),
        )

    def _when_google(self, item: dict) -> str:
        """Short local start time of a Google event resource, e.g. "Fri 20 Nov 11:00"."""
        start = item["start"]
        if "date" in start:
            return f"{_fmt_short(date.fromisoformat(start['date']))} (all day)"
        when = datetime.fromisoformat(start["dateTime"]).astimezone(self.settings.timezone)
        return f"{_fmt_short(when)} {when:%H:%M}"

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        context.user_data.pop("editing", None)
        await update.message.reply_text("OK, cancelled.")

    # --- incoming messages ----------------------------------------------------------------

    async def on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message
        if self.extractor is None:
            await msg.reply_text(
                "Reading forwarded messages isn't switched on yet. Use /add to add an event, or /help.",
            )
            return
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
        if action in ("del", "delok", "delno"):
            await self._on_delete_button(query, action, raw_id)
            return
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
                (await asyncio.to_thread(self.calendar.create, event))["htmlLink"]
                for event in pending.extraction.events
            ]
            self.store.set_status(pending.id, "added", links)
            added = "\n".join(f'✅ <a href="{html.escape(link)}">Open in Google Calendar</a>' for link in links)
            await query.edit_message_text(
                _render(pending.extraction) + "\n\n" + added,
                parse_mode=ParseMode.HTML, disable_web_page_preview=True,
            )

    async def _on_delete_button(self, query, action: str, event_id: str) -> None:
        """del → ask to confirm; delok → delete; delno → back off."""
        if action == "delno":
            await query.answer("Kept")
            await query.message.delete()
            return
        try:
            item = await asyncio.to_thread(self.calendar.get, event_id)
        except HttpError as e:
            if e.resp.status not in (404, 410):
                raise
            item = {"status": "cancelled"}
        if item.get("status") == "cancelled":
            await query.answer("Already deleted.")
            return
        title = html.escape(item.get("summary", "(no title)"))
        when = html.escape(self._when_google(item))
        if action == "del":
            await query.answer()
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("🗑 Yes, delete", callback_data=f"delok:{event_id}"),
                InlineKeyboardButton("Keep it", callback_data="delno:"),
            ]])
            await query.message.reply_text(
                f"Delete <b>{title}</b> ({when})?", parse_mode=ParseMode.HTML, reply_markup=keyboard
            )
        else:
            await asyncio.to_thread(self.calendar.delete, event_id)
            await query.answer("Deleted")
            await query.edit_message_text(f"🗑 Deleted <b>{title}</b> ({when}).", parse_mode=ParseMode.HTML)

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


def _fmt_short(d: date | datetime) -> str:
    return f"{d:%a} {d.day} {d:%b}"


async def _set_commands(app: Application) -> None:
    """Show the commands in Telegram's "/" menu."""
    await app.bot.set_my_commands(COMMANDS)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # don't log the bot token in request URLs
    Bot(config.load()).build_app().run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
