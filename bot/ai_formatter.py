"""
Uses Claude API to parse a voice note transcript and structure it into
journal activity entries that match the Musa journal format.
"""

import json
import os


SYSTEM_PROMPT = """\
Kamu adalah asisten pencatat jurnal belajar untuk Musa, seorang anak yang sedang belajar di rumah (homeschooling).

Tugasmu adalah membaca transkrip voice note (yang menceritakan kegiatan Musa hari ini) dan mengubahnya menjadi data jurnal terstruktur.

Output kamu harus berupa JSON dengan format berikut:
{
  "activities": [
    {
      "name": "Nama kegiatan singkat (contoh: Cooking Class, Sains - Fisika, Matematika)",
      "description": "Deskripsi singkat apa yang dilakukan (1-2 kalimat, tanpa bullet)",
      "capaian": ["Capaian 1", "Capaian 2"],
      "kendala": ["Kendala 1"]
    }
  ],
  "focus": "Kata kunci fokus hari ini (singkat, 3-5 kata)",
  "summary": "Satu kalimat ringkasan kegiatan hari ini untuk weekly readme"
}

Aturan:
- Pisahkan kegiatan berbeda menjadi item terpisah dalam array "activities"
- "capaian" adalah hal yang berhasil dipelajari atau diselesaikan
- "kendala" boleh kosong array jika tidak ada kendala
- "focus" adalah tema utama hari itu
- "summary" adalah ringkasan 1 kalimat untuk weekly readme (ditulis seperti laporan, bukan "Musa belajar..." tapi "Mengikuti sesi X dan melakukan Y...")
- Semua teks dalam Bahasa Indonesia
- Jika transkrip tidak jelas, buat perkiraan yang masuk akal berdasarkan konteks

Kembalikan HANYA JSON tanpa kode markdown atau teks lainnya.
"""


def format_transcript_to_activities(transcript: str) -> dict:
    """
    Send transcript to Claude and get structured activity data back.
    Returns dict with keys: activities, focus, summary
    """
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("anthropic package is not installed. Run: pip install anthropic")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable is not set.")

    client = anthropic.Anthropic(api_key=api_key)

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Transkrip voice note:\n\n{transcript}",
            }
        ],
    )

    raw = message.content[0].text.strip()

    # Strip markdown code blocks if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude returned invalid JSON: {e}\n\nRaw response:\n{raw}")

    # Validate structure
    if "activities" not in data:
        raise ValueError(f"Response missing 'activities' key: {data}")

    return data
