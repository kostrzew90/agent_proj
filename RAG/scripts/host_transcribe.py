"""Host-side transcription for large audio files (avoids Docker RAM limits)."""
import json
import os
import sys
import time

AUDIO_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "Wszystkie grzechy polskiej policji - Marcin _Borys_ Miksza bez cenzury. [EtLCZyx7eyc].mp3",
)
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transcription_output.json")
MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "small")
BEAM_SIZE = int(os.environ.get("WHISPER_BEAM_SIZE", "5"))
AUDIO_DURATION = 9063.7


def main():
    if not os.path.exists(AUDIO_FILE):
        print(f"[ERROR] Audio file not found: {AUDIO_FILE}", flush=True)
        sys.exit(1)

    t0 = time.time()
    print(f"[TRANSCRIBE] File: {os.path.basename(AUDIO_FILE)} ({AUDIO_DURATION:.0f}s)", flush=True)
    print(f"[TRANSCRIBE] Model: {MODEL_SIZE}, beam_size: {BEAM_SIZE}", flush=True)

    from faster_whisper import WhisperModel

    print(f"[TRANSCRIBE] Loading model... ({time.time()-t0:.1f}s)", flush=True)
    model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
    print(f"[TRANSCRIBE] Model loaded ({time.time()-t0:.1f}s)", flush=True)

    segments, info = model.transcribe(
        AUDIO_FILE,
        beam_size=BEAM_SIZE,
        language=None,
        vad_filter=True,
        word_timestamps=False,
    )
    print(f"[TRANSCRIBE] Language: {info.language} ({info.language_probability*100:.0f}%)", flush=True)

    result = []
    last_report = time.time()
    for seg in segments:
        text = seg.text.strip()
        if text:
            result.append({
                "text": text,
                "start": round(seg.start, 2),
                "end": round(seg.end, 2),
                "duration": round(seg.end - seg.start, 2),
            })
        now = time.time()
        if now - last_report >= 30:
            pct = (seg.end / AUDIO_DURATION) * 100
            elapsed = now - t0
            eta = (elapsed / max(seg.end, 1)) * (AUDIO_DURATION - seg.end)
            mins_e = int(elapsed // 60)
            secs_e = int(elapsed % 60)
            mins_eta = int(eta // 60)
            secs_eta = int(eta % 60)
            print(
                f"[TRANSCRIBE] {seg.end:.0f}/{AUDIO_DURATION:.0f}s ({pct:.0f}%) | "
                f"segs: {len(result)} | elapsed: {mins_e}m{secs_e:02d}s | ETA: {mins_eta}m{secs_eta:02d}s",
                flush=True,
            )
            last_report = now

    elapsed = time.time() - t0
    print(f"[TRANSCRIBE] DONE: {len(result)} segments in {elapsed:.1f}s", flush=True)

    data = {
        "file": os.path.basename(AUDIO_FILE),
        "duration_mp3": AUDIO_DURATION,
        "language": info.language,
        "language_prob": info.language_probability,
        "segments": result,
        "last_segment_end": result[-1]["end"] if result else 0,
        "transcription_time_s": round(elapsed, 1),
        "model_size": MODEL_SIZE,
        "beam_size": BEAM_SIZE,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[TRANSCRIBE] Saved to {OUTPUT_FILE}", flush=True)


if __name__ == "__main__":
    main()
