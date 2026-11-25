import { useEffect, useRef, useState } from "react";
import { Mic, Square, Trash2, Upload, UserRound } from "lucide-react";

type Voice = { id: string; name: string; reference_seconds: number; created_at: number };
type Engine = { installed: boolean; models_downloaded: boolean; install_hint: string | null; license: string };
type SongLike = { id: string; status: string; payload: { instrumental?: boolean; mode?: string } };

const MAX_RECORD_SECONDS = 30;
const READ_ALOUD = "Прочети спокойно и ясно, на нормален глас: „Днес е хубав ден. Слънцето грее над града, а аз пея любимата си песен. Музиката ме кара да се чувствам свободен и щастлив.“ Ако можеш, изпей и няколко реда — така тембърът на пеене се улавя по-добре.";

export function VoiceStudio({ song, onCreated }: { song: SongLike; onCreated: (job: never) => void }) {
  const [engine, setEngine] = useState<Engine | null>(null);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [voiceId, setVoiceId] = useState("");
  const [semitones, setSemitones] = useState(0);
  const [quality, setQuality] = useState("balanced");
  const [name, setName] = useState("Моят глас");
  const [consent, setConsent] = useState(false);
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [pending, setPending] = useState<{ blob: Blob; filename: string; url: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const recorder = useRef<MediaRecorder | null>(null);
  const timer = useRef<number | null>(null);

  const load = () => fetch("/api/v1/voices").then((response) => response.json()).then((data) => {
    setEngine(data.engine); setVoices(data.voices || []);
    setVoiceId((current) => current && (data.voices || []).some((item: Voice) => item.id === current) ? current : data.voices?.[0]?.id || "");
  }).catch(() => undefined);
  useEffect(() => { void load(); return () => { if (timer.current) window.clearInterval(timer.current); }; }, []);

  async function startRecording() {
    setError(""); setPending(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: true, autoGainControl: false } });
      const chunks: Blob[] = [];
      const media = new MediaRecorder(stream);
      media.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
      media.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        const blob = new Blob(chunks, { type: media.mimeType || "audio/webm" });
        setPending({ blob, filename: media.mimeType.includes("ogg") ? "recording.ogg" : media.mimeType.includes("mp4") ? "recording.m4a" : "recording.webm", url: URL.createObjectURL(blob) });
        setRecording(false); if (timer.current) window.clearInterval(timer.current);
      };
      recorder.current = media; media.start(); setRecording(true); setSeconds(0);
      timer.current = window.setInterval(() => setSeconds((value) => { if (value + 1 >= MAX_RECORD_SECONDS) recorder.current?.stop(); return value + 1; }), 1000);
    } catch { setError("Няма достъп до микрофона. Разреши го в браузъра или качи готов файл."); }
  }

  function chooseFile(file: File | undefined) {
    if (!file) return;
    setError(""); setPending({ blob: file, filename: file.name, url: URL.createObjectURL(file) });
  }

  async function saveVoice() {
    if (!pending) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const query = new URLSearchParams({ name, filename: pending.filename, consent: String(consent) });
      const response = await fetch(`/api/v1/voices?${query}`, { method: "POST", headers: { "Content-Type": pending.blob.type || "application/octet-stream" }, body: pending.blob });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Гласът не беше запазен.");
      setPending(null); setConsent(false); setNotice(`✓ „${data.name}“ е запазен (${data.reference_seconds} сек. чист глас).`); setVoiceId(data.id); await load();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Гласът не беше запазен."); }
    finally { setBusy(false); }
  }

  async function removeVoice(id: string) {
    if (!window.confirm("Да изтрия ли този гласов профил? Записът се премахва от диска.")) return;
    await fetch(`/api/v1/voices/${id}/delete`, { method: "POST" }).catch(() => undefined);
    await load();
  }

  async function singInVoice() {
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/v1/music/voice-swap", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ song_job_id: song.id, voice_id: voiceId, semitones, quality }) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Обработката не започна.");
      window.localStorage.setItem("meloforge.latestSongJob", data.id);
      onCreated(data as never);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Обработката не започна."); }
    finally { setBusy(false); }
  }

  if (song.payload.instrumental) return null;
  return <details className="engine-settings voice-studio"><summary><UserRound size={15} /> Изпей с моя глас</summary>
    <p>Вокалът на песента се отделя от музиката и се преобразува в твоя тембър (Seed-VC, локално, $0). Мелодията и текстът остават същите, затова работи и на български.</p>
    {engine && !engine.installed && <p className="inline-notice error-text">Seed-VC не е инсталиран. {engine.install_hint}</p>}
    {engine?.installed && !engine.models_downloaded && <p className="inline-notice">Първото пускане тегли моделите (~1 GB) — отнема няколко минути.</p>}
    {voices.length > 0 && <><div className="voice-list">{voices.map((voice) => <div key={voice.id} className={voice.id === voiceId ? "voice-item active" : "voice-item"}><button onClick={() => setVoiceId(voice.id)}><b>{voice.name}</b><small>{voice.reference_seconds} сек.</small></button><audio src={`/api/v1/voices/${voice.id}/sample`} controls preload="none" /><button className="icon-button" title="Изтрий" onClick={() => void removeVoice(voice.id)}><Trash2 size={14} /></button></div>)}</div>
      <div className="form-grid"><label>Височина <span>{semitones > 0 ? `+${semitones}` : semitones} полутона</span><input className="slider" type="range" min="-12" max="12" step="1" value={semitones} onChange={(event) => setSemitones(Number(event.target.value))} /></label><label>Качество<select value={quality} onChange={(event) => setQuality(event.target.value)}><option value="fast">Бързо (чернова)</option><option value="balanced">Балансирано</option><option value="best">Най-добро (по-бавно)</option></select></label></div>
      <p className="inline-notice">Мъжки глас върху женски вокал: −5 до −12. Женски върху мъжки: +5 до +12.</p>
      <button className="primary-button large" disabled={busy || !engine?.installed || !voiceId || song.status !== "completed"} onClick={() => void singInVoice()}><Mic size={17} />{busy ? "Стартирам…" : "Изпей песента с този глас"}</button></>}
    <div className="voice-add"><b>{voices.length ? "Добави нов глас" : "Създай своя глас"}</b>
      <p className="inline-notice">{READ_ALOUD} Нужни са 10–30 сек. в тиха стая, без музика и ехо.</p>
      <div className="assembly-links">{recording ? <button className="primary-button" onClick={() => recorder.current?.stop()}><Square size={15} />Спри ({seconds}/{MAX_RECORD_SECONDS} сек.)</button> : <button className="secondary-button" disabled={busy} onClick={() => void startRecording()}><Mic size={15} />Запиши с микрофона</button>}
        <label className="secondary-button file-button"><Upload size={15} />Качи файл<input type="file" accept="audio/*" hidden onChange={(event) => chooseFile(event.target.files?.[0])} /></label></div>
      {pending && <><audio className="generated-audio" src={pending.url} controls /><label>Име на гласа<input value={name} onChange={(event) => setName(event.target.value)} maxLength={60} /></label>
        <label className="checkline"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} /> Потвърждавам, че това е моят глас или имам изричното съгласие на човека. Няма да го използвам, за да се представям за друг.</label>
        <button className="primary-button" disabled={busy || !consent} onClick={() => void saveVoice()}>{busy ? "Обработвам…" : "Запази гласа"}</button></>}
    </div>
    {notice && <p className="inline-notice" role="status">{notice}</p>}
    {error && <p className="inline-notice error-text" role="alert">{error}</p>}
  </details>;
}
