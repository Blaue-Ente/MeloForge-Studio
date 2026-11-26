import { useEffect, useState } from "react";
import { JobProgress, type Progress } from "./JobProgress";
import { ArrowLeft, ArrowRight, Check, Clapperboard, Download, FolderOpen, Mic, Music2, RefreshCw, Sparkles, Wand2 } from "lucide-react";

type Genre = { id: string; label: string; caption: string; bpm: [number, number]; mood: string };
type Voice = { id: string; name: string };
type TextAi = { ready: boolean; local: { running: boolean; enabled: boolean; model: string; models: string[]; suggested: string | null }; cloud_configured: boolean };
type Job = { id: string; kind: string; status: string; quote_usd: number; progress?: Progress; error?: string | null; payload: { title?: string; duration_seconds?: number }; result?: { files?: Record<string, string>; library_dir?: string; formats?: string[] } | null };

const QUICK_GENRES = ["pop", "balkan", "folk", "rock", "hiphop", "dance"];
const LENGTHS = [{ id: 60, label: "Кратка", hint: "~1 мин." }, { id: 150, label: "Песен", hint: "~2:30 мин." }, { id: 210, label: "Дълга", hint: "~3:30 мин." }];
const STEPS = ["Идея", "Текст", "Глас", "Създаване", "Клип"];
const ACTIVE = ["queued", "running", "mastering", "awaiting_confirmation"];

async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = (data as { detail?: unknown }).detail;
    const message = typeof detail === "string" ? detail : (detail as { message?: string } | undefined)?.message;
    throw new Error(message || "Нещо не се получи. Опитай пак.");
  }
  return data as T;
}
const post = <T,>(url: string, body?: unknown) => api<T>(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });

