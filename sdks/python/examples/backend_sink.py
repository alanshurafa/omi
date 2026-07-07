"""
Example: stream Omi transcripts to your own backend.

Instead of printing transcripts, push each structured `Transcript` to an HTTP
endpoint you control — your API, a Supabase function, a serverless webhook.
The SDK core stays transport-agnostic: the HTTP POST lives here in the example,
not in the SDK. Swap `BackendSink` for a Supabase client, a Kafka producer, or
a database write as needed.

Try it without hardware using a local echo server. In one terminal:

    python -c "from http.server import BaseHTTPRequestHandler, HTTPServer; \
H=type('H',(BaseHTTPRequestHandler,),{'do_POST':lambda s:(s.send_response(200), s.end_headers(), \
print(s.rfile.read(int(s.headers['Content-Length'])).decode()))}); \
HTTPServer(('127.0.0.1',8088),H).serve_forever()"

In another terminal:

    export DEEPGRAM_API_KEY=...                 # your Deepgram key
    export OMI_SINK_URL=http://127.0.0.1:8088   # where transcripts are POSTed
    python examples/backend_sink.py
"""

import asyncio
import json
import os
import urllib.request
from dataclasses import asdict
from typing import Any
from asyncio import Queue

from omi.bluetooth import listen_to_omi
from omi.decoder import OmiOpusDecoder
from omi.transcribe import Transcript, TranscribeConfig, TranscriptSink, transcribe

# Replace with your Omi device's MAC address (get it by running: omi-scan)
OMI_MAC = "C9DDDACB-CA1E-CDD6-7A17-59A2A5303CDA"
# Standard Omi audio characteristic UUID
OMI_CHAR_UUID = "19B10001-E8F2-537E-4F6C-D104768A1214"


class BackendSink(TranscriptSink):
    """Posts each transcript to an HTTP endpoint as JSON.

    The blocking network call is offloaded to a thread so it never stalls the
    audio or transcription loops.
    """

    def __init__(self, url: str) -> None:
        self.url = url

    async def write(self, transcript: Transcript) -> None:
        await asyncio.to_thread(self._post, transcript)

    def _post(self, transcript: Transcript) -> None:
        payload = json.dumps(asdict(transcript)).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp.read()
        except Exception as e:
            print(f"Failed to post transcript: {e}")


def main() -> None:
    api_key: str | None = os.getenv("DEEPGRAM_API_KEY")
    if not api_key:
        print("Set your Deepgram API Key in the DEEPGRAM_API_KEY environment variable.")
        return

    sink_url: str | None = os.getenv("OMI_SINK_URL")
    if not sink_url:
        print("Set OMI_SINK_URL to the endpoint that should receive transcripts.")
        return

    audio_queue: Queue[bytes] = Queue()
    decoder = OmiOpusDecoder()
    sink = BackendSink(sink_url)
    # Configure STT without editing SDK internals.
    config = TranscribeConfig(model="nova", language="en-US")

    def handle_ble_data(sender: Any, data: bytes) -> None:
        decoded_pcm: bytes = decoder.decode_packet(data)
        if decoded_pcm:
            try:
                audio_queue.put_nowait(decoded_pcm)
            except Exception as e:
                print("Queue Error:", e)

    async def run() -> None:
        await asyncio.gather(
            listen_to_omi(OMI_MAC, OMI_CHAR_UUID, handle_ble_data),
            transcribe(audio_queue, api_key, sink=sink, config=config),
        )

    asyncio.run(run())


if __name__ == '__main__':
    main()
