import { useEffect, useState, type ReactNode } from "react";
import { Activity, AlertCircle, AudioLines, CheckCircle2, Cloud, Cpu, Gauge, HardDrive, Layers3, Play, RefreshCw, ShieldCheck, SlidersHorizontal, Sparkles, Video, WandSparkles } from "lucide-react";

type View = "control" | "music" | "video";
type Mode = "local_first" | "hybrid" | "cloud_quality";
type Provider = { id: string; name: string; description: string; configured: boolean; model: string | null; pricing_configured: boolean; input_usd_per_1m?: number; output_usd_per_1m?: number; video_cost_per_second_usd?: number | null; kind: "local" | "cloud" };
type Resources = { ram_total_gb: number; ram_available_gb: number; gpu: { detected: boolean; vram_total_gb: number | null; vram_available_gb: number | null } };
type Check = { id: string; label: string; ok: boolean; detail: string };
type SongJob = { id: string; kind: string; status: string; quote_usd: number; payload: { title: string; prompt: string; genre: string; mood: string; language: string; duration_seconds: number; lyrics: string }; provider_task_id?: string | null; result?: { audio_url?: string; lyrics?: string; metadata?: Record<string, unknown> } | null; error?: string | null; estimate_note?: string; max_cost_usd?: number };
type VideoJob = { id: string; kind: string; status: string; quote_usd: number; payload: { prompt: string; duration: number; size: string }; provider_task_id?: string | null; result?: { video_urls?: string[] } | null; error?: string | null; estimate_note?: string; max_cost_usd?: number };
type MediaJob = { id: string; kind: string; status: string; payload: { song_job_id: string; video_job_id: string }; result?: { formats?: string[]; duration_seconds?: number; lyrics_available?: boolean } | null; error?: string | null };

const fallback: Provider[] = [
  { id: "ollama", name: "Ollama", description: "Local LLM", configured: false, model: null, pricing_configured: true, kind: "local" },
  { id: "openrouter", name: "OpenRouter", description: "LLM routing", configured: false, model: null, pricing_configured: false, kind: "cloud" },
  { id: "novita", name: "Novita", description: "LLM and video API", configured: false, model: null, pricing_configured: false, kind: "cloud" },
  { id: "nvidia", name: "NVIDIA", description: "NVIDIA NIM", configured: false, model: null, pricing_configured: false, kind: "cloud" },
  { id: "huggingface", name: "Hugging Face", description: "Inference Providers", configured: false, model: null, pricing_configured: false, kind: "cloud" },
];

