"""Record Grandpa's training set in Captain's ElevenLabs voice, while credits last.

Writes an LJSpeech-style folder that Piper's trainer reads directly:

    <out>/wavs/0001.wav ... (22,050 Hz, mono, 16-bit)
    <out>/metadata.csv      0001|The text that was spoken.

Safe to stop and run again: lines whose WAV already exists are skipped. It
checks the account's credits first and stops before going over ``--max-credits``
or below ``--keep-credits``, so daily replies still have credits left.

    $env:ELEVENLABS_API_KEY = [Environment]::GetEnvironmentVariable('ELEVENLABS_API_KEY','User')
    uv run python scripts/odin/voice/make_voice_dataset.py --out D:\\GrandpaVoice\\achchuu
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx  # noqa: E402
from sentences import build  # noqa: E402

API = "https://api.elevenlabs.io/v1"
RATE = 22_050
SETTINGS = {
    "stability": 0.65,  # steadier than live replies: training data should be consistent
    "similarity_boost": 0.85,
    "style": 0.0,
    "use_speaker_boost": True,
    "speed": 1.0,
}


def _key() -> str:
    import os

    for name in ("GRANDPA_ELEVENLABS_API_KEY", "ELEVENLABS_API_KEY"):
        if os.environ.get(name, "").strip():
            return os.environ[name].strip()
    sys.exit("Set ELEVENLABS_API_KEY first.")


def credits_left(client: httpx.Client) -> tuple[int, int]:
    r = client.get(f"{API}/user/subscription", timeout=20)
    r.raise_for_status()
    data = r.json()
    return int(data["character_limit"]) - int(data["character_count"]), int(
        data["character_count"]
    )


def say(client: httpx.Client, voice: str, model: str, text: str, out: Path) -> float:
    for attempt in range(4):
        r = client.post(
            f"{API}/text-to-speech/{voice}",
            params={"output_format": f"pcm_{RATE}"},
            json={"text": text, "model_id": model, "voice_settings": SETTINGS},
            timeout=60,
        )
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code != 200:
            raise RuntimeError(f"{r.status_code}: {r.text[:200]}")
        pcm = r.content[: len(r.content) // 2 * 2]
        tmp = out.with_suffix(".part")
        with wave.open(str(tmp), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(pcm)
        tmp.replace(out)
        return len(pcm) / 2 / RATE
    raise RuntimeError("ElevenLabs kept failing (rate limit or server error).")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--voice", default="iJwttXBNy3RzWJrkRD97")
    ap.add_argument("--model", default="eleven_flash_v2_5")
    ap.add_argument(
        "--max-credits", type=int, default=24_000, help="spend at most this many"
    )
    ap.add_argument(
        "--keep-credits", type=int, default=5_000, help="never go below this"
    )
    ap.add_argument(
        "--limit", type=int, default=0, help="only the first N lines (a test run)"
    )
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()

    lines = build()
    if args.limit:
        lines = lines[: args.limit]
    wavs = args.out / "wavs"
    wavs.mkdir(parents=True, exist_ok=True)
    (args.out / "metadata.csv").write_text(
        "".join(f"{i:04d}|{t}\n" for i, t in enumerate(lines, 1)), encoding="utf-8"
    )
    todo = [
        (i, t) for i, t in enumerate(lines, 1) if not (wavs / f"{i:04d}.wav").exists()
    ]
    print(
        f"{len(lines)} lines, {len(lines) - len(todo)} already recorded, {len(todo)} to go"
    )

    client = httpx.Client(headers={"xi-api-key": _key()})
    left, used_at_start = credits_left(client)
    print(f"credits left: {left}")
    spent_chars = 0
    seconds = 0.0
    failed = 0
    budget_chars = min(
        args.max_credits * 2, (left - args.keep_credits) * 2
    )  # Flash: 0.5/char
    with cf.ThreadPoolExecutor(args.workers) as pool:
        futures = {}
        for i, text in todo:
            if spent_chars + len(text) > budget_chars:
                print("budget reached, stopping here (run again next month to finish)")
                break
            spent_chars += len(text)
            futures[
                pool.submit(
                    say, client, args.voice, args.model, text, wavs / f"{i:04d}.wav"
                )
            ] = i
        for n, fut in enumerate(cf.as_completed(futures), 1):
            try:
                seconds += fut.result()
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"line {futures[fut]}: {exc}")
                if failed >= 5:
                    print("too many failures, stopping")
                    pool.shutdown(cancel_futures=True)
                    break
            if n % 25 == 0:
                print(
                    f"  {n}/{len(futures)} done, {seconds / 60:.1f} min of audio",
                    flush=True,
                )
    left_now, used_now = credits_left(client)
    have = len(list(wavs.glob("*.wav")))
    print(
        f"recorded {have}/{len(lines)} lines this folder; this run made {seconds / 60:.1f} min; "
        f"credits used this run {used_now - used_at_start}, left {left_now}"
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
