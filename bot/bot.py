"""
Telegram bot for Musa's voice journal — with approval flow.

Flow:
1. User sends a voice note or text message
2. Bot transcribes audio (if voice) via local Whisper
3. Bot formats transcript via Claude API into structured activities
4. Bot writes/updates the daily journal .md file LOCALLY (not committed yet)
5. Bot shows a preview with an inline keyboard:
      ✅ Setujui & Push  |  ✏️ Edit  |  ❌ Batalkan
6a. Setujui  → commit + push to git
6b. Edit     → bot asks for correction text → re-process → show new preview
6c. Batalkan → revert file changes, nothing is saved
"""

import logging
import os
import tempfile
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_USER_IDS_RAW = os.getenv("ALLOWED_USER_IDS", "")
ALLOWED_USER_IDS: set[int] = (
    {int(uid.strip()) for uid in ALLOWED_USER_IDS_RAW.split(",") if uid.strip()}
    if ALLOWED_USER_IDS_RAW
    else set()
)

REPO_ROOT = os.getenv("REPO_ROOT", str(Path(__file__).parent.parent))
ACTIVITY_LOG_ROOT = os.path.join(REPO_ROOT, "Activity-Log")
# ──────────────────────────────────────────────────────────────────────────────

# Callback data constants
CB_APPROVE = "approve"
CB_CANCEL  = "cancel"
CB_EDIT    = "edit"

# User-data keys
UD_PENDING       = "pending"       # dict with pending journal state
UD_AWAITING_EDIT = "awaiting_edit" # bool: waiting for edit correction text


def _check_auth(update: Update) -> bool:
    if not ALLOWED_USER_IDS:
        return True
    return update.effective_user.id in ALLOWED_USER_IDS


def _approval_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Setujui & Push", callback_data=CB_APPROVE),
            InlineKeyboardButton("✏️ Edit",           callback_data=CB_EDIT),
            InlineKeyboardButton("❌ Batalkan",        callback_data=CB_CANCEL),
        ]
    ])


def _build_preview(data: dict) -> str:
    """Build a human-readable preview of the pending journal entry."""
    activities = data["activities"]
    focus      = data.get("focus", "")
    summary    = data.get("summary", "")
    target     = data["target_date"]

    act_lines = []
    for act in activities:
        act_lines.append(f"• *{act['name']}*")
        if act.get("description"):
            act_lines.append(f"  _{act['description']}_")
        for c in act.get("capaian", []):
            act_lines.append(f"  ✅ {c}")
        for k in act.get("kendala", []):
            act_lines.append(f"  ⚠️ {k}")

    action = "baru" if data["created_new"] else "diperbarui"
    text = (
        f"📓 *Pratinjau jurnal ({action}):*\n"
        f"📅 {target.strftime('%d %B %Y')}\n"
        f"🎯 Fokus: {focus}\n\n"
        + "\n".join(act_lines)
        + f"\n\n📋 _{summary}_"
        + "\n\n─────────────────────\n"
        "Setujui untuk push ke repo, edit untuk koreksi, atau batalkan."
    )
    return text


def _revert_changes(pending: dict) -> None:
    """Revert locally written journal files to their original state."""
    daily_path = pending.get("daily_path")
    weekly_path = pending.get("weekly_path")
    original_daily = pending.get("original_daily")
    original_weekly = pending.get("original_weekly")
    created_new = pending.get("created_new", True)

    if daily_path:
        if created_new:
            try:
                Path(daily_path).unlink(missing_ok=True)
            except Exception as e:
                logger.warning("Gagal hapus file baru: %s", e)
        elif original_daily is not None:
            try:
                Path(daily_path).write_text(original_daily, encoding="utf-8")
            except Exception as e:
                logger.warning("Gagal restore daily file: %s", e)

    if weekly_path and original_weekly is not None:
        try:
            Path(weekly_path).write_text(original_weekly, encoding="utf-8")
        except Exception as e:
            logger.warning("Gagal restore weekly readme: %s", e)


async def _write_journal(target_date: date, activities: list, focus: str, summary: str) -> dict:
    """
    Write journal files locally (no git commit yet).
    Returns a 'pending' dict that can be committed or reverted.
    """
    from journal_writer import write_journal_entry, update_weekly_readme
    from date_resolver import find_week_folder

    # Snapshot original content before overwriting
    _, week_dir = find_week_folder(ACTIVITY_LOG_ROOT, target_date)
    if week_dir is None:
        raise ValueError(
            f"Tidak ditemukan folder week untuk tanggal {target_date}. "
            "Pastikan batch sudah dibuat dengan placeholder_generator.sh."
        )

    from date_resolver import daily_filename
    daily_file = week_dir / daily_filename(target_date)
    original_daily   = daily_file.read_text(encoding="utf-8") if daily_file.exists() else None
    weekly_readme    = week_dir / "readme.md"
    original_weekly  = weekly_readme.read_text(encoding="utf-8") if weekly_readme.exists() else None

    # Write the journal entry
    daily_path, created_new = write_journal_entry(ACTIVITY_LOG_ROOT, target_date, activities)

    # Update weekly readme
    update_weekly_readme(week_dir, target_date, summary, focus)

    changed_files = [daily_path, str(weekly_readme)]

    return {
        "target_date":     target_date,
        "activities":      activities,
        "focus":           focus,
        "summary":         summary,
        "daily_path":      daily_path,
        "weekly_path":     str(weekly_readme),
        "changed_files":   changed_files,
        "created_new":     created_new,
        "original_daily":  original_daily,
        "original_weekly": original_weekly,
    }