export default function App() {
  const [view, setView] = useState<View>("control"); const [providers, setProviders] = useState(fallback); const [resources, setResources] = useState<Resources | null>(null); const [checks, setChecks] = useState<Check[]>([]);
  const [mode, setMode] = useState<Mode>("hybrid"); const [budget, setBudget] = useState(2); const [fallbackAllowed, setFallbackAllowed] = useState(true); const [loading, setLoading] = useState(false); const [saving, setSaving] = useState(false); const [api, setApi] = useState<"loading" | "online" | "offline">("loading"); const [notice, setNotice] = useState("");
  async function refresh() { setLoading(true); try { const [p, r, d, m] = await Promise.all([fetch("/api/v1/providers"), fetch("/api/v1/resources"), fetch("/api/v1/diagnostics"), fetch("/api/v1/music/readiness")]); if (!p.ok || !r.ok || !d.ok) throw new Error("offline"); const [pd, rd, dd, md] = await Promise.all([p.json(), r.json(), d.json(), m.ok ? m.json() : Promise.resolve({ ready: false, reason: "Проверка е недостъпна." })]); setProviders(pd.providers); setMode(pd.default_mode); setBudget(pd.max_task_budget_usd); setFallbackAllowed(pd.allow_cloud_fallback); setResources(rd); setChecks([...dd.checks, { id: "ace_step", label: "ACE-Step music engine", ok: Boolean(md.ready), detail: md.ready ? `Модел ${md.model} е зареден` : (md.reason || "Не е готов") }]); setApi("online"); } catch { setApi("offline"); setResources(null); setProviders(fallback); setChecks([]); } finally { setLoading(false); } }
  async function savePreferences() { setSaving(true); setNotice(""); try { const response = await fetch("/api/v1/settings", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ default_mode: mode, max_task_budget_usd: budget, allow_cloud_fallback: fallbackAllowed }) }); if (!response.ok) throw new Error("save failed"); const data = await response.json(); setMode(data.default_mode); setBudget(data.max_task_budget_usd); setFallbackAllowed(data.allow_cloud_fallback); setNotice("Настройките са запазени локално. API ключове не се записват тук."); } catch { setNotice("Настройките не бяха записани. Провери дали backend работи."); } finally { setSaving(false); } }
  useEffect(() => { void refresh(); }, []);
  const configured = providers.filter((p) => p.configured).length; const cloudCount = providers.filter((p) => p.kind === "cloud" && p.configured).length;
  return <div className="shell"><aside className="sidebar"><div className="brand"><div className="brand-icon"><AudioLines /></div><div><b>MeloForge</b><small>STUDIO</small></div></div><p className="side-label">WORKSPACE</p><nav><Nav active={view === "control"} icon={<Layers3 size={17} />} label="Resource Manager" onClick={() => setView("control")} /><Nav active={view === "music"} icon={<AudioLines size={17} />} label="Music Studio" onClick={() => setView("music")} /><Nav active={view === "video"} icon={<Video size={17} />} label="Music Video" onClick={() => setView("video")} /></nav><div className="side-note"><ShieldCheck size={16} /> Ключовете остават локално</div></aside><main><header><div><small className="eyebrow">MELOFORGE / {view === "control" ? "CONTROL CENTER" : view.toUpperCase()}</small><h1>{view === "control" ? "AI Resource Manager" : view === "music" ? "Music Studio" : "Music Video Studio"}</h1></div><div className="actions"><span className={`api ${api}`}><i />{api === "online" ? "API свързан" : api === "offline" ? "API недостъпен" : "Проверка…"}</span><button className="refresh" onClick={() => void refresh()} disabled={loading} aria-label="Обнови"><RefreshCw size={17} /></button></div></header>{view === "control" && <ControlCenter resources={resources} providers={providers} checks={checks} configured={configured} cloudCount={cloudCount} mode={mode} setMode={setMode} budget={budget} setBudget={setBudget} fallbackAllowed={fallbackAllowed} setFallbackAllowed={setFallbackAllowed} savePreferences={() => void savePreferences()} saving={saving} notice={notice} loading={loading} refreshProviders={() => void refresh()} />}{view === "music" && <MusicStudio apiOnline={api === "online"} />}{view === "video" && <VideoStudio apiOnline={api === "online"} checks={checks} />}<footer>MELOFORGE STUDIO <span>Adaptive local + cloud AI architecture</span><span>v0.4.0</span></footer></main></div>;
}