export function FastMode({ apiOnline, onOpenStudio }: { apiOnline: boolean; onOpenStudio: () => void }) {
  const [step, setStep] = useState(0);
  const [genres, setGenres] = useState<Genre[]>([]);
  const [story, setStory] = useState("");
  const [genreId, setGenreId] = useState("pop");
  const [language, setLanguage] = useState<"bg" | "en">("bg");
  const [title, setTitle] = useState("");
  const [lyrics, setLyrics] = useState("");
  const [style, setStyle] = useState("");
  const [textAi, setTextAi] = useState<TextAi | null>(null);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [singer, setSinger] = useState("male");
  const [length, setLength] = useState(150);
  const [song, setSong] = useState<Job | null>(null);
  const [voiceJob, setVoiceJob] = useState<Job | null>(null);
  const [clip, setClip] = useState<Job | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => {
    void api<{ genres: Genre[] }>("/api/v1/music/genres").then((d) => setGenres(d.genres)).catch(() => undefined);
    void api<TextAi>("/api/v1/text-ai/status").then(setTextAi).catch(() => undefined);
    void api<{ voices: Voice[]; engine: { installed: boolean } }>("/api/v1/voices").then((d) => setVoices(d.engine.installed ? d.voices : [])).catch(() => undefined);
  }, []);

  const genre = genres.find((g) => g.id === genreId);
  const finalJob = voiceJob || song;

  // Poll whichever job is running.
  useEffect(() => {
    const running = [song, voiceJob, clip].find((job) => job && ["queued", "running", "mastering"].includes(job.status));
    if (!running) return;
    const timer = window.setTimeout(async () => {
      try {
        const next = await api<Job>(`/api/v1/jobs/${running.id}`);
        if (running === clip) setClip(next); else if (running === voiceJob) setVoiceJob(next); else setSong(next);
      } catch { /* next poll */ }
    }, 3000);
    return () => window.clearTimeout(timer);
  }, [song, voiceJob, clip]);

  // When the AI song is ready and "my voice" was chosen, re-sing it automatically.
  useEffect(() => {
    if (song?.status !== "completed" || voiceJob || !singer.startsWith("voice:")) return;
    void post<Job>("/api/v1/music/voice-swap", { song_job_id: song.id, voice_id: singer.slice(6), quality: "balanced" })
      .then(setVoiceJob).catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, [song, voiceJob, singer]);

  async function writeLyrics() {
    setBusy("lyrics"); setError(""); setNote("");
    try {
      const data = await post<{ lyrics: string; title?: string; style?: string; provider: string; model: string; warnings: string[] }>("/api/v1/music/lyrics", {
        prompt: `${genre?.caption || ""}`.trim() || "song", story, genre: genre?.label || "", mood: genre?.mood || "", language, duration_seconds: length,
      });
      setLyrics(data.lyrics);
      if (data.title && !title.trim()) setTitle(data.title);
      setStyle(data.style || "");
      setNote(`${data.warnings?.length ? `⚠ ${data.warnings.join(" ")} ` : ""}Написан от ${data.provider === "ollama" ? `локалния модел ${data.model} (безплатно)` : `${data.provider} · ${data.model}`}. Можеш да го промениш свободно.`);
    } catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); }
    finally { setBusy(""); }
  }

  async function useLocalAi() {
    setBusy("ai"); setError("");
    try { setTextAi(await post<TextAi>("/api/v1/text-ai/local")); }
    catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); }
    finally { setBusy(""); }
  }

  async function createSong() {
    setBusy("song"); setError(""); setSong(null); setVoiceJob(null); setClip(null);
    const vocal = singer === "female" ? "female lead vocal" : "male lead vocal";
    try {
      const quote = await post<Job>("/api/v1/jobs/song/quote", {
        title: title.trim() || story.split(/[.!?\n]/)[0].split(/\s+/).slice(0, 5).join(" "), prompt: `${style || genre?.caption || "song"}, ${vocal}`, genre: genre?.label || "",
        mood: genre?.mood || "", language, duration_seconds: length, lyrics, instrumental: false, master_preset: "streaming",
      });
      if (quote.quote_usd > 0) { setSong(quote); setStep(3); return; }  // paid engine: show the price and wait for a click
      setSong(await post<Job>(`/api/v1/jobs/${quote.id}/confirm`));
      setStep(3);
    } catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); }
    finally { setBusy(""); }
  }

  async function confirmPaid() {
    if (!song) return;
    setBusy("song");
    try { setSong(await post<Job>(`/api/v1/jobs/${song.id}/confirm`)); }
    catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); }
    finally { setBusy(""); }
  }

  async function makeClip(style: string) {
    if (!finalJob) return;
    setBusy("clip"); setError("");
    try { setClip(await post<Job>("/api/v1/media/visualizer", { song_job_id: finalJob.id, style, palette: "sunset", show_lyrics: true })); }
    catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); }
    finally { setBusy(""); }
  }

  function openFolder() {
    if (finalJob) void fetch(`/api/v1/library/open?job_id=${finalJob.id}`, { method: "POST" });
  }

  const songDone = finalJob?.status === "completed" && (!singer.startsWith("voice:") || Boolean(voiceJob));
  const working = [song, voiceJob].some((job) => job && ["queued", "running", "mastering"].includes(job.status)) || (singer.startsWith("voice:") && song?.status === "completed" && !voiceJob);
  const failed = [song, voiceJob].find((job) => job?.status === "failed");
  const canNext = [story.trim().length >= 5, lyrics.trim().length >= 20, true, Boolean(songDone), false][step];

  return <section className="fast-mode">
    <div className="fast-steps">{STEPS.map((label, index) => <button key={label} className={index === step ? "active" : index < step ? "done" : ""} disabled={index > step} onClick={() => setStep(index)}><span>{index < step ? <Check size={13} /> : index + 1}</span>{label}</button>)}</div>
    <div className="panel fast-card">
      {!apiOnline && <p className="inline-notice error-text">Приложението още стартира. Изчакай няколко секунди.</p>}

      {step === 0 && <>
        <h2>За какво да е песента?</h2>
        <p className="fast-hint">Напиши с няколко изречения: за кого е, какъв е поводът, какво да се случва в нея, имена и места. Може и кой я пее или представя.</p>
        <textarea className="fast-story" value={story} maxLength={1500} onChange={(event) => setStory(event.target.value)} placeholder="Например: Песен за рождения ден на баба Пенка от Враца. Тя прави най-хубавата баница и обича да танцува хоро. Пее я внукът ѝ Ники." />
        <p className="fast-label">Стил</p>
        <div className="chip-row">{QUICK_GENRES.map((id) => genres.find((g) => g.id === id)).filter(Boolean).map((g) => <button key={g!.id} className={genreId === g!.id ? "chip active" : "chip"} onClick={() => setGenreId(g!.id)}>{g!.label}</button>)}
          <select className="chip-select" value={QUICK_GENRES.includes(genreId) ? "" : genreId} onChange={(event) => event.target.value && setGenreId(event.target.value)}><option value="">Друг стил…</option>{genres.filter((g) => !QUICK_GENRES.includes(g.id)).map((g) => <option key={g.id} value={g.id}>{g.label}</option>)}</select></div>
        <p className="fast-label">Дължина</p>
        <div className="chip-row">{LENGTHS.map((item) => <button key={item.id} className={length === item.id ? "chip active" : "chip"} onClick={() => { setLength(item.id); setLyrics(""); }}>{item.label} <small>{item.hint}</small></button>)}</div>
        <p className="fast-label">Език</p>
        <div className="chip-row"><button className={language === "bg" ? "chip active" : "chip"} onClick={() => { setLanguage("bg"); setLyrics(""); }}>Български</button><button className={language === "en" ? "chip active" : "chip"} onClick={() => { setLanguage("en"); setLyrics(""); }}>English</button></div>
      </>}

      {step === 1 && <>
        <h2>Текстът на песента</h2>
        {textAi && !textAi.ready ? <div className="fast-callout">
          <b>Няма свързан AI за писане на текстове.</b>
          {textAi.local.running ? <p>На компютъра има Ollama с модел {textAi.local.suggested || textAi.local.models[0]}. Ползвай го безплатно — или добави облачен ключ (OpenRouter, под 1 цент на текст, по-добър български) от Resource Manager.</p>
            : <p>Стартирай Ollama (безплатно, локално) или добави облачен ключ в Resource Manager. Можеш и сам да напишеш текста отдолу.</p>}
          {textAi.local.running && <button className="primary-button" disabled={busy === "ai"} onClick={() => void useLocalAi()}><Sparkles size={15} />Ползвай локалния модел</button>}
        </div> : !lyrics && <p className="fast-hint">AI ще напише текст по твоята идея. Ще можеш да го промениш, преди да стане песен.</p>}
        <div className="fast-actions"><button className="primary-button" disabled={Boolean(busy) || (textAi !== null && !textAi.ready)} onClick={() => void writeLyrics()}>{busy === "lyrics" ? <><RefreshCw size={15} className="spin" />Пиша… (до минута)</> : lyrics ? <><RefreshCw size={15} />Напиши друг вариант</> : <><Wand2 size={15} />Напиши текста</>}</button></div>
        <label className="fast-label">Заглавие <span>по желание</span><input value={title} maxLength={120} onChange={(event) => setTitle(event.target.value)} placeholder="Ще го измисля сам или остави празно" /></label>
        <textarea className="fast-lyrics" value={lyrics} onChange={(event) => setLyrics(event.target.value)} placeholder={"[Verse 1]\nПърви куплет…\n\n[Chorus]\nПрипев…"} />
        {note && <p className="inline-notice">{note}</p>}
      </>}

      {step === 2 && <>
        <h2>Кой да я изпее?</h2>
        <div className="choice-grid">
          <button className={singer === "male" ? "choice active" : "choice"} onClick={() => setSinger("male")}><Music2 size={20} /><b>Мъжки AI глас</b><small>ACE-Step</small></button>
          <button className={singer === "female" ? "choice active" : "choice"} onClick={() => setSinger("female")}><Music2 size={20} /><b>Женски AI глас</b><small>ACE-Step</small></button>
          {voices.map((voice) => <button key={voice.id} className={singer === `voice:${voice.id}` ? "choice active" : "choice"} onClick={() => setSinger(`voice:${voice.id}`)}><Mic size={20} /><b>{voice.name}</b><small>клониран глас · +5–10 мин.</small></button>)}
        </div>
        {voices.length === 0 && <p className="fast-hint">Искаш песента с твоя глас? Запиши го веднъж в Music Studio → „Изпей с моя глас“ и ще се появи тук.</p>}
      </>}

      {step === 3 && <>
        <h2>{songDone ? "Песента е готова" : failed ? "Нещо се обърка" : "Създавам песента…"}</h2>
        {song?.status === "awaiting_confirmation" && song.quote_usd > 0 && <div className="fast-callout"><b>Тази генерация струва ${song.quote_usd.toFixed(2)}.</b><button className="primary-button" disabled={busy === "song"} onClick={() => void confirmPaid()}>Потвърди и създай</button></div>}
        {working && <><JobProgress progress={(voiceJob || song)?.progress} fallback={voiceJob ? "Пея песента с избрания глас…" : "ACE-Step композира и пее…"} /><p className="fast-hint">{voiceJob ? "Пея песента с избрания глас." : "ACE-Step композира и пее."} Можеш да оставиш прозореца отворен.</p></>}
        {failed && <p className="inline-notice error-text">{failed.error || "Генерацията не успя."}</p>}
        {songDone && finalJob?.result?.files?.mp3 && <>
          <audio className="generated-audio" controls src={finalJob.result.files.mp3} />
          <div className="fast-actions"><button className="secondary-button" onClick={openFolder}><FolderOpen size={15} />Отвори папката</button><a className="secondary-button" href={finalJob.result.files.mp3} download><Download size={15} />Изтегли MP3</a></div>
          <p className="fast-hint">Песента е записана и в Музика\MeloForge. Ако не ти харесва, върни се на „Текст“ или „Глас“ и опитай пак.</p>
        </>}
      </>}

      {step === 4 && <>
        <h2>Искаш ли видео към песента?</h2>
        <div className="choice-grid">
          <button className="choice" disabled={Boolean(busy) || Boolean(clip && ACTIVE.includes(clip.status))} onClick={() => void makeClip("spectrum")}><Clapperboard size={20} /><b>Безплатен клип</b><small>визуализация + текст · ~2 мин. на минута</small></button>
          <button className="choice" onClick={onOpenStudio}><Clapperboard size={20} /><b>Клип с картини</b><small>през Atelier · в Music Studio</small></button>
          <button className="choice" onClick={() => { setStep(0); setStory(""); setLyrics(""); setTitle(""); setSong(null); setVoiceJob(null); setClip(null); }}><Check size={20} /><b>Готово, нова песен</b><small>започни отначало</small></button>
        </div>
        {clip && ["queued", "running"].includes(clip.status) && <JobProgress progress={clip.progress} fallback="Рендерирам клипа 16:9 и 9:16…" />}
        {clip?.status === "failed" && <p className="inline-notice error-text">{clip.error}</p>}
        {clip?.status === "completed" && <><video className="generated-video" controls src={`/api/v1/media/${clip.id}/16x9`} /><div className="fast-actions"><a className="secondary-button" href={`/api/v1/media/${clip.id}/16x9`} download><Download size={15} />16:9 (YouTube)</a><a className="secondary-button" href={`/api/v1/media/${clip.id}/9x16`} download><Download size={15} />9:16 (Shorts/TikTok)</a><button className="secondary-button" onClick={openFolder}><FolderOpen size={15} />Отвори папката</button></div></>}
      </>}

      {error && <p className="inline-notice error-text" role="alert">{error}</p>}
      <div className="fast-nav">
        <button className="secondary-button" disabled={step === 0 || working} onClick={() => setStep(step - 1)}><ArrowLeft size={15} />Назад</button>
        {step === 2 ? <button className="primary-button large" disabled={!apiOnline || Boolean(busy) || lyrics.trim().length < 20} onClick={() => void createSong()}><Sparkles size={16} />{busy === "song" ? "Стартирам…" : "Създай песента"}</button>
          : step < 4 && <button className="primary-button large" disabled={!canNext} onClick={() => { setError(""); setStep(step + 1); if (step === 0 && !lyrics && textAi?.ready) void writeLyrics(); }}>Напред<ArrowRight size={15} /></button>}
      </div>
    </div>
  </section>;
}
