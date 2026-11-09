import time, json, traceback

log = open("/tmp/transcribe_log.txt", "w")
try:
    start = time.time()
    ts = time.strftime("%H:%M:%S")
    log.write(f"[TRANSCRIBE] Starting at {ts}\n"); log.flush()

    from faster_whisper import WhisperModel
    log.write(f"[TRANSCRIBE] Model loading... ({time.time()-start:.0f}s)\n"); log.flush()
    model = WhisperModel("small", device="cpu", compute_type="int8")
    log.write(f"[TRANSCRIBE] Model loaded ({time.time()-start:.0f}s)\n"); log.flush()

    segments, info = model.transcribe(
        "/tmp/borys.mp3", beam_size=5, language=None,
        vad_filter=True, word_timestamps=False,
    )
    log.write(f"[TRANSCRIBE] Language: {info.language} ({info.language_probability*100:.0f}%)\n"); log.flush()

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
        if now - last_report >= 60:
            pct = (seg.end / 9063.7) * 100
            elapsed = now - start
            eta = (elapsed / max(seg.end, 1)) * (9063.7 - seg.end)
            log.write(f"[TRANSCRIBE] {seg.end:.0f}/9064s ({pct:.0f}%) | segs: {len(result)} | elapsed: {elapsed:.0f}s | ETA: {eta:.0f}s\n")
            log.flush()
            last_report = now

    elapsed = time.time() - start
    log.write(f"[TRANSCRIBE] DONE: {len(result)} segments in {elapsed:.0f}s\n"); log.flush()

    with open("/tmp/transcription.json", "w", encoding="utf-8") as f:
        json.dump({
            "file": "borys.mp3",
            "duration_mp3": 9063.7,
            "language": info.language,
            "language_prob": info.language_probability,
            "segments": result,
            "last_segment_end": result[-1]["end"] if result else 0,
            "transcription_time_s": round(elapsed, 1),
        }, f, ensure_ascii=False, indent=2)

    log.write("[TRANSCRIBE] Saved /tmp/transcription.json\n"); log.flush()
    open("/tmp/transcribe_done", "w").write("done")
except Exception as e:
    log.write(f"[ERROR] {traceback.format_exc()}\n"); log.flush()
finally:
    log.close()
