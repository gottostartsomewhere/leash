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
def out_name(p: pathlib.Path, n: int) -> str:
    """Named after the file, not after its position on the command line.

    Numbering by position meant transcribing one file wrote `_take1.json`
    whatever that file was, so checking the assembled voice track quietly
    overwrote the word timings the assembly is built from.
    """
    if "(1)" in p.name:
        return "_take2.json"
    if p.name.startswith("Record"):
        return "_take1.json"
    return f"_{p.stem.replace('-', '_')}.json"


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
    (ROOT / "video" / out_name(p, n)).write_text(
        json.dumps(out, indent=1), encoding="utf-8"
    )
    print(f"\n{'=' * 72}\nTAKE {n}  {p.name}  {out.get('duration')}s\n{'=' * 72}")
    for s in out.get("segments", []):
        print(f"  [{s['start']:7.2f} {s['end']:7.2f}]  {s['text'].strip()}")
