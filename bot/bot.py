"""
Telegram bot for Musa's voice journal.

Flow:
1. User sends a voice note (or text message)
2. Bot transcribes audio via Whisper API
3. Bot formats transcript via Claude API into structured activities
4. Bot writes/updates the daily journal .md file
5. Bot updates the weekly readme.md summary
6. Bot commits & pushes changes to git
7. Bot replies with a preview of the journal entry
"""

import logging
import os
import tempfile
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
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

# Path to the root of the musa git repository
REPO_ROOT = os.getenv("REPO_ROOT", str(Path(__file__).parent.parent))
ACTIVITY_LOG_ROOT = os.path.join(REPO_ROOT, "Activity-Log")

AUTO_PUSH = os.getenv("AUTO_PUSH", "true").lower() == "true"
# ──────────────────────────────────────────────────────────────────────────────


def _check_auth(update: Update) -> bool:
    if not ALLOWED_USER_IDS:
        return True  # No restriction configured
    return update.effective_user.id in ALLOWED_USER_IDS


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _check_auth(update):
        await update.message.reply_text("⛔ Maaf, kamu tidak punya akses ke bot ini.")
        return

    await update.message.reply_text(
        "👋 Halo! Saya bot jurnal Musa.\n\n"
        "Kirim *voice note* (atau pesan teks) yang menceritakan kegiatan Musa hari ini, "
        "dan saya akan otomatis membuat catatan jurnal di repo.\n\n"
        "Perintah tersedia:\n"
        "/start – Tampilkan pesan ini\n"
        "/today – Tampilkan isi log hari ini\n"
        "/help – Bantuan",
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _check_auth(update):
        return

    await update.message.reply_text(
        "📖 *Cara pakai:*\n\n"
        "1. Kirim voice note yang menceritakan kegiatan Musa hari ini\n"
        "2. Bot akan transkripsi, format, dan simpan ke jurnal secara otomatis\n"
        "3. Perubahan langsung di-commit ke repo git\n\n"
        "*Tips voice note yang bagus:*\n"
        "- Sebutkan nama kegiatan (mis: cooking class, belajar matematika)\n"
        "- Ceritakan apa yang dilakukan dan hasilnya\n"
        "- Boleh sebut kendala atau tantangan\n\n"
        "Kamu juga bisa kirim pesan *teks* biasa jika tidak mau rekam suara.",
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
        await update.message.reply_text(
            "⚠️ Belum ada folder week untuk hari ini. "
            "Pastikan batch sudah dibuat dengan `placeholder_generator.sh`."
        )
        return

    from date_resolver import daily_filename as df
    daily_file = week_dir / df(today)
    if not daily_file.exists():
        await update.message.reply_text("📭 Belum ada log untuk hari ini.")
        return

    content = daily_file.read_text(encoding="utf-8")
    # Telegram message limit is 4096 chars
    if len(content) > 3800:
        content = content[:3800] + "\n\n... _(dipotong)_"

    await update.message.reply_text(
        f"📓 *Log hari ini:*\n\n```\n{content}\n```",
        parse_mode="Markdown",
    )


async def _process_text(update: Update, text: str) -> None:
    """Core processing: format text → write journal → git push → reply."""
    msg = update.message

    status_msg = await msg.reply_text("⏳ Memproses catatan...")

    try:
        # Step 1: Format with Claude
        await status_msg.edit_text("🤖 Memformat dengan AI...")
        from ai_formatter import format_transcript_to_activities

        data = format_transcript_to_activities(text)
        activities = data["activities"]
        focus = data.get("focus", "")
        summary = data.get("summary", "")

        # Step 2: Write journal
        await status_msg.edit_text("📝 Menulis jurnal...")
        from journal_writer import write_journal_entry, update_weekly_readme
        from date_resolver import find_week_folder

        today = date.today()
        daily_path, created_new = write_journal_entry(
            ACTIVITY_LOG_ROOT, today, activities
        )

        # Step 3: Update weekly readme
        _, week_dir = find_week_folder(ACTIVITY_LOG_ROOT, today)
        changed_files = [daily_path]
        if week_dir:
            update_weekly_readme(week_dir, today, summary, focus)
            changed_files.append(str(week_dir / "readme.md"))

        # Step 4: Git commit & push
        commit_ref = "—"
        if AUTO_PUSH:
            await status_msg.edit_text("📤 Menyimpan ke repo...")
            from git_sync import commit_and_push

            commit_ref = commit_and_push(REPO_ROOT, today, changed_files)

        # Step 5: Build reply preview
        act_lines = []
        for act in activities:
            act_lines.append(f"• *{act['name']}*")
            if act.get("description"):
                act_lines.append(f"  _{act['description']}_")
            for c in act.get("capaian", []):
                act_lines.append(f"  ✅ {c}")
            for k in act.get("kendala", []):
                act_lines.append(f"  ⚠️ {k}")

        action = "dibuat" if created_new else "diperbarui"
        reply = (
            f"✅ *Jurnal {action}!*\n\n"
            f"📅 {today.strftime('%d %B %Y')}\n"
            f"🎯 Fokus: {focus}\n\n"
            + "\n".join(act_lines)
            + f"\n\n📋 _{summary}_"
        )
        if AUTO_PUSH and commit_ref not in ("—", "Tidak ada perubahan untuk di-commit."):
            reply += f"\n\n🔀 Commit: `{commit_ref}`"

        await status_msg.edit_text(reply, parse_mode="Markdown")

    except ValueError as e:
        logger.error("ValueError: %s", e)
        await status_msg.edit_text(f"❌ Error: {e}")
    except Exception as e:
        logger.exception("Unexpected error")
        await status_msg.edit_text(
            f"❌ Terjadi kesalahan:\n`{type(e).__name__}: {e}`",
            parse_mode="Markdown",
        )


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _check_auth(update):
        await update.message.reply_text("⛔ Tidak punya akses.")
        return

    msg = update.message
    voice = msg.voice or msg.audio

    if voice is None:
        await msg.reply_text("⚠️ Tidak ada file audio ditemukan.")
        return

    status_msg = await msg.reply_text("🎙️ Mengunduh audio...")

    try:
        # Download voice note to temp file
        file = await context.bot.get_file(voice.file_id)
        suffix = ".ogg" if msg.voice else ".mp3"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name

        await file.download_to_drive(tmp_path)

        # Transcribe
        await status_msg.edit_text("🎙️ Transkripsi audio...")
        from transcriber import transcribe_audio

        transcript = transcribe_audio(tmp_path)
        logger.info("Transcript: %s", transcript)

        # Show transcript to user
        await status_msg.edit_text(
            f"📝 *Transkripsi:*\n_{transcript}_\n\n⏳ Memproses...",
            parse_mode="Markdown",
        )

    except Exception as e:
        logger.exception("Audio processing error")
        await status_msg.edit_text(f"❌ Gagal transkripsi audio: {e}")
        return
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    await _process_text(update, transcript)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _check_auth(update):
        await update.message.reply_text("⛔ Tidak punya akses.")
        return

    text = update.message.text.strip()
    if not text:
        return

    await _process_text(update, text)


def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("today", cmd_today))

    # Voice notes and audio files
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))

    # Plain text messages (excluding commands)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Bot started. Listening for messages...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
