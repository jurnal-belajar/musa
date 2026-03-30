"""
Telegram bot untuk jurnal harian — voice note, teks, dan foto.

Flow:
1. Kirim voice note atau teks → transkripsi (jika audio) → format via Claude AI
2. Bot tampilkan pratinjau + inline keyboard (Setujui / Edit / Batalkan)
3. Kirim foto kapan saja saat ada pending journal → foto masuk ke img/, preview diperbarui
4. ✅ Setujui & Push  → commit semua file (teks + foto) ke git
5. ✏️ Edit            → kirim koreksi teks, bot format ulang
6. ❌ Batalkan        → revert semua perubahan lokal
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
    if ALLOWED_USER_IDS_RAW else set()
)

# Nama anak pemilik jurnal ini, misal "Musa" atau "Aasiyah"
BOT_NAME = os.getenv("BOT_NAME", "Musa")

# Path ke root repo jurnal (satu level di atas folder bot/ secara default)
REPO_ROOT          = os.getenv("REPO_ROOT", str(Path(__file__).parent.parent))
ACTIVITY_LOG_ROOT  = os.path.join(REPO_ROOT, "Activity-Log")
# ──────────────────────────────────────────────────────────────────────────────

CB_APPROVE = "approve"
CB_CANCEL  = "cancel"
CB_EDIT    = "edit"

UD_PENDING       = "pending"
UD_AWAITING_EDIT = "awaiting_edit"


def _check_auth(update: Update) -> bool:
    if not ALLOWED_USER_IDS:
        return True
    return update.effective_user.id in ALLOWED_USER_IDS


def _approval_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Setujui & Push", callback_data=CB_APPROVE),
        InlineKeyboardButton("✏️ Edit",           callback_data=CB_EDIT),
        InlineKeyboardButton("❌ Batalkan",        callback_data=CB_CANCEL),
    ]])


def _build_preview(data: dict) -> str:
    activities  = data["activities"]
    focus       = data.get("focus", "")
    summary     = data.get("summary", "")
    target      = data["target_date"]
    photos      = data.get("photos", [])

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
        f"📓 *Pratinjau jurnal {BOT_NAME} ({action}):*\n"
        f"📅 {target.strftime('%d %B %Y')}\n"
        f"🎯 Fokus: {focus}\n\n"
        + "\n".join(act_lines)
        + f"\n\n📋 _{summary}_"
    )

    if photos:
        text += f"\n\n📸 *Foto terlampir:* {len(photos)} gambar"
    else:
        text += "\n\n📸 _Belum ada foto. Kirim foto sebelum approve jika perlu._"

    text += (
        "\n\n─────────────────────\n"
        "Setujui untuk push, edit untuk koreksi, atau batalkan."
    )
    return text


def _revert_changes(pending: dict) -> None:
    """Kembalikan semua file lokal ke kondisi semula."""
    daily_path      = pending.get("daily_path")
    weekly_path     = pending.get("weekly_path")
    original_daily  = pending.get("original_daily")
    original_weekly = pending.get("original_weekly")
    created_new     = pending.get("created_new", True)

    if daily_path:
        p = Path(daily_path)
        if created_new:
            p.unlink(missing_ok=True)
        elif original_daily is not None:
            try:
                p.write_text(original_daily, encoding="utf-8")
            except Exception as e:
                logger.warning("Gagal restore daily: %s", e)

    if weekly_path and original_weekly is not None:
        try:
            Path(weekly_path).write_text(original_weekly, encoding="utf-8")
        except Exception as e:
            logger.warning("Gagal restore weekly: %s", e)

    # Hapus foto yang sudah disimpan
    for photo_path in pending.get("photos", []):
        try:
            Path(photo_path).unlink(missing_ok=True)
        except Exception as e:
            logger.warning("Gagal hapus foto: %s", e)


async def _write_journal(
    target_date: date,
    activities: list,
    focus: str,
    summary: str,
) -> dict:
    """Tulis file jurnal lokal (belum di-commit). Kembalikan dict pending."""
    from journal_writer import write_journal_entry, update_weekly_readme
    from date_resolver import find_week_folder, daily_filename

    _, week_dir = find_week_folder(ACTIVITY_LOG_ROOT, target_date)
    if week_dir is None:
        raise ValueError(
            f"Tidak ditemukan folder week untuk tanggal {target_date}. "
            "Pastikan batch sudah dibuat dengan placeholder_generator.sh."
        )

    # Snapshot original sebelum ditulis
    daily_file      = week_dir / daily_filename(target_date)
    original_daily  = daily_file.read_text(encoding="utf-8") if daily_file.exists() else None
    weekly_readme   = week_dir / "readme.md"
    original_weekly = weekly_readme.read_text(encoding="utf-8") if weekly_readme.exists() else None

    daily_path, created_new = write_journal_entry(ACTIVITY_LOG_ROOT, target_date, activities)
    update_weekly_readme(week_dir, target_date, summary, focus)

    return {
        "target_date":     target_date,
        "activities":      activities,
        "focus":           focus,
        "summary":         summary,
        "week_dir":        week_dir,
        "daily_path":      daily_path,
        "weekly_path":     str(weekly_readme),
        "changed_files":   [daily_path, str(weekly_readme)],
        "created_new":     created_new,
        "original_daily":  original_daily,
        "original_weekly": original_weekly,
        "photos":          [],   # diisi saat user kirim foto
    }


async def _do_process(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> None:
    """Pipeline: teks → AI format → tulis lokal → tampilkan preview + keyboard."""
    msg        = update.message or update.effective_message
    status_msg = await msg.reply_text("🤖 Memformat dengan AI...")

    try:
        from ai_formatter import format_transcript_to_activities

        data       = format_transcript_to_activities(text)
        activities = data["activities"]
        focus      = data.get("focus", "")
        summary    = data.get("summary", "")

        await status_msg.edit_text("📝 Menulis draft jurnal...")
        today   = date.today()
        pending = await _write_journal(today, activities, focus, summary)
        pending["transcript"] = text

        context.user_data[UD_PENDING]       = pending
        context.user_data[UD_AWAITING_EDIT] = False

        await status_msg.edit_text(
            _build_preview(pending),
            parse_mode="Markdown",
            reply_markup=_approval_keyboard(),
        )

    except ValueError as e:
        logger.error("ValueError: %s", e)
        await status_msg.edit_text(f"❌ Error: {e}")
    except Exception as e:
        logger.exception("Unexpected error")
        await status_msg.edit_text(
            f"❌ Terjadi kesalahan:\n`{type(e).__name__}: {e}`",
            parse_mode="Markdown",
        )


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _check_auth(update):
        await update.message.reply_text("⛔ Tidak punya akses.")
        return

    await update.message.reply_text(
        f"👋 Halo! Saya bot jurnal *{BOT_NAME}*.\n\n"
        "Kirim *voice note* atau *teks* tentang kegiatan hari ini.\n"
        "Setelah muncul pratinjau, kamu bisa kirim *foto* sebelum approve.\n\n"
        "/today – Lihat log hari ini\n"
        "/help  – Bantuan",
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _check_auth(update):
        return

    await update.message.reply_text(
        "📖 *Cara pakai:*\n\n"
        "1. Kirim voice note atau teks tentang kegiatan\n"
        "2. Bot tampilkan pratinjau jurnal\n"
        "3. Kirim foto (opsional) — langsung kirim saja, bot otomatis menyimpannya\n"
        "4. Pilih:\n"
        "   • ✅ *Setujui & Push* — simpan semua ke repo\n"
        "   • ✏️ *Edit* — kirim koreksi, bot format ulang\n"
        "   • ❌ *Batalkan* — buang semua, tidak ada yang disimpan\n\n"
        "📸 *Tips foto:*\n"
        "Kirim foto kapan saja setelah ada pratinjau muncul.\n"
        "Boleh kirim beberapa foto sekaligus atau satu per satu.\n"
        "Preview akan diperbarui otomatis setiap ada foto baru.",
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
        f"📓 *Log hari ini ({BOT_NAME}):*\n\n```\n{content}\n```",
        parse_mode="Markdown",
    )


# ── Message handlers ──────────────────────────────────────────────────────────

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _check_auth(update):
        await update.message.reply_text("⛔ Tidak punya akses.")
        return

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
        logger.exception("Audio error")
        await status_msg.edit_text(f"❌ Gagal transkripsi: {e}")
        return
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    await _do_process(update, context, transcript)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _check_auth(update):
        await update.message.reply_text("⛔ Tidak punya akses.")
        return

    text = update.message.text.strip()
    if not text:
        return

    # ── Mode edit: koreksi dari user ─────────────────────────────────────────
    if context.user_data.get(UD_AWAITING_EDIT):
        context.user_data[UD_AWAITING_EDIT] = False
        pending = context.user_data.get(UD_PENDING)
        if not pending:
            await update.message.reply_text("⚠️ Tidak ada jurnal pending. Kirim voice note atau teks baru.")
            return

        _revert_changes(pending)
        context.user_data.pop(UD_PENDING, None)

        original = pending.get("transcript", "")
        combined = f"{original}\n\nKoreksi: {text}" if original else text

        await update.message.reply_text("♻️ Memformat ulang dengan koreksi...")
        await _do_process(update, context, combined)
        return

    # ── Mode normal: jurnal baru ──────────────────────────────────────────────
    await _do_process(update, context, text)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Terima foto dan simpan ke img/ pada pending journal.
    Bisa menerima foto tunggal maupun album (media group).
    """
    if not _check_auth(update):
        await update.message.reply_text("⛔ Tidak punya akses.")
        return

    pending = context.user_data.get(UD_PENDING)
    if not pending:
        await update.message.reply_text(
            "📸 Foto diterima, tapi belum ada jurnal aktif.\n"
            "Kirim dulu voice note atau teks tentang kegiatan hari ini."
        )
        return

    msg = update.message
    # Ambil resolusi tertinggi (elemen terakhir di list photo)
    photo = msg.photo[-1] if msg.photo else None
    if photo is None:
        await msg.reply_text("⚠️ Tidak bisa membaca foto.")
        return

    try:
        file       = await context.bot.get_file(photo.file_id)
        photo_data = await file.download_as_bytearray()

        from journal_writer import save_photo, update_photo_section
        from date_resolver import find_week_folder

        target_date = pending["target_date"]
        week_dir    = pending["week_dir"]

        rel_path = save_photo(week_dir, target_date, bytes(photo_data), ext="jpg")
        abs_path = str(week_dir / rel_path)

        # Tambahkan ke daftar foto di pending
        pending["photos"].append(abs_path)
        if abs_path not in pending["changed_files"]:
            pending["changed_files"].append(abs_path)

        # Update bagian dokumentasi di daily .md
        from date_resolver import daily_filename
        daily_file = week_dir / daily_filename(target_date)
        all_rel_paths = [
            str(Path(p).relative_to(week_dir)) for p in pending["photos"]
        ]
        update_photo_section(daily_file, all_rel_paths)

        # Perbarui preview dengan jumlah foto terkini
        # Cari pesan preview sebelumnya (yang memiliki keyboard) dan edit
        photo_count = len(pending["photos"])
        await msg.reply_text(
            f"📸 Foto #{photo_count} tersimpan. "
            f"Total: {photo_count} foto.\n"
            "_Kirim foto lagi atau tap ✅ Setujui untuk push._",
            parse_mode="Markdown",
        )

    except Exception as e:
        logger.exception("Error menyimpan foto")
        await msg.reply_text(f"❌ Gagal menyimpan foto: {e}")


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
        photo_count = len(pending.get("photos", []))
        status_text = "📤 Menyimpan dan push ke repo"
        if photo_count:
            status_text += f" ({photo_count} foto)"
        status_text += "..."
        await query.edit_message_text(status_text)

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
                f"✅ *Jurnal {BOT_NAME} berhasil {action_label} dan di-push!*\n\n"
                f"📅 {pending['target_date'].strftime('%d %B %Y')}\n"
                f"🎯 Fokus: {pending['focus']}\n"
                f"📋 _{pending['summary']}_"
            )
            if photo_count:
                reply += f"\n📸 {photo_count} foto dokumentasi"
            if commit_ref and commit_ref != "Tidak ada perubahan untuk di-commit.":
                reply += f"\n\n🔀 Commit: `{commit_ref}`"

            await query.edit_message_text(reply, parse_mode="Markdown")

        except Exception as e:
            logger.exception("Error saat commit/push")
            await query.edit_message_text(
                f"❌ Gagal push:\n`{type(e).__name__}: {e}`\n\n"
                "Draft lokal masih ada. Coba lagi atau batalkan.",
                parse_mode="Markdown",
            )

    # ── EDIT ──────────────────────────────────────────────────────────────────
    elif action == CB_EDIT:
        context.user_data[UD_AWAITING_EDIT] = True
        await query.edit_message_text(
            "✏️ *Mode edit aktif.*\n\n"
            "Kirim koreksi atau tambahan sebagai pesan teks.\n"
            "Contoh:\n"
            "• _\"tambahkan belajar matematika 1 jam\"_\n"
            "• _\"ganti nama kegiatan pertama jadi Sains\"_\n\n"
            "⚠️ Foto yang sudah dikirim akan ikut terhapus saat edit. "
            "Kirim ulang foto setelah pratinjau baru muncul.",
            parse_mode="Markdown",
        )

    # ── CANCEL ────────────────────────────────────────────────────────────────
    elif action == CB_CANCEL:
        photo_count = len(pending.get("photos", []))
        _revert_changes(pending)
        context.user_data.pop(UD_PENDING, None)
        context.user_data[UD_AWAITING_EDIT] = False

        msg = "❌ *Jurnal dibatalkan.* Tidak ada yang disimpan."
        if photo_count:
            msg += f"\n_(termasuk {photo_count} foto yang sudah dikirim)_"
        await query.edit_message_text(msg, parse_mode="Markdown")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CommandHandler("today", cmd_today))

    app.add_handler(CallbackQueryHandler(handle_callback))

    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Bot jurnal %s dimulai.", BOT_NAME)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
