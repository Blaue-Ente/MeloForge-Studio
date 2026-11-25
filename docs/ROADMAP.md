# Roadmap

## Foundation
- [x] FastAPI, React dashboard shell, hardware detector
- [x] Ollama / OpenRouter / Novita / NVIDIA / Hugging Face provider registry
- [x] Cost estimator and hard budget gate
- [x] Novita Wan 2.2 async video adapter
- [ ] Run CI and integration tests on the target laptop

## Next
- [ ] Dynamic provider model catalogs and pricing refresh
- [ ] Persist settings and jobs in SQLite
- [ ] Queue, retries, cancellation and provider health checks
- [x] ACE-Step song-generation adapter (structure tags, BPM/key/seed, lossless output)
- [x] Loudness mastering (−14/−16/−23 LUFS, −1 dBTP), WAV/MP3 deliverables, mastering report
- [x] Genre presets and chart trend analysis (Deezer + LLM brief)
- [x] Free local visualizer music video (spectrum/wave/pulse, lyrics overlay)
- [x] Song package `meloforge.song/1` (song.json, master, sample-aligned vocal/instrumental stems) + `export-song` CLI
- [x] Music video through Atelier (estimate → confirm → progress → MP4) from the UI and `clip` CLI; storyboard/cuts live in Atelier
- [x] Sing in my own voice: Demucs stems + Seed-VC zero-shot singing conversion, consent-gated voice profiles, `voices`/`voice-add`/`sing` CLI
- [ ] Faster voice conversion on 4 GB GPUs (fewer diffusion steps, chunked fp16) and optional fine-tuned personal voice model
- [x] Agent CLI (`python -m app.cli`) and song history API
- [ ] VoxCPM voice-over adapter (not a singing engine)
- [ ] InvokeAI keyframes and scene references
- [ ] RunPod worker template for Wan/LTX
- [ ] Storyboard and beat-aware scene plan (FFmpeg composer done)
- [ ] Authentication, secrets vault, rate limits and audit logs