function ControlCenter({ resources, providers, checks, configured, cloudCount, mode, setMode, budget, setBudget, fallbackAllowed, setFallbackAllowed, savePreferences, saving, notice, loading, refreshProviders }: { resources: Resources | null; providers: Provider[]; checks: Check[]; configured: number; cloudCount: number; mode: Mode; setMode: (value: Mode) => void; budget: number; setBudget: (value: number) => void; fallbackAllowed: boolean; setFallbackAllowed: (value: boolean) => void; savePreferences: () => void; saving: boolean; notice: string; loading: boolean; refreshProviders: () => void }) {
  return <><section className="hero"><div><small className="eyebrow">ADAPTIVE AI PIPELINE</small><h2>Качествен резултат.<br /><span>Контролирана цена.</span></h2><p>Локалните задачи използват RAM и GPU; тежките генерации преминават към облак само при наличен модел, цена и бюджет.</p></div><div className="hero-art"><div className="ring" /><div className="core"><Sparkles size={29} /></div></div></section><div className="section-head"><div><small className="eyebrow">LIVE OVERVIEW</small><h3>Състояние на системата</h3></div><span>{loading ? "Обновяване…" : "Проверено при отваряне"}</span></div><section className="metrics"><Metric icon={<Cpu />} label="GPU" value={resources?.gpu.detected ? `${resources.gpu.vram_total_gb} GB` : "Не е открита"} detail={resources?.gpu.detected ? `${resources.gpu.vram_available_gb} GB свободни` : "Изисква nvidia-smi"} /><Metric icon={<HardDrive />} label="RAM" value={resources ? `${resources.ram_total_gb} GB` : "—"} detail={resources ? `${resources.ram_available_gb} GB свободни` : "Няма данни"} /><Metric icon={<Activity />} label="Доставчици" value={`${configured} / ${providers.length}`} detail={`${cloudCount} облачни конфигурирани`} /><Metric icon={<Gauge />} label="Лимит на задача" value={`$${budget.toFixed(2)}`} detail="Таван за една задача" /></section><section className="columns"><div className="panel"><div className="panel-head"><div><small className="eyebrow">ROUTING POLICY</small><h3>Стратегия за генериране</h3></div><SlidersHorizontal /></div><div className="modes">{([ ["local_first", "Local First", "Локално първо; облак само при разрешен fallback"], ["hybrid", "Smart Hybrid", "Локално за леки задачи, облак за тежките"], ["cloud_quality", "Cloud Quality", "Предпочитан облачен модел с бюджетен контрол"] ] as const).map(([id, title, sub]) => <button key={id} className={`mode ${mode === id ? "selected" : ""}`} onClick={() => setMode(id)}><span className="radio" /><span><b>{title}{id === "hybrid" && <i>Recommended</i>}</b><small>{sub}</small></span></button>)}</div><div className="budget-head"><div><b>Максимална цена за задача</b><small>Генерацията се блокира над тази сума</small></div><strong>${budget.toFixed(2)}</strong></div><input className="slider" aria-label="Максимална цена" type="range" min="0.1" max="20" step="0.1" value={budget} onChange={(e) => setBudget(Number(e.target.value))} /><div className="range-labels"><span>$0.10</span><span>$20.00</span></div><label className="checkline"><input type="checkbox" checked={fallbackAllowed} onChange={(e) => setFallbackAllowed(e.target.checked)} /> Разреши cloud fallback при недостъпен локален модел</label><button className="primary-button" disabled={saving} onClick={savePreferences}>{saving ? "Запазване…" : "Запази настройките"}</button>{notice && <p className="inline-notice">{notice}</p>}</div><div className="panel"><div className="panel-head"><div><small className="eyebrow">MODEL CONNECTORS</small><h3>AI доставчици</h3></div><span className="count">{configured} активни</span></div><div className="providers">{providers.map((p) => <ProviderRow key={p.id} p={p} />)}</div><ProviderConnector providers={providers} onSaved={refreshProviders} /><p className="hint">Ключът се предава локално и се шифрова с Windows DPAPI за текущия профил. Не се записва във файловете на проекта.</p></div></section><section className="panel diagnostics"><div className="panel-head"><div><small className="eyebrow">SAFE PRE-FLIGHT</small><h3>Диагностика и готовност</h3></div><span className="count">{checks.filter((check) => check.ok).length} / {checks.length || 5} готови</span></div><div className="check-grid">{checks.length ? checks.map((check) => <div className="check" key={check.id}>{check.ok ? <CheckCircle2 /> : <AlertCircle />}<span><b>{check.label}</b><small>{check.detail}</small></span></div>) : <p className="hint">Стартирай backend, за да видиш диагностика.</p>}</div></section><section className="panel roadmap"><div className="panel-head"><div><small className="eyebrow">PIPELINE ROADMAP</small><h3>Състояние на модулите</h3></div></div><div className="roadmaps"><Roadmap icon={<AudioLines />} title="Song Builder" sub="ACE-Step + текст + аудио" status="Свързва се" /><Roadmap icon={<Video />} title="AI Music Video" sub="Novita Wan 2.2 · оферта + потвърждение" status="Адаптер готов" /><Roadmap icon={<Layers3 />} title="Media Composer" sub="FFmpeg монтаж към цялата песен" status="Локален монтаж" /></div></section></>;
}

