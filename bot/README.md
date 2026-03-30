# Musa Voice Journal Bot

Telegram bot yang menerima voice note dan otomatis membuat catatan jurnal harian Musa.

## Cara Kerja

```
Voice Note → Whisper (transkripsi) → Claude AI (format) → .md file → git commit & push
```

1. Kirim voice note ke bot → Whisper API transkripsi audio ke teks
2. Claude AI memformat teks menjadi struktur jurnal (kegiatan, capaian, kendala)
3. Bot menulis/update file harian `DDbulanYYYY.md` di folder week yang sesuai
4. Bot update ringkasan di `readme.md` mingguan
5. Bot commit & push otomatis ke repo

## Setup

### 1. Buat Bot Telegram
- Chat ke [@BotFather](https://t.me/BotFather)
- Jalankan `/newbot` dan ikuti instruksinya
- Salin **Bot Token** yang diberikan

### 2. Dapatkan API Keys
- **OpenAI API Key**: [platform.openai.com](https://platform.openai.com)
- **Anthropic API Key**: [console.anthropic.com](https://console.anthropic.com)

### 3. Install Dependencies
```bash
cd bot/
pip install -r requirements.txt
```

### 4. Konfigurasi Environment
```bash
cp .env.example .env
# Edit .env dan isi semua nilai yang diperlukan
```

Isi `.env`:
```env
TELEGRAM_BOT_TOKEN=...
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
ALLOWED_USER_IDS=123456789   # Telegram user ID kamu
AUTO_PUSH=true
```

> Untuk mengetahui Telegram user ID kamu, chat ke [@userinfobot](https://t.me/userinfobot)

### 5. Jalankan Bot
```bash
cd bot/
python bot.py
```

## Perintah Bot

| Perintah | Fungsi |
|----------|--------|
| `/start` | Pesan sambutan dan cara pakai |
| `/help`  | Panduan lengkap |
| `/today` | Tampilkan log harian hari ini |

## Format Voice Note yang Bagus

Ceritakan saja dengan natural, misalnya:
> "Hari ini Musa belajar memasak yakitori bareng instruktur. Berhasil membuat yakitori yang enak. Terus habis itu melukis macan tutul pakai cat air."

Bot akan otomatis:
- Memisahkan jadi 2 kegiatan: Cooking Class dan Melukis
- Mengidentifikasi capaian dari masing-masing kegiatan
- Memformat ke struktur jurnal standar

## Struktur File yang Dibuat

Bot akan menulis/update file berikut:
```
Activity-Log/2025-2026/
└── {batch}/
    └── {week}/
        ├── DDbulanYYYY.md   ← daily log (dibuat/diupdate)
        └── readme.md         ← weekly summary (diupdate)
```

## Menjalankan Sebagai Background Service (opsional)

Buat file `musa-bot.service`:
```ini
[Unit]
Description=Musa Journal Bot
After=network.target

[Service]
WorkingDirectory=/path/to/musa/bot
ExecStart=/usr/bin/python3 bot.py
Restart=always
EnvironmentFile=/path/to/musa/bot/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo cp musa-bot.service /etc/systemd/system/
sudo systemctl enable musa-bot
sudo systemctl start musa-bot
```
