"""
Transcribes audio files using OpenAI Whisper API.
"""

import os
from pathlib import Path


def transcribe_audio(audio_path: str) -> str:
    """
    Transcribe an audio file to text using OpenAI Whisper API.
    Returns the transcribed text.
    """
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("openai package is not installed. Run: pip install openai")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable is not set.")

    client = OpenAI(api_key=api_key)

    with open(audio_path, "rb") as audio_file:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="id",  # Indonesian
            response_format="text",
        )

    return response.strip() if isinstance(response, str) else response.text.strip()
