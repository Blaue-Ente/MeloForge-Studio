"""MeloForge command line for scripts and AI agents.

Runs the same FastAPI app in-process (no server needed) and prints JSON, so an
agent can create a song end to end:

    python -m app.cli readiness
    python -m app.cli lyrics --prompt "..." --language bg --duration 120
    python -m app.cli song --prompt "..." --lyrics-file song.txt --duration 120 --yes --out ./out
    python -m app.cli trends --genre pop          (or --genre list)
    python -m app.cli master input.wav --out ./mastered --preset streaming
    python -m app.cli jobs --kind song
    python -m app.cli voices
    python -m app.cli voice-add me.wav --name "My voice" --i-own-this-voice
    python -m app.cli sing --song <song job id> --voice <voice id> --semitones 0 --out ./out
    python -m app.cli library                       (copy finished songs to Music\MeloForge)
    python -m app.cli export-song <song job id> --to ./package      (meloforge.song/1 for Atelier)
    python -m app.cli clip <song job id> --mode stills --local-only  (Atelier music video; --confirm to start)

Data and settings are shared with the desktop app (%LOCALAPPDATA%\\MeloForge Studio)
unless MELOFORGE_DATA_DIR / MELOFORGE_ENV_FILE are already set.
Paid (non-zero) quotes are never confirmed without --yes and --max-cost.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path


def _use_desktop_profile() -> None:
    home = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "MeloForge Studio"
    if home.is_dir():
        os.environ.setdefault("MELOFORGE_DATA_DIR", str(home / "data"))
        if (home / "config.env").is_file():
            os.environ.setdefault("MELOFORGE_ENV_FILE", str(home / "config.env"))


def _print(data, code: int = 0) -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return code


def _detail(response) -> object:
    try:
        return response.json().get("detail", response.json())
    except ValueError:
        return response.text


def _client():
    import warnings

    warnings.filterwarnings("ignore", category=DeprecationWarning)
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def cmd_readiness(_args) -> int:
    with _client() as client:
        return _print(client.get("/api/v1/music/readiness").json())


def cmd_jobs(args) -> int:
    with _client() as client:
        params = {"limit": args.limit, **({"kind": args.kind} if args.kind else {})}
        rows = client.get("/api/v1/jobs", params=params).json()["jobs"]
        return _print([{k: row.get(k) for k in ("id", "kind", "status", "created_at", "error")} | {"title": row["payload"].get("title")} for row in rows])


def cmd_lyrics(args) -> int:
    body = {"prompt": args.prompt, "title": args.title, "genre": args.genre, "mood": args.mood,
            "language": args.language, "duration_seconds": args.duration}
    if args.provider:
        body["provider"] = args.provider
    if args.themes:
        body["themes"] = [item.strip() for item in args.themes.split(";") if item.strip()]
    with _client() as client:
        response = client.post("/api/v1/music/lyrics", json=body)
    if response.status_code != 200:
        return _print({"error": _detail(response)}, 1)
    data = response.json()
    if args.out:
        Path(args.out).write_text(data["lyrics"] + "\n", encoding="utf-8", newline="\n")
        data["written_to"] = str(Path(args.out).resolve())
    return _print(data)


def cmd_trends(args) -> int:
    body = {"genre": args.genre, "language": args.language, "analyze": not args.no_analyze, "refresh": args.refresh}
    if args.provider:
        body["provider"] = args.provider
    with _client() as client:
        if args.genre == "list":
            return _print(client.get("/api/v1/music/genres").json()["genres"])
        response = client.post("/api/v1/music/trends", json=body)
    if response.status_code != 200:
        return _print({"error": _detail(response)}, 1)
    data = response.json()
    data["tracks"] = [f"{t['rank']}. {t['artist']} - {t['title']}" for t in data["tracks"][:args.top]]
    return _print(data)


def cmd_master(args) -> int:
    from app.services.mastering import master_track

    source = Path(args.input)
    out = Path(args.out or source.with_suffix("").as_posix() + "-master")
    report = master_track(source, out, preset=args.preset, title=args.title, genre=args.genre)
    return _print({"output_dir": str(out.resolve()), **report}, 0 if report["compliant"] else 2)


def cmd_song(args) -> int:
    lyrics = ""
    if args.lyrics_file:
        lyrics = Path(args.lyrics_file).read_text(encoding="utf-8")
    elif args.lyrics:
        lyrics = args.lyrics
    body = {
        "title": args.title, "prompt": args.prompt, "genre": args.genre, "mood": args.mood,
        "language": args.language, "duration_seconds": args.duration, "lyrics": lyrics,
        "instrumental": args.instrumental, "inference_steps": args.steps, "master_preset": args.preset,
    }
    for key, value in (("bpm", args.bpm), ("key_scale", args.key), ("time_signature", args.time_signature), ("seed", args.seed), ("max_cost_usd", args.max_cost)):
        if value is not None:
            body[key] = value

    with _client() as client:
        quote = client.post("/api/v1/jobs/song/quote", json=body)
        if quote.status_code != 200:
            return _print({"stage": "quote", "error": _detail(quote)}, 1)
        job = quote.json()
        if job["quote_usd"] > 0 and not (args.yes and args.max_cost is not None):
            return _print({"stage": "quote", "job_id": job["id"], "quote_usd": job["quote_usd"],
                           "message": "Paid generation: re-run with --yes and --max-cost to confirm."}, 3)
        if not args.yes and job["quote_usd"] == 0:
            print(f"Local generation ($0). Job {job['id']}. Confirming…", file=sys.stderr)
        confirmed = client.post(f"/api/v1/jobs/{job['id']}/confirm")
        if confirmed.status_code != 200:
            return _print({"stage": "confirm", "job_id": job["id"], "error": _detail(confirmed)}, 1)

        started = time.monotonic()
        state = confirmed.json()
        while state["status"] in {"queued", "running", "mastering"}:
            if time.monotonic() - started > args.timeout:
                return _print({"stage": "generate", "job_id": job["id"], "status": state["status"], "error": "timeout; poll again with `jobs`"}, 4)
            time.sleep(3)
            state = client.get(f"/api/v1/jobs/{job['id']}").json()
            print(f"[{int(time.monotonic() - started)}s] {state['status']}", file=sys.stderr)

    if state["status"] != "completed":
        return _print({"stage": "generate", "job_id": job["id"], "status": state["status"], "error": state.get("error")}, 1)
    result = state["result"]
    output = {"job_id": job["id"], "status": "completed", "seconds": round(time.monotonic() - started, 1),
              "warnings": job.get("warnings", []), "local_dir": result["local_dir"],
              "mastering": {k: result["mastering"][k] for k in ("preset", "compliant", "before", "after")},
              "metadata": result.get("metadata")}
    if args.out:
        target = Path(args.out)
        target.mkdir(parents=True, exist_ok=True)
        stem = "".join(ch for ch in (args.title or "song") if ch.isalnum() or ch in " -_").strip() or "song"
        copied = {}
        for name, suffix in (("master.mp3", ".mp3"), ("master.wav", ".wav"), ("lyrics.txt", ".lyrics.txt"), ("mastering-report.json", ".mastering.json")):
            source = Path(result["local_dir"]) / name
            if source.is_file():
                destination = target / f"{stem}{suffix}"
                shutil.copyfile(source, destination)
                copied[name] = str(destination.resolve())
        output["files"] = copied
    return _print(output)


def cmd_voices(_args) -> int:
    with _client() as client:
        return _print(client.get("/api/v1/voices").json())


def cmd_voice_add(args) -> int:
    if not args.i_own_this_voice:
        return _print({"error": "Pass --i-own-this-voice: only your own voice, or one you have explicit permission to use."}, 1)
    source = Path(args.input)
    with _client() as client:
        response = client.post("/api/v1/voices", params={"name": args.name, "filename": source.name, "consent": "true"},
                               content=source.read_bytes(), headers={"Content-Type": "application/octet-stream"})
    return _print(response.json() if response.status_code == 200 else {"error": _detail(response)}, 0 if response.status_code == 200 else 1)


def cmd_sing(args) -> int:
    from app.services.arrangement import is_chorus

    body = {"song_job_id": args.song, "voice_id": args.voice, "semitones": args.semitones, "quality": args.quality,
            "master_preset": args.preset}
    started = time.monotonic()
    with _client() as client:
        if args.voice_b or args.choir:
            sections = client.get(f"/api/v1/song-sections/{args.song}").json()
            parts = dict(sections.get("duet_default") or {}) if args.voice_b else {str(s["index"]): "A" for s in sections.get("sections", []) if s["lines"]}
            if args.choir:
                for section in sections.get("sections", []):
                    if section["lines"] and is_chorus(section["label"]):
                        parts[str(section["index"])] = "choir"
            body.update(parts=parts)
            if args.voice_b:
                body.update(voice_b_id=args.voice_b, semitones_b=args.semitones_b)
        # The in-process client runs the background conversion before returning.
        response = client.post("/api/v1/music/voice-swap", json=body)
        if response.status_code != 200:
            return _print({"stage": "start", "error": _detail(response)}, 1)
        state = client.get(f"/api/v1/jobs/{response.json()['id']}").json()
    if state["status"] != "completed":
        return _print({"job_id": state["id"], "status": state["status"], "error": state.get("error")}, 1)
    result = state["result"]
    output = {"job_id": state["id"], "seconds": round(time.monotonic() - started, 1), "local_dir": result["local_dir"],
              "timings": result.get("timings"), "sections": result.get("sections"), "mastering": {k: result["mastering"][k] for k in ("preset", "compliant", "after")}}
    if args.out:
        target = Path(args.out)
        target.mkdir(parents=True, exist_ok=True)
        stem = "".join(ch for ch in state["payload"].get("title", "song") if ch.isalnum() or ch in " -_()").strip() or "song"
        copied = {}
        for name, suffix in (("master.mp3", ".mp3"), ("master.wav", ".wav"), ("vocals.wav", " - vocals.wav"), ("instrumental.wav", " - instrumental.wav")):
            source = Path(result["local_dir"]) / name
            if source.is_file():
                shutil.copyfile(source, target / f"{stem}{suffix}")
                copied[name] = str((target / f"{stem}{suffix}").resolve())
        output["files"] = copied
    return _print(output)


def cmd_export_song(args) -> int:
    from app.services.song_package import PackageError, export_package

    try:
        result = export_package(args.song, Path(args.to) if args.to else None, stems=not args.no_stems)
    except PackageError as exc:
        return _print({"error": str(exc)}, 1)
    return _print(result)


def cmd_clip(args) -> int:
    body = {"song_job_id": args.song, "mode": args.mode, "aspect": args.aspect, "lyrics_on_screen": not args.no_lyrics,
            "local_only": args.local_only, "budget_usd": args.budget, "notes": args.notes}
    with _client() as client:
        created = client.post("/api/v1/atelier/musicvideo", json=body)
        if created.status_code != 200:
            return _print({"stage": "estimate", "error": _detail(created)}, 1)
        state = created.json()
        project = state.get("project")
        amount = float((state.get("estimate") or {}).get("amount_usd") or 0)
        if not args.confirm:
            return _print({**state, "message": "Estimate only. Re-run with --confirm to start."}, 3 if amount > 0 else 0)
        if amount > args.budget:
            return _print({**state, "error": f"Estimate ${amount:.2f} exceeds --budget ${args.budget:.2f}"}, 3)
        confirmed = client.post(f"/api/v1/atelier/musicvideo/{project}/confirm")
        if confirmed.status_code != 200:
            return _print({"stage": "confirm", "project": project, "error": _detail(confirmed)}, 1)
        started = time.monotonic()
        while True:
            state = client.get(f"/api/v1/atelier/musicvideo/{project}").json()
            if state.get("status") in {"done", "failed", "interrupted"} or time.monotonic() - started > args.timeout:
                break
            print(f"[{int(time.monotonic() - started)}s] {state.get('stage')} {state.get('pct')}%", file=sys.stderr)
            time.sleep(5)
    return _print(state, 0 if state.get("status") == "done" else 1)


def cmd_library(_args) -> int:
    from app.services import jobs, library

    folders = []
    for job in jobs.list_recent(kind="song", limit=1000):
        folder = library.publish_song(job.id) if job.status == "completed" else None
        if folder:
            folders.append(str(folder))
    return _print({"root": str(library.library_root()), "songs": folders})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="meloforge", description="MeloForge song generation CLI (JSON output)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("readiness", help="Check the ACE-Step engine").set_defaults(func=cmd_readiness)

    jobs_cmd = sub.add_parser("jobs", help="List recent jobs")
    jobs_cmd.add_argument("--kind", choices=["song", "video", "composition"])
    jobs_cmd.add_argument("--limit", type=int, default=10)
    jobs_cmd.set_defaults(func=cmd_jobs)

    def song_brief(p):
        p.add_argument("--prompt", required=True, help="Style, instruments, emotion (ACE-Step caption)")
        p.add_argument("--title", default="")
        p.add_argument("--genre", default="")
        p.add_argument("--mood", default="")
        p.add_argument("--language", choices=["bg", "en"], default="bg")
        p.add_argument("--duration", type=int, default=90, help="Seconds (10-600)")

    lyrics_cmd = sub.add_parser("lyrics", help="Draft ACE-Step-tagged lyrics with the routed LLM")
    song_brief(lyrics_cmd)
    lyrics_cmd.add_argument("--provider", choices=["ollama", "openrouter", "novita", "nvidia", "huggingface"])
    lyrics_cmd.add_argument("--out", help="Write lyrics to this file")
    lyrics_cmd.add_argument("--themes", help='Trend themes, separated by ";" (from the trends command)')
    lyrics_cmd.set_defaults(func=cmd_lyrics)

    song_cmd = sub.add_parser("song", help="Generate, master and export a song")
    song_brief(song_cmd)
    group = song_cmd.add_mutually_exclusive_group()
    group.add_argument("--lyrics-file")
    group.add_argument("--lyrics")
    group.add_argument("--instrumental", action="store_true")
    song_cmd.add_argument("--bpm", type=int)
    song_cmd.add_argument("--key", help='e.g. "A minor", "C Major", "F#m"')
    song_cmd.add_argument("--time-signature", choices=["2", "3", "4", "6"])
    song_cmd.add_argument("--seed", type=int)
    song_cmd.add_argument("--steps", type=int, default=8, help="Turbo model: 1-20 (8 recommended)")
    song_cmd.add_argument("--preset", choices=["streaming", "apple", "broadcast"], default="streaming")
    song_cmd.add_argument("--max-cost", type=float, help="USD ceiling for a paid endpoint")
    song_cmd.add_argument("--yes", action="store_true", help="Confirm the quote")
    song_cmd.add_argument("--timeout", type=int, default=3600)
    song_cmd.add_argument("--out", help="Copy MP3/WAV/lyrics/report here")
    song_cmd.set_defaults(func=cmd_song)

    trends_cmd = sub.add_parser("trends", help="Chart trends for a genre (use --genre list for presets)")
    trends_cmd.add_argument("--genre", required=True)
    trends_cmd.add_argument("--language", choices=["bg", "en"], default="bg")
    trends_cmd.add_argument("--no-analyze", action="store_true", help="Chart statistics only, no LLM")
    trends_cmd.add_argument("--refresh", action="store_true", help="Ignore the 6 h cache")
    trends_cmd.add_argument("--provider", choices=["ollama", "openrouter", "novita", "nvidia", "huggingface"])
    trends_cmd.add_argument("--top", type=int, default=10)
    trends_cmd.set_defaults(func=cmd_trends)

    master_cmd = sub.add_parser("master", help="Loudness-master any audio file")
    master_cmd.add_argument("input")
    master_cmd.add_argument("--out")
    master_cmd.add_argument("--preset", choices=["streaming", "apple", "broadcast"], default="streaming")
    master_cmd.add_argument("--title", default="")
    master_cmd.add_argument("--genre", default="")
    master_cmd.set_defaults(func=cmd_master)

    sub.add_parser("voices", help="List voice profiles and the Seed-VC engine status").set_defaults(func=cmd_voices)
    voice_add = sub.add_parser("voice-add", help="Create a voice profile from a 10-30 s clean recording")
    voice_add.add_argument("input")
    voice_add.add_argument("--name", default="My voice")
    voice_add.add_argument("--i-own-this-voice", action="store_true", help="Required consent confirmation")
    voice_add.set_defaults(func=cmd_voice_add)
    sing_cmd = sub.add_parser("sing", help="Re-sing a finished song in a voice profile (local Seed-VC)")
    sing_cmd.add_argument("--song", required=True)
    sing_cmd.add_argument("--voice", required=True)
    sing_cmd.add_argument("--semitones", type=int, default=0)
    sing_cmd.add_argument("--voice-b", help="Second voice for a duet (verses alternate, choruses together)")
    sing_cmd.add_argument("--semitones-b", type=int, default=0)
    sing_cmd.add_argument("--choir", action="store_true", help="Choir on every chorus")
    sing_cmd.add_argument("--quality", choices=["fast", "balanced", "best"], default="balanced")
    sing_cmd.add_argument("--preset", choices=["streaming", "apple", "broadcast"], default="streaming")
    sing_cmd.add_argument("--out")
    sing_cmd.set_defaults(func=cmd_sing)

    sub.add_parser("library", help="Copy all finished songs to the readable library folder").set_defaults(func=cmd_library)
    export_cmd = sub.add_parser("export-song", help="Export a meloforge.song/1 package (song.json, master, aligned stems)")
    export_cmd.add_argument("song")
    export_cmd.add_argument("--to", help="Target folder (default: data/songs/<id>/package)")
    export_cmd.add_argument("--no-stems", action="store_true")
    export_cmd.set_defaults(func=cmd_export_song)
    clip_cmd = sub.add_parser("clip", help="Music video through Atelier (estimate first, --confirm to start)")
    clip_cmd.add_argument("song")
    clip_cmd.add_argument("--mode", choices=["stills", "mixed", "video"], default="mixed")
    clip_cmd.add_argument("--aspect", choices=["16x9", "9x16"], default="16x9")
    clip_cmd.add_argument("--no-lyrics", action="store_true")
    clip_cmd.add_argument("--local-only", action="store_true")
    clip_cmd.add_argument("--budget", type=float, default=1.05)
    clip_cmd.add_argument("--notes", default="")
    clip_cmd.add_argument("--confirm", action="store_true")
    clip_cmd.add_argument("--timeout", type=int, default=7200)
    clip_cmd.set_defaults(func=cmd_clip)
    return parser


def main(argv: list[str] | None = None) -> int:
    _use_desktop_profile()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
