"""
Transcribes audio files using local OpenAI Whisper model.
Runs entirely offline — no API key required.

Requirements:
    pip install openai-whisper
    # Linux:  sudo apt install ffmpeg
    # Mac:    brew install ffmpeg
    # Windows: https://ffmpeg.org/download.html
"""

import os


# Whisper model size to use. Tradeoff: speed vs accuracy.
#   tiny   (~39M)  — paling cepat, akurasi rendah
#   base   (~74M)  — cepat, akurasi cukup          ← default
#   small  (~244M) — seimbang
#   medium (~769M) — akurasi bagus, butuh ~5GB RAM
#   large  (~1.5G) — paling akurat, butuh ~10GB RAM
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")

_model_cache = None


def _load_model():
    global _model_cache
    if _model_cache is None:
        try:
            import whisper
        except ImportError:
            raise RuntimeError(
                "openai-whisper tidak terinstall.\n"
                "Jalankan: pip install openai-whisper\n"
                "Dan pastikan ffmpeg terinstall di sistem."
            )
        _model_cache = whisper.load_model(WHISPER_MODEL)
    return _model_cache


def transcribe_audio(audio_path: str) -> str:
    """
    Transcribe an audio file to text using local Whisper model.
    Returns the transcribed text. No API key needed.
    """
    model = _load_model()
    result = model.transcribe(audio_path, language="id", fp16=False)
    return result["text"].strip()
