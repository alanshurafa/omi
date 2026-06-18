import websockets
import json
import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Callable, Optional
from asyncio import Queue


@dataclass
class TranscribeConfig:
    """Streaming STT configuration.

    Defaults reproduce the previous hardcoded Deepgram settings, so existing
    callers that don't pass a config see identical behavior.
    """

    model: str = "nova"
    language: str = "en-US"
    encoding: str = "linear16"
    sample_rate: int = 16000
    channels: int = 1
    punctuate: bool = True
    endpoint: str = "wss://api.deepgram.com/v1/listen"

    def to_url(self) -> str:
        params = (
            f"punctuate={'true' if self.punctuate else 'false'}"
            f"&model={self.model}"
            f"&language={self.language}"
            f"&encoding={self.encoding}"
            f"&sample_rate={self.sample_rate}"
            f"&channels={self.channels}"
        )
        return f"{self.endpoint}?{params}"


@dataclass
class Transcript:
    """A single transcription result.

    `text` is always present; the remaining fields are populated when the STT
    provider supplies them. `raw` keeps the full provider payload (including
    word-level timestamps) for callers that need more than these fields.
    """

    text: str
    is_final: bool = False
    start: Optional[float] = None
    end: Optional[float] = None
    speaker: Optional[int] = None
    confidence: Optional[float] = None
    language: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


class TranscriptSink:
    """Destination for transcripts.

    Subclass and override `write` to push transcripts somewhere — your own
    backend, a queue, a file. `write` may be sync or async; the transcribe loop
    awaits it either way. Keep HTTP/database specifics in your sink (see
    `examples/backend_sink.py`); the SDK core stays transport-agnostic.
    """

    async def write(self, transcript: Transcript) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class ConsoleSink(TranscriptSink):
    """Default sink: prints transcripts to stdout (preserves prior behavior)."""

    async def write(self, transcript: Transcript) -> None:
        print("\nTranscript:", transcript.text)


def _parse_transcript(response: Dict[str, Any], config: TranscribeConfig) -> Optional[Transcript]:
    """Build a Transcript from a Deepgram streaming message, or None when the
    message carries no transcript text."""
    channel = response.get("channel")
    if not channel or "alternatives" not in channel:
        return None
    alternatives = channel["alternatives"]
    if not alternatives:
        return None

    alt = alternatives[0]
    text = (alt.get("transcript") or "").strip()
    if not text:
        return None

    # Timestamp semantics: the Deepgram result window [start, start + duration].
    # Word-level timestamps stay available in `raw`.
    start = response.get("start")
    duration = response.get("duration")
    end = start + duration if start is not None and duration is not None else None

    # Speaker id (when diarization is enabled) is attached to each word.
    speaker = None
    words = alt.get("words") or []
    if words:
        speaker = words[0].get("speaker")

    return Transcript(
        text=text,
        is_final=bool(response.get("is_final", False)),
        start=start,
        end=end,
        speaker=speaker,
        confidence=alt.get("confidence"),
        language=config.language,
        raw=response,
    )


async def _dispatch(
    transcript: Transcript,
    on_transcript: Optional[Callable[[str], Any]],
    sink: Optional[TranscriptSink],
) -> None:
    """Deliver a transcript to the text callback and/or the sink.

    `on_transcript` gets the text (str) for backward compatibility and may be
    sync or async; `sink` gets the full `Transcript`.
    """
    if on_transcript is not None:
        result = on_transcript(transcript.text)
        if asyncio.iscoroutine(result):
            await result
    if sink is not None:
        await sink.write(transcript)


async def transcribe(
    audio_queue: Queue[bytes],
    api_key: str,
    on_transcript: Optional[Callable[[str], Any]] = None,
    sink: Optional[TranscriptSink] = None,
    config: Optional[TranscribeConfig] = None,
) -> None:
    """
    Real-time audio transcription using the Deepgram WebSocket API.

    Args:
        audio_queue: Queue containing PCM audio chunks.
        api_key: Deepgram API key.
        on_transcript: Optional callback receiving the transcript text (str).
            Backward compatible — still supported. May be sync or async. Prefer
            `sink` when you need timestamps, speaker, or confidence.
        sink: Optional TranscriptSink receiving full `Transcript` objects.
        config: Optional TranscribeConfig (model, language, encoding,
            sample_rate). Defaults match the previous hardcoded settings.

    If neither `on_transcript` nor `sink` is provided, transcripts are printed
    to the console, matching earlier SDK behavior.
    """
    config = config or TranscribeConfig()
    if on_transcript is None and sink is None:
        sink = ConsoleSink()

    url = config.to_url()

    while True:
        try:
            async with websockets.connect(url, additional_headers={"Authorization": f"Token {api_key}"}) as ws:
                print("Connected to Deepgram WebSocket")

                async def send_audio() -> None:
                    """Send audio chunks from queue to WebSocket."""
                    while True:
                        try:
                            chunk: bytes = await audio_queue.get()
                            await ws.send(chunk)
                        except Exception as e:
                            print(f"Error sending audio: {e}")
                            break

                async def receive_transcripts() -> None:
                    """Receive and process transcription results from WebSocket."""
                    try:
                        async for msg in ws:
                            try:
                                response: Dict[str, Any] = json.loads(msg)
                                if "error" in response:
                                    print(f"Deepgram Error: {response['error']}")
                                    continue

                                transcript = _parse_transcript(response, config)
                                if transcript is not None:
                                    await _dispatch(transcript, on_transcript, sink)
                            except json.JSONDecodeError as e:
                                print(f"Error decoding response: {e}")
                            except Exception as e:
                                print(f"Error processing transcript: {e}")
                    except websockets.exceptions.ConnectionClosed:
                        print("Connection to Deepgram closed")
                    except Exception as e:
                        print(f"Error in receive_transcripts: {e}")

                try:
                    await asyncio.gather(send_audio(), receive_transcripts())
                except Exception as e:
                    print(f"Error in transcribe: {e}")

        except Exception as e:
            print(f"Connection error: {e}")
            print("Retrying connection in 5 seconds...")
            await asyncio.sleep(5)
