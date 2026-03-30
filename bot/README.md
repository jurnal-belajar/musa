# Jurnal Bot

Telegram bot untuk mencatat jurnal harian via voice note, teks, dan foto.
Satu codebase, bisa dijalankan untuk beberapa repo jurnal secara terpisah.

## Fitur

- 🎙️ **Voice note** → transkripsi otomatis (Whisper lokal, gratis, offline)
- 💬 **Teks** → langsung diproses
- 📸 **Foto** → disimpan ke `img/`, masuk ke dokumentasi jurnal
- 🤖 **Claude AI** → memformat cerita mentah menjadi jurnal terstruktur
- ✅ **Approval flow** → pratinjau dulu, baru push ke repo
- ✏️ **Edit** → kirim koreksi teks, bot format ulang
- 🔀 **Auto git commit & push** setelah disetujui

## Cara Kerja

```
Voice / Teks
     ↓
Transkripsi (Whisper)
     ↓
Format dengan Claude AI
     ↓
Tulis .md lokal (BELUM di-commit)
     ↓
Tampilkan pratinjau + keyboard
[✅ Setujui & Push] [✏️ Edit] [❌ Batalkan]
     ↓              ↓              ↓
  commit+push   kirim koreksi  revert semua
                     ↓
               format ulang → pratinjau baru

📸 Foto: kirim kapan saja setelah pratinjau muncul,
         sebelum tap ✅ Setujui
```

## Setup

### 1. Prasyarat sistem

```bash
# Ubuntu/Debian
sudo apt install ffmpeg git python3 python3-pip

# Mac
brew install ffmpeg
```

### 2. Install dependensi Python

```bash
pip install -r requirements.txt
```

### 3. Buat Telegram Bot

- Chat ke [@BotFather](https://t.me/BotFather)
- Ketik `/newbot`, ikuti instruksinya
- Salin **Bot Token** yang diberikan

### 4. Dapatkan Anthropic API Key

- Daftar di [console.anthropic.com](https://console.anthropic.com)
- Tidak perlu OpenAI API key

### 5. Konfigurasi

```bash
cp .env.example .env
# Edit .env dan isi semua nilai
```

Minimal yang harus diisi:
```env
TELEGRAM_BOT_TOKEN=...
ANTHROPIC_API_KEY=...
BOT_NAME=Musa               # atau Aasiyah
REPO_ROOT=/path/to/musa     # path absolut ke repo jurnal
ALLOWED_USER_IDS=123456789  # Telegram user ID kamu (@userinfobot)
```

### 6. Jalankan

```bash
cd /path/to/jurnal-bot
python bot.py
```

---

## Menjalankan untuk Dua Jurnal (Musa & Aasiyah)

Buat dua file `.env` terpisah dan jalankan dua proses:

```bash
# .env.musa
BOT_NAME=Musa
REPO_ROOT=/home/user/musa
TELEGRAM_BOT_TOKEN=token_bot_musa

# .env.aasiyah
BOT_NAME=Aasiyah
REPO_ROOT=/home/user/aasiyah
TELEGRAM_BOT_TOKEN=token_bot_aasiyah
```

```bash
# Terminal 1 — bot Musa
ENV_FILE=.env.musa python bot.py

# Terminal 2 — bot Aasiyah
ENV_FILE=.env.aasiyah python bot.py
```

Atau dengan systemd, buat dua unit service terpisah.

---

## Perintah Bot

| Perintah | Fungsi |
|----------|--------|
| `/start` | Pesan sambutan |
| `/help`  | Panduan penggunaan |
| `/today` | Tampilkan log hari ini |

## Model Whisper

| Model | Ukuran | Kecepatan | Akurasi |
|-------|--------|-----------|---------|
| `tiny` | 39 MB | Sangat cepat | Rendah |
| `base` | 74 MB | Cepat | Cukup ✓ **(default)** |
| `small` | 244 MB | Sedang | Bagus |
| `medium` | 769 MB | Lambat | Sangat bagus |

Model didownload otomatis saat pertama kali dijalankan.

---

## Menjalankan Sebagai Service (opsional)

```ini
# /etc/systemd/system/jurnal-musa.service
[Unit]
Description=Jurnal Bot Musa
After=network.target

[Service]
WorkingDirectory=/path/to/jurnal-bot
ExecStart=/usr/bin/python3 bot.py
Restart=always
EnvironmentFile=/path/to/jurnal-bot/.env.musa

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable jurnal-musa
sudo systemctl start jurnal-musa
```