async def _do_process(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """
    Core pipeline: text → AI format → write locally → show approval keyboard.
    Stores pending state in context.user_data[UD_PENDING].
    """
    msg = update.message or update.effective_message
    status_msg = await msg.reply_text("🤖 Memformat dengan AI...")

    try:
        from ai_formatter import format_transcript_to_activities

        data = format_transcript_to_activities(text)
        activities = data["activities"]
        focus      = data.get("focus", "")
        summary    = data.get("summary", "")

        await status_msg.edit_text("📝 Menulis draft jurnal...")
        today   = date.today()
        pending = await _write_journal(today, activities, focus, summary)
        pending["transcript"] = text

        # Save to user state
        context.user_data[UD_PENDING]       = pending
        context.user_data[UD_AWAITING_EDIT] = False

        preview = _build_preview(pending)
        await status_msg.edit_text(preview, parse_mode="Markdown", reply_markup=_approval_keyboard())

    except ValueError as e:
        logger.error("ValueError: %s", e)
        await status_msg.edit_text(f"❌ Error: {e}")
    except Exception as e:
        logger.exception("Unexpected error during processing")
        await status_msg.edit_text(
            f"❌ Terjadi kesalahan:\n`{type(e).__name__}: {e}`",
            parse_mode="Markdown",
        )


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _check_auth(update):
        await update.message.reply_text("⛔ Maaf, kamu tidak punya akses ke bot ini.")
        return

    await update.message.reply_text(
        "👋 Halo! Saya bot jurnal Musa.\n\n"
        "Kirim *voice note* atau *pesan teks* yang menceritakan kegiatan Musa hari ini.\n\n"
        "Bot akan memperlihatkan pratinjau jurnal dulu sebelum disimpan ke repo — "
        "kamu yang menentukan apakah jurnal tersebut sudah benar.\n\n"
        "Perintah:\n"
        "/start – Pesan ini\n"
        "/today – Lihat log hari ini\n"
        "/help  – Bantuan",
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _check_auth(update):
        return

    await update.message.reply_text(
        "📖 *Cara pakai:*\n\n"
        "1. Kirim voice note atau teks tentang kegiatan Musa\n"
        "2. Bot menampilkan *pratinjau* jurnal yang diformat AI\n"
        "3. Kamu memilih:\n"
        "   • ✅ *Setujui & Push* — simpan dan push ke repo\n"
        "   • ✏️ *Edit* — kirim koreksi lalu lihat pratinjau baru\n"
        "   • ❌ *Batalkan* — buang, tidak ada yang disimpan\n\n"
        "*Tips voice note yang bagus:*\n"
        "- Sebutkan nama kegiatan (cooking class, belajar matematika, dll)\n"
        "- Ceritakan apa yang dilakukan dan hasilnya\n"
        "- Boleh sebut kendala jika ada",
        parse_mode="Markdown",
    )


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _check_auth(update):
        await update.message.reply_text("⛔ Tidak punya akses.")
        return

    from date_resolver import find_week_folder, daily_filename

    today = date.today()
    _, week_dir = find_week_folder(ACTIVITY_LOG_ROOT, today)
    if week_dir is None:
        await update.message.reply_text("⚠️ Belum ada folder week untuk hari ini.")
        return

    daily_file = week_dir / daily_filename(today)
    if not daily_file.exists():
        await update.message.reply_text("📭 Belum ada log untuk hari ini.")
        return

    content = daily_file.read_text(encoding="utf-8")
    if len(content) > 3800:
        content = content[:3800] + "\n\n... _(dipotong)_"

    await update.message.reply_text(
        f"📓 *Log hari ini:*\n\n```\n{content}\n```",
        parse_mode="Markdown",
    )


# ── Message handlers ──────────────────────────────────────────────────────────

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _check_auth(update):
        await update.message.reply_text("⛔ Tidak punya akses.")
        return

    # Cancel any pending edit state
    context.user_data[UD_AWAITING_EDIT] = False

    msg   = update.message
    voice = msg.voice or msg.audio
    if voice is None:
        await msg.reply_text("⚠️ Tidak ada file audio ditemukan.")
        return

    status_msg = await msg.reply_text("🎙️ Mengunduh audio...")
    tmp_path   = None

    try:
        file   = await context.bot.get_file(voice.file_id)
        suffix = ".ogg" if msg.voice else ".mp3"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name
        await file.download_to_drive(tmp_path)

        await status_msg.edit_text("🎙️ Transkripsi audio...")
        from transcriber import transcribe_audio

        transcript = transcribe_audio(tmp_path)
        logger.info("Transcript: %s", transcript)

        await status_msg.edit_text(
            f"📝 *Transkripsi:*\n_{transcript}_\n\n⏳ Memformat...",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.exception("Audio processing error")
        await status_msg.edit_text(f"❌ Gagal transkripsi: {e}")
        return
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    # Reuse status_msg slot for the processing flow
    # We need a fresh update-like context; just pass the original update
    await _do_process(update, context, transcript)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _check_auth(update):
        await update.message.reply_text("⛔ Tidak punya akses.")
        return

    text = update.message.text.strip()
    if not text:
        return

    # ── Edit mode: user is sending a correction ──────────────────────────────
    if context.user_data.get(UD_AWAITING_EDIT):
        context.user_data[UD_AWAITING_EDIT] = False

        pending = context.user_data.get(UD_PENDING)
        if not pending:
            await update.message.reply_text(
                "⚠️ Tidak ada jurnal pending. Kirim voice note atau teks baru."
            )
            return

        # Revert previous draft before re-processing
        _revert_changes(pending)
        context.user_data.pop(UD_PENDING, None)

        # Combine original transcript + correction as new input
        original_transcript = pending.get("transcript", "")
        combined = (
            f"{original_transcript}\n\nKoreksi tambahan: {text}"
            if original_transcript
            else text
        )

        await update.message.reply_text("♻️ Memformat ulang dengan koreksi...")
        await _do_process(update, context, combined)
        return

    # ── Normal mode: new journal entry ───────────────────────────────────────
    await _do_process(update, context, text)


# ── Inline keyboard callback ──────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not _check_auth(update):
        await query.edit_message_text("⛔ Tidak punya akses.")
        return

    action  = query.data
    pending = context.user_data.get(UD_PENDING)

    if pending is None:
        await query.edit_message_text("⚠️ Sesi sudah kedaluwarsa. Kirim jurnal baru.")
        return

    # ── APPROVE ───────────────────────────────────────────────────────────────
    if action == CB_APPROVE:
        await query.edit_message_text("📤 Menyimpan dan push ke repo...")
        try:
            from git_sync import commit_and_push

            commit_ref = commit_and_push(
                REPO_ROOT,
                pending["target_date"],
                pending["changed_files"],
            )

            context.user_data.pop(UD_PENDING, None)

            action_label = "dibuat" if pending["created_new"] else "diperbarui"
            reply = (
                f"✅ *Jurnal berhasil {action_label} dan di-push!*\n\n"
                f"📅 {pending['target_date'].strftime('%d %B %Y')}\n"
                f"🎯 Fokus: {pending['focus']}\n"
                f"📋 _{pending['summary']}_"
            )
            if commit_ref and commit_ref != "Tidak ada perubahan untuk di-commit.":
                reply += f"\n\n🔀 Commit: `{commit_ref}`"

            await query.edit_message_text(reply, parse_mode="Markdown")

        except Exception as e:
            logger.exception("Error during commit/push")
            await query.edit_message_text(
                f"❌ Gagal push ke repo:\n`{type(e).__name__}: {e}`\n\n"
                "Draft lokal masih tersimpan. Coba lagi atau /cancel untuk batalkan.",
                parse_mode="Markdown",
            )

    # ── EDIT ──────────────────────────────────────────────────────────────────
    elif action == CB_EDIT:
        context.user_data[UD_AWAITING_EDIT] = True
        await query.edit_message_text(
            "✏️ *Mode edit aktif.*\n\n"
            "Kirim koreksi atau tambahan sebagai pesan teks.\n"
            "Contoh: _\"tambahkan belajar matematika 1 jam\"_ atau "
            "_\"ganti nama kegiatan pertama jadi Sains\"_\n\n"
            "Bot akan memformat ulang jurnal dengan koreksimu.",
            parse_mode="Markdown",
        )

    # ── CANCEL ────────────────────────────────────────────────────────────────
    elif action == CB_CANCEL:
        _revert_changes(pending)
        context.user_data.pop(UD_PENDING, None)
        context.user_data[UD_AWAITING_EDIT] = False

        await query.edit_message_text(
            "❌ *Jurnal dibatalkan.* Tidak ada perubahan yang disimpan.",
            parse_mode="Markdown",
        )


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CommandHandler("today",  cmd_today))

    app.add_handler(CallbackQueryHandler(handle_callback))

    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Bot started. Listening for messages...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