function ProviderConnector({ providers, onSaved }: { providers: Provider[]; onSaved: () => void }) {
  const [provider, setProvider] = useState<"openrouter" | "novita" | "nvidia" | "huggingface">("novita");
  const [apiKey, setApiKey] = useState(""); const [model, setModel] = useState(""); const [inputRate, setInputRate] = useState(0); const [outputRate, setOutputRate] = useState(0); const [videoRate, setVideoRate] = useState(0);
  const [saving, setSaving] = useState(false); const [notice, setNotice] = useState(""); const [failed, setFailed] = useState(false);
  const activeProvider = providers.find((item) => item.id === provider);
  useEffect(() => { setModel(activeProvider?.model || ""); setInputRate(activeProvider?.input_usd_per_1m || 0); setOutputRate(activeProvider?.output_usd_per_1m || 0); setVideoRate(activeProvider?.video_cost_per_second_usd || 0); setNotice(""); }, [activeProvider, provider]);
  async function saveProvider() {
    setSaving(true); setNotice(""); setFailed(false);
    try {
      const body = { provider, api_key: apiKey, model, input_usd_per_1m: inputRate, output_usd_per_1m: outputRate, ...(provider === "novita" ? { novita_video_cost_per_second_usd: videoRate } : {}) };
      const response = await fetch("/api/v1/providers/configure", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Настройката не беше записана.");
      setApiKey(""); setNotice(`${data.provider.name} е свързан. Ключът е шифрован за този Windows профил.`); onSaved();
    } catch (error) { setFailed(true); setNotice(error instanceof Error ? error.message : "Настройката не беше записана."); }
    finally { setSaving(false); }
  }
  return <div className="provider-connect"><div className="connect-heading"><b>Свържи или обнови доставчик</b><small>Ключът не се връща обратно от backend.</small></div><label>Доставчик<select value={provider} onChange={(event) => setProvider(event.target.value as typeof provider)}><option value="novita">Novita</option><option value="openrouter">OpenRouter</option><option value="nvidia">NVIDIA NIM</option><option value="huggingface">Hugging Face</option></select></label><label>API ключ<input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} autoComplete="new-password" placeholder="Постави нов или завъртян ключ" /></label><label>Model ID<input value={model} onChange={(event) => setModel(event.target.value)} placeholder="ID от каталога на доставчика" /></label><div className="form-grid"><label>Вход · USD / 1M токена<input type="number" min="0" step="0.0001" value={inputRate} onChange={(event) => setInputRate(Number(event.target.value))} /></label><label>Изход · USD / 1M токена<input type="number" min="0" step="0.0001" value={outputRate} onChange={(event) => setOutputRate(Number(event.target.value))} /></label></div>{provider === "novita" && <label>Wan 2.2 · USD / секунда<input type="number" min="0" step="0.001" value={videoRate} onChange={(event) => setVideoRate(Number(event.target.value))} /></label>}<button className="primary-button" disabled={saving || apiKey.trim().length < 8 || !model.trim()} onClick={() => void saveProvider()}>{saving ? "Запазване…" : "Запази ключа и модела"}</button>{notice && <p className={`inline-notice ${failed ? "error-text" : ""}`} role={failed ? "alert" : "status"}>{notice}</p>}</div>;
}

