"""
Omi Python SDK

A Python SDK for connecting to Omi wearable devices over Bluetooth,
decoding Opus-encoded audio, and transcribing it in real time.
"""

__version__ = "0.2.0"

from .bluetooth import print_devices, listen_to_omi
from .decoder import OmiOpusDecoder
from .transcribe import (
    transcribe,
    Transcript,
    TranscribeConfig,
    TranscriptSink,
    ConsoleSink,
)

__all__ = [
    "print_devices",
    "listen_to_omi",
    "OmiOpusDecoder",
    "transcribe",
    "Transcript",
    "TranscribeConfig",
    "TranscriptSink",
    "ConsoleSink",
    "__version__",
]
