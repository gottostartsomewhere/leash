"""Transcribe the voiceover takes with timestamps, so pace can be checked
against the cut rather than guessed at.

Groq's free tier, the same key the agent and the red team already use.
httpx rather than urllib: Cloudflare rejects urllib's user agent with a
1010 before the request ever reaches Groq.
"""

import json
import pathlib
import sys

import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent


def key() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("LEASH_GROQ_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("no LEASH_GROQ_API_KEY in .env")


token = key()
for n, path in enumerate(sys.argv[1:], start=1):
    p = pathlib.Path(path)
    with httpx.Client(timeout=300.0) as client:
        r = client.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (p.name, p.read_bytes(), "audio/mpeg")},
            data={
                "model": "whisper-large-v3",
                "response_format": "verbose_json",
                "language": "en",
                "timestamp_granularities[]": "word",
            },
        )
    if r.status_code != 200:
        sys.exit(f"HTTP {r.status_code}: {r.text[:600]}")
    out = r.json()
    (ROOT / "video" / f"_take{n}.json").write_text(
        json.dumps(out, indent=1), encoding="utf-8"
    )
    print(f"\n{'=' * 72}\nTAKE {n}  {p.name}  {out.get('duration')}s\n{'=' * 72}")
    for s in out.get("segments", []):
        print(f"  [{s['start']:7.2f} {s['end']:7.2f}]  {s['text'].strip()}")