function MusicStudio({ apiOnline }: { apiOnline: boolean }) {
  const [prompt, setPrompt] = useState("Мелодична песен за нощно пътуване през неонов град, с надежден и кинематографичен припев.");
  const [title, setTitle] = useState(""); const [genre, setGenre] = useState("Synthwave"); const [mood, setMood] = useState("Cinematic");
  const [duration, setDuration] = useState(45); const [language, setLanguage] = useState<"bg" | "en">("bg"); const [lyrics, setLyrics] = useState("");
  const [readiness, setReadiness] = useState<{ ready: boolean; reason?: string; model?: string; base_url?: string; models?: string[] }>({ ready: false });
  const [engineUrl, setEngineUrl] = useState("http://127.0.0.1:8001"); const [engineModel, setEngineModel] = useState("acestep-v15-turbo"); const [engineKey, setEngineKey] = useState(""); const [engineRate, setEngineRate] = useState(0); const [engineSaving, setEngineSaving] = useState(false); const [engineNotice, setEngineNotice] = useState("");
  const [job, setJob] = useState<SongJob | null>(null); const [busy, setBusy] = useState(false); const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    void fetch("/api/v1/music/readiness").then((response) => response.json()).then((data) => { if (alive) { setReadiness(data); setEngineUrl(data.base_url || "http://127.0.0.1:8001"); setEngineModel(data.model || "acestep-v15-turbo"); } }).catch(() => { if (alive) setReadiness({ ready: false, reason: "Backend не е достъпен." }); });
    const savedId = window.localStorage.getItem("meloforge.latestSongJob");
    if (savedId) void fetch(`/api/v1/jobs/${savedId}`).then((response) => response.ok ? response.json() : null).then((data) => { if (alive && data?.kind === "song") setJob(data); }).catch(() => undefined);
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!job || job.status !== "running") return;
    const timer = window.setTimeout(async () => {
      try { const response = await fetch(`/api/v1/jobs/${job.id}`); if (response.ok) setJob(await response.json()); }
      catch { /* A temporary polling error leaves the job available for the next refresh. */ }
    }, 3000);
    return () => window.clearTimeout(timer);
  }, [job]);

  async function quoteSong() {
    setBusy(true); setError(""); setJob(null);
    try {
      const response = await fetch("/api/v1/jobs/song/quote", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title, prompt, genre, mood, language, duration_seconds: duration, lyrics }) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Неуспешна ценова оценка.");
      setJob(data); window.localStorage.setItem("meloforge.latestSongJob", data.id);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Неуспешна проверка на ACE-Step."); }
    finally { setBusy(false); }
  }

  async function configureEngine() {
    setEngineSaving(true); setEngineNotice("");
    try {
      const response = await fetch("/api/v1/music/configure", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ base_url: engineUrl, model: engineModel, api_key: engineKey || null, cost_per_second_usd: engineRate }) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "ACE-Step настройките не бяха запазени.");
      setReadiness(data.readiness); setEngineKey(""); setEngineNotice(data.readiness.ready ? "ACE-Step е свързан и готов." : "Настройката е запазена. Стартирай endpoint и зареди избрания модел.");
    } catch (caught) { setEngineNotice(caught instanceof Error ? caught.message : "Настройката не беше запазена."); }
    finally { setEngineSaving(false); }
  }

  async function confirmSong() {
    if (!job || job.status !== "awaiting_confirmation") return;
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/v1/jobs/${job.id}/confirm`, { method: "POST" }); const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "ACE-Step не прие задачата.");
      setJob(data);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Неуспешно изпращане към ACE-Step."); }
    finally { setBusy(false); }
  }

  const stateLabel = job?.status === "awaiting_confirmation" ? "Чака потвърждение" : job?.status === "queued" ? "На опашка" : job?.status === "running" ? "Генерира се" : job?.status === "completed" ? "Готова песен" : "Неуспешно";
  return <section className="studio-layout"><div className="studio-intro"><small className="eyebrow">SONG BUILDER</small><h2>Текст и музика<br /><span>в един поток.</span></h2><p>ACE-Step генерира песента и може да напише текста, ако оставиш полето празно. Първо се проверява моделът и цената; заявката се изпраща само след потвърждение.</p><div className="safety-strip"><ShieldCheck /> Ключът се предава локално и се пази криптиран за този Windows профил.</div><div className="preflight"><b>{readiness.model || "ACE-Step"}</b><span className={readiness.ready ? "good" : "warn"}>{readiness.ready ? "Свързан и готов" : "Не е готов"}</span></div>{!readiness.ready && <p className="inline-notice">{readiness.reason || "Настрой endpoint и стартирай ACE-Step."}</p>}</div><div className="panel composer"><details className="engine-settings" open={!readiness.ready}><summary>Настрой музикалния engine</summary><p>Инсталирай и стартирай ACE-Step 1.5 API. За локален адрес не се начислява API цена; отдалечен endpoint изисква зададена тарифа.</p><label>ACE-Step API адрес<input value={engineUrl} onChange={(event) => setEngineUrl(event.target.value)} placeholder="http://127.0.0.1:8001" /></label><label>Модел<select value={engineModel} onChange={(event) => setEngineModel(event.target.value)}>{readiness.models?.length ? readiness.models.map((name) => <option key={name} value={name}>{name}</option>) : <option value={engineModel}>{engineModel}</option>}</select></label><label>API ключ <span>по избор</span><input type="password" value={engineKey} onChange={(event) => setEngineKey(event.target.value)} autoComplete="new-password" placeholder="Ключ за private endpoint" /></label><label>Цена · USD / секунда<input type="number" min="0" step="0.001" value={engineRate} onChange={(event) => setEngineRate(Number(event.target.value))} /></label><button className="primary-button" disabled={engineSaving || !engineUrl.trim() || !engineModel.trim()} onClick={() => void configureEngine()}>{engineSaving ? "Запазване…" : "Запази и провери връзката"}</button>{engineNotice && <p className="inline-notice" role="status">{engineNotice}</p>}</details><div className="form-grid"><label>Заглавие<input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={120} placeholder="По желание" /></label><label>Език на текста<select value={language} onChange={(event) => setLanguage(event.target.value as "bg" | "en")}><option value="bg">Български</option><option value="en">English</option></select></label></div><label>Идея за песента<textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} maxLength={1200} /></label><div className="form-grid"><label>Жанр<input value={genre} onChange={(event) => setGenre(event.target.value)} maxLength={80} /></label><label>Настроение<input value={mood} onChange={(event) => setMood(event.target.value)} maxLength={80} /></label></div><label>Текст на песента <span>празно = генерирай автоматично</span><textarea className="lyrics-input" value={lyrics} onChange={(event) => setLyrics(event.target.value)} maxLength={10000} placeholder="Можеш да добавиш свой текст на български или английски…" /></label><label>Дължина <span>{duration} сек.</span><input className="slider" type="range" min="10" max="180" step="5" value={duration} onChange={(event) => setDuration(Number(event.target.value))} /></label><button className="primary-button large" disabled={!apiOnline || !readiness.ready || busy || prompt.trim().length < 3} onClick={() => void quoteSong()}><WandSparkles size={17} />{busy ? "Проверка…" : "Изчисли цена"}</button>{!apiOnline && <p className="inline-notice">Backend е офлайн.</p>}{error && <p className="inline-notice error-text" role="alert">{error}</p>}{job && <div className="job-card"><div className="job-head"><span className={`job-state ${job.status}`}>{stateLabel}</span><strong>${job.quote_usd.toFixed(4)}</strong></div><p>{job.estimate_note || `ACE-Step · ${job.payload.duration_seconds}s · ${job.payload.language === "bg" ? "български" : "English"}`}</p>{job.status === "awaiting_confirmation" && <button className="primary-button large" disabled={busy} onClick={() => void confirmSong()}><ShieldCheck size={17} />Потвърди и създай песента</button>}{job.status === "running" && <p className="inline-notice">ACE-Step задача {job.provider_task_id || "изпратена"}. Проверявам статуса автоматично.</p>}{job.status === "failed" && <p className="inline-notice error-text">{job.error || "Генерацията не беше успешна."}</p>}{job.status === "completed" && job.result?.audio_url && <><audio className="generated-audio" src={job.result.audio_url} controls /><details className="lyrics-result"><summary>Покажи текста на песента</summary><pre>{job.result.lyrics || job.payload.lyrics || "ACE-Step не върна текст в резултата."}</pre></details></>}</div>}</div></section>;
}
function VideoStudio({ apiOnline, checks }: { apiOnline: boolean; checks: Check[] }) {
  const ffmpeg = checks.find((check) => check.id === "ffmpeg");
  const [prompt, setPrompt] = useState("Cinematic night drive through a neon-lit European city, emotional and atmospheric, slow camera movement");
  const [duration, setDuration] = useState<5 | 8>(5);
  const [size, setSize] = useState("1280*720");
  const [job, setJob] = useState<VideoJob | null>(null);
  const [songJob, setSongJob] = useState<SongJob | null>(null);
  const [mediaJob, setMediaJob] = useState<MediaJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    const savedVideoId = window.localStorage.getItem("meloforge.latestVideoJob");
    const savedSongId = window.localStorage.getItem("meloforge.latestSongJob");
    const savedMediaId = window.localStorage.getItem("meloforge.latestCompositionJob");
    const restore = async (id: string | null, accept: (data: any) => void, kind: string) => {
      if (!id) return;
      try {
        const response = await fetch(`/api/v1/jobs/${id}`);
        const data = response.ok ? await response.json() : null;
        if (alive && data?.kind === kind) accept(data);
      } catch { /* Keep the studio usable when saved jobs cannot be restored. */ }
    };
    void Promise.all([
      restore(savedVideoId, setJob, "video"),
      restore(savedSongId, setSongJob, "song"),
      restore(savedMediaId, setMediaJob, "composition"),
    ]);
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (![job?.status, songJob?.status, mediaJob?.status].some((status) => status === "running" || status === "queued")) return;
    const timer = window.setTimeout(async () => {
      const poll = async (id: string, apply: (data: any) => void) => {
        try { const response = await fetch(`/api/v1/jobs/${id}`); if (response.ok) apply(await response.json()); }
        catch { /* Keep the previous state; the next poll can recover. */ }
      };
      await Promise.all([
        job?.status === "running" ? poll(job.id, setJob) : Promise.resolve(),
        songJob?.status === "running" ? poll(songJob.id, setSongJob) : Promise.resolve(),
        mediaJob && ["running", "queued"].includes(mediaJob.status) ? poll(mediaJob.id, setMediaJob) : Promise.resolve(),
      ]);
    }, 3000);
    return () => window.clearTimeout(timer);
  }, [job, songJob, mediaJob]);

  async function getQuote() {
    setBusy(true); setError(""); setJob(null);
    try {
      const response = await fetch("/api/v1/jobs/video/quote", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt, duration, size }) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Неуспешна ценова оценка.");
      setJob(data);
      window.localStorage.setItem("meloforge.latestVideoJob", data.id);
      setMediaJob(null);
      window.localStorage.removeItem("meloforge.latestCompositionJob");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Backend не е достъпен."); }
    finally { setBusy(false); }
  }

  async function confirmGeneration() {
    if (!job || job.status !== "awaiting_confirmation") return;
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/v1/jobs/${job.id}/confirm`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Novita не прие задачата.");
      setJob(data);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Неуспешно изпращане към Novita.");
      try { const current = await fetch(`/api/v1/jobs/${job.id}`); if (current.ok) setJob(await current.json()); } catch { /* Keep the quoted job visible for recovery. */ }
    }
    finally { setBusy(false); }
  }

  async function composeFullVideo() {
    if (!job || job.status !== "completed" || !songJob || songJob.status !== "completed") return;
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/v1/media/compose", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ song_job_id: songJob.id, video_job_id: job.id }) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Монтажът не можа да започне.");
      setMediaJob(data); window.localStorage.setItem("meloforge.latestCompositionJob", data.id);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Монтажът не можа да започне."); }
    finally { setBusy(false); }
  }

  const songReady = songJob?.status === "completed" && Boolean(songJob.result?.audio_url);
  const videoReady = job?.status === "completed" && Boolean(job.result?.video_urls?.length);
  return <section className="studio-layout"><div className="studio-intro"><small className="eyebrow">MUSIC VIDEO</small><h2>Сцени, ритъм<br /><span>и финален монтаж.</span></h2><p>Създай сцена с Novita Wan 2.2. После комбинирай последната готова песен и видео в пълна дължина, с файлове 16:9 и 9:16 и отделен текст на песента.</p><div className="safety-strip"><Cloud /> Платената генерация започва само след потвърждение. Финалният монтаж е локален.</div><div className="preflight"><b>Локален монтаж</b><span className={ffmpeg?.ok ? "good" : "warn"}>{ffmpeg?.ok ? "FFmpeg готов" : "FFmpeg не е открит"}</span></div></div><div className="panel video-flow"><label className="video-label">Опиши сцената<textarea className="video-prompt" value={prompt} onChange={(event) => setPrompt(event.target.value)} maxLength={800} /></label><div className="form-grid video-options"><label>Продължителност<select value={duration} onChange={(event) => setDuration(Number(event.target.value) as 5 | 8)}><option value={5}>5 секунди</option><option value={8}>8 секунди</option></select></label><label>Формат<select value={size} onChange={(event) => setSize(event.target.value)}><option value="1280*720">16:9 · 720p</option><option value="720*1280">9:16 · 720p</option><option value="624*624">1:1 · 624p</option></select></label></div><button className="primary-button large" disabled={!apiOnline || busy || prompt.trim().length < 3} onClick={() => void getQuote()}><WandSparkles size={17} />{busy ? "Изчисляване…" : "Изчисли цена"}</button>{!apiOnline && <p className="inline-notice">Backend е офлайн.</p>}{error && <p className="inline-notice error-text" role="alert">{error}</p>}{job && <div className="job-card"><div className="job-head"><span className={`job-state ${job.status}`}>{job.status === "awaiting_confirmation" ? "Чака потвърждение" : job.status === "queued" ? "На опашка" : job.status === "running" ? "Генерира се" : job.status === "completed" ? "Готово" : "Неуспешно"}</span><strong>${job.quote_usd.toFixed(4)}</strong></div><p>{job.estimate_note || `Novita Wan 2.2 · ${job.payload.duration}s · ${job.payload.size}`}</p>{job.status === "awaiting_confirmation" && <button className="primary-button large" disabled={busy} onClick={() => void confirmGeneration()}><ShieldCheck size={17} />Потвърди и генерирай за ${job.quote_usd.toFixed(4)}</button>}{job.status === "running" && <p className="inline-notice">Задача {job.provider_task_id || "изпратена"}. Статусът се обновява автоматично.</p>}{job.status === "failed" && <p className="inline-notice error-text">{job.error || "Генерацията не беше успешна."}</p>}{job.status === "completed" && (job.result?.video_urls?.length ? job.result.video_urls.map((url) => <video key={url} className="generated-video" src={url} controls />) : <p className="inline-notice">Видеото е завършено, но доставчикът не върна preview URL.</p>)}</div>}{(songReady || (job?.status === "completed" && !songReady)) && <div className="job-card assembly-card"><div className="job-head"><b>Пълно музикално видео</b><span className="job-state">Локално · без допълнителна API такса</span></div><p>{songReady ? `Песен: ${songJob?.payload.title || "ACE-Step"} · ${songJob?.payload.duration_seconds}s` : "Създай и завърши песен в Song Builder, за да я свържеш с видеото."}{videoReady ? " · видео готово" : ""}</p>{songReady && videoReady && !mediaJob && <button className="primary-button large" disabled={busy || !ffmpeg?.ok} onClick={() => void composeFullVideo()}><Layers3 size={17} />Сглоби песен и видео</button>}{mediaJob && <><div className="job-head"><span className={`job-state ${mediaJob.status}`}>{mediaJob.status === "queued" || mediaJob.status === "running" ? "Обработва се локално" : mediaJob.status === "completed" ? "Монтажът е готов" : "Монтажът не завърши"}</span></div>{mediaJob.status === "queued" || mediaJob.status === "running" ? <p className="inline-notice">Повтарям видео сцената до дължината на песента и създавам 16:9 и 9:16 версии.</p> : mediaJob.status === "failed" ? <><p className="inline-notice error-text">{mediaJob.error}</p><button className="primary-button" disabled={busy} onClick={() => void composeFullVideo()}>Опитай отново</button></> : <div className="assembly-links"><a className="primary-button" href={`/api/v1/media/${mediaJob.id}/16x9`} download>Изтегли 16:9 · 720p</a><a className="primary-button" href={`/api/v1/media/${mediaJob.id}/9x16`} download>Изтегли 9:16 · 720p</a>{mediaJob.result?.lyrics_available && <a className="text-download" href={`/api/v1/media/${mediaJob.id}/lyrics`} download>Изтегли текста · TXT</a>}</div>}</>}</div>}</div></section>;
}
function Flow({ n, title, detail }: { n: string; title: string; detail: string }) { return <div className="flow-step"><span>{n}</span><div><b>{title}</b><small>{detail}</small></div></div>; }
function Nav({ active, icon, label, onClick }: { active: boolean; icon: ReactNode; label: string; onClick: () => void }) { return <button className={active ? "active" : ""} onClick={onClick}>{icon}{label}</button>; }
function Metric({ icon, label, value, detail }: { icon: ReactNode; label: string; value: string; detail: string }) { return <div className="metric"><div className="metric-top"><span>{icon}</span><small>{label}</small></div><b>{value}</b><em>{detail}</em></div>; }
function ProviderRow({ p }: { p: Provider }) { const mark = p.id === "ollama" ? <Cpu size={18} /> : p.id === "huggingface" ? "HF" : p.id === "nvidia" ? "N" : p.id === "novita" ? "nv" : "OR"; return <div className="provider"><div className={`provider-mark ${p.id}`}>{mark}</div><div className="provider-text"><b>{p.name}</b><small>{p.model || p.description}</small></div><div className="tags"><span className={p.configured ? "good" : "off"}>{p.configured ? "Configured" : "Not set"}</span>{p.kind === "cloud" && <span className={p.pricing_configured ? "good" : "warn"}>{p.pricing_configured ? "Price set" : "Price missing"}</span>}</div></div>; }
function Roadmap({ icon, title, sub, status }: { icon: ReactNode; title: string; sub: string; status: string }) { return <div className="roadmap-item"><div>{icon}</div><span><b>{title}</b><small>{sub}</small></span><em>{status}</em></div>; }
