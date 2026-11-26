"""Worker code executed inside the Seed-VC Python environment (numpy, soundfile, faster-whisper).

The source is passed with ``python -c`` so the frozen desktop app does not need
to ship a separate script file. Commands (JSON on argv[1], JSON result on stdout):

``{"cmd": "words", "audio": ..., "language": "bg"}``
    faster-whisper word timestamps on a (vocal) stem, CPU int8.

``{"cmd": "mix", "length": seconds, "out": ..., "layers": [...]}``
    Sum vocal layers with per-segment gain envelopes (50 ms ramps), optional
    delay, tiny detune (cents) and stereo pan. Used for duets and choirs.
"""

WORKER_SOURCE = r'''
import json, sys

def words(job):
    from faster_whisper import WhisperModel
    model = WhisperModel(job.get("model", "small"), device="cpu", compute_type="int8")
    segments, _ = model.transcribe(job["audio"], language=job.get("language") or None, word_timestamps=True,
                                   vad_filter=True, beam_size=5, condition_on_previous_text=False)
    out = []
    for seg in segments:
        for w in seg.words or []:
            out.append({"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word.strip(), "p": round(w.probability, 3)})
    return {"words": out}

def notes(job):
    # Sung notes from the vocal stem: pYIN f0 -> runs of the same rounded MIDI pitch.
    import numpy as np, librosa
    y, sr = librosa.load(job["audio"], sr=22050, mono=True)
    hop = 256
    f0, voiced, _ = librosa.pyin(y, fmin=65.0, fmax=1050.0, sr=sr, hop_length=hop, frame_length=2048)
    times = librosa.times_like(f0, sr=sr, hop_length=hop)
    out, cur = [], None
    for t, hz, v in zip(times, f0, voiced):
        midi = int(round(librosa.hz_to_midi(hz))) if v and hz == hz else None
        if cur and midi == cur[2]:
            cur[1] = float(t)
            continue
        if cur and cur[1] - cur[0] >= 0.08:
            out.append([round(cur[0], 3), round(cur[1] + hop / sr, 3), cur[2]])
        cur = [float(t), float(t), midi] if midi is not None else None
    if cur and cur[1] - cur[0] >= 0.08:
        out.append([round(cur[0], 3), round(cur[1] + hop / sr, 3), cur[2]])
    return {"notes": out}

def mix(job):
    import numpy as np, soundfile as sf
    sr = 44100
    n = int(round(job["length"] * sr))
    acc = np.zeros((n, 2), dtype=np.float64)
    ramp = int(0.05 * sr)
    for layer in job["layers"]:
        data, rate = sf.read(layer["path"], always_2d=True, dtype="float64")
        if rate != sr:
            raise SystemExit(f"expected {sr} Hz, got {rate}")
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        cents = float(layer.get("cents", 0))
        if cents:
            # Resample by the pitch ratio (also shifts timing by <0.5 %, fine for a doubled layer).
            ratio = 2 ** (cents / 1200.0)
            idx = np.arange(0, data.shape[0] - 1, ratio)
            lo = idx.astype(np.int64)
            frac = (idx - lo)[:, None]
            data = data[lo] * (1 - frac) + data[lo + 1] * frac
        delay = int(float(layer.get("delay_ms", 0)) * sr / 1000)
        if delay:
            data = np.vstack([np.zeros((delay, 2)), data])
        data = data[:n]
        if data.shape[0] < n:
            data = np.vstack([data, np.zeros((n - data.shape[0], 2))])
        env = np.zeros(n)
        for start, end in layer["segments"]:
            a, b = max(0, int(start * sr)), min(n, int(end * sr))
            if b <= a:
                continue
            env[a:b] = 1.0
        if ramp > 1:
            kernel = np.ones(ramp) / ramp
            env = np.convolve(env, kernel, mode="same")
        gain = 10 ** (float(layer.get("gain_db", 0)) / 20)
        pan = max(-1.0, min(1.0, float(layer.get("pan", 0))))
        left, right = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
        acc[:, 0] += data[:, 0] * env * gain * left * np.sqrt(2)
        acc[:, 1] += data[:, 1] * env * gain * right * np.sqrt(2)
    peak = float(np.max(np.abs(acc))) if acc.size else 0.0
    if peak > 0.98:
        acc *= 0.98 / peak
    sf.write(job["out"], acc.astype(np.float32), sr, subtype="PCM_24")
    return {"peak": round(peak, 3)}

job = json.loads(sys.argv[1])
result = {"words": words, "notes": notes, "mix": mix}[job["cmd"]](job)
sys.stdout.write("\n@@RESULT@@" + json.dumps(result, ensure_ascii=False))
'''
