import { useEffect, useState } from "react";
import { Clapperboard, ShieldCheck } from "lucide-react";

type Estimate = { known?: boolean; amount_usd?: number; fits_budget?: boolean; breakdown?: { item?: string; label?: string; amount_usd?: number }[]; downgraded_to_stills?: unknown[] };
type Project = { project: string; status: string; stage?: string; pct?: number; spent_usd?: number; estimate?: Estimate; warnings?: string[]; error?: string | null; outputs?: { video?: string }; package?: { stems: boolean } };
type SongLike = { id: string; status: string };

const ACTIVE = ["running", "queued"];

export function AtelierClip({ song }: { song: SongLike }) {
  const [online, setOnline] = useState<boolean | null>(null);
  const [baseUrl, setBaseUrl] = useState("");
  const [mode, setMode] = useState("mixed");
  const [aspect, setAspect] = useState("16x9");
  const [lyrics, setLyrics] = useState(true);
  const [localOnly, setLocalOnly] = useState(false);
  const [budget, setBudget] = useState(1.05);
  const [notes, setNotes] = useState("");
  const [project, setProject] = useState<Project | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const storageKey = `meloforge.atelierProject.${song.id}`;

  useEffect(() => {
    void fetch("/api/v1/atelier/status").then((response) => response.json()).then((data) => { setOnline(Boolean(data.online)); setBaseUrl(data.base_url || ""); }).catch(() => setOnline(false));
    const saved = window.localStorage.getItem(storageKey);
    if (saved) void fetch(`/api/v1/atelier/musicvideo/${encodeURIComponent(saved)}`).then((response) => response.ok ? response.json() : null).then((data) => { if (data) setProject({ ...data, project: saved }); }).catch(() => undefined);
  }, [song.id]);

  useEffect(() => {
    if (!project || !ACTIVE.includes(project.status)) return;
    const timer = window.setTimeout(async () => {
      try { const response = await fetch(`/api/v1/atelier/musicvideo/${encodeURIComponent(project.project)}`); if (response.ok) setProject({ ...(await response.json()), project: project.project }); }
      catch { /* next poll */ }
    }, 4000);
    return () => window.clearTimeout(timer);
  }, [project]);

  async function estimate() {
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/v1/atelier/musicvideo", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ song_job_id: song.id, mode, aspect, lyrics_on_screen: lyrics, local_only: localOnly, budget_usd: localOnly ? 0 : budget, notes }) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Atelier не прие задачата.");
      setProject(data); window.localStorage.setItem(storageKey, data.project);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Atelier не прие задачата."); }
    finally { setBusy(false); }
  }

  async function confirm() {
    if (!project) return;
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/v1/atelier/musicvideo/${encodeURIComponent(project.project)}/confirm`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Потвърждението не мина.");
      setProject({ ...project, ...data, project: project.project, status: data.status || "running" });
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Потвърждението не мина."); }
    finally { setBusy(false); }
  }

  if (song.status !== "completed") return null;
  const est = project?.estimate;
  const amount = est?.amount_usd ?? 0;
  return <details className="engine-settings atelier-clip"><summary><Clapperboard size={15} /> Клип в Atelier (истински кадри)</summary>
    <p>Atelier прави сценарий по куплетите и припевите, кадри с постоянни герои, монтаж в ритъма на песента и текст на екрана. Нищо платено не започва преди да потвърдиш цената.</p>
    {online === false && <p className="inline-notice error-text">Atelier не отговаря на {baseUrl || "http://127.0.0.1:8765"}. Стартирай Atelier и опитай пак.</p>}
    <div className="form-grid"><label>Режим<select value={mode} onChange={(event) => setMode(event.target.value)}><option value="stills">Кадри с движение (най-евтино)</option><option value="mixed">Смесен: кадри + AI видео в припевите</option><option value="video">Само AI видео (най-скъпо)</option></select></label>
      <label>Формат<select value={aspect} onChange={(event) => setAspect(event.target.value)}><option value="16x9">16:9 · YouTube</option><option value="9x16">9:16 · Shorts/TikTok/Reels</option></select></label></div>
    <label className="checkline"><input type="checkbox" checked={localOnly} onChange={(event) => setLocalOnly(event.target.checked)} /> Само локално и безплатно (ComfyUI, без облак)</label>
    <label className="checkline"><input type="checkbox" checked={lyrics} onChange={(event) => setLyrics(event.target.checked)} /> Текст на екрана</label>
    {!localOnly && <label>Таван на разхода <span>${budget.toFixed(2)}</span><input className="slider" type="range" min="0.1" max="5" step="0.05" value={budget} onChange={(event) => setBudget(Number(event.target.value))} /></label>}
    <label>Бележки към режисьора <span>по желание</span><textarea value={notes} onChange={(event) => setNotes(event.target.value)} maxLength={1000} placeholder="напр. селска кръчма, зимна вечер, топла жълта светлина" /></label>
    <button className="secondary-button" disabled={busy || online === false || Boolean(project && ACTIVE.includes(project.status))} onClick={() => void estimate()}><Clapperboard size={15} />{busy && !project ? "Подготвям пакета…" : "Изчисли цена в Atelier"}</button>
    {project && <div className="job-card"><div className="job-head"><span className={`job-state ${project.status === "done" ? "completed" : project.status}`}>{project.status}</span><strong>{project.status === "needs_confirm" ? `~$${amount.toFixed(2)}` : `$${(project.spent_usd ?? 0).toFixed(2)} похарчени`}</strong></div>
      {project.package && <p className="inline-notice">{project.package.stems ? "✓ Изпратен с отделен вокал за точен синхрон на текста." : "Изпратен без отделен вокал — Atelier ще го отдели сам."}</p>}
      {(project.warnings || []).map((warning) => <p key={warning} className="inline-notice warn-text">⚠ {warning}</p>)}
      {project.status === "needs_confirm" && <>{est?.breakdown && est.breakdown.length > 0 && <ul className="estimate-list">{est.breakdown.map((row, index) => <li key={index}>{row.label || row.item}<em>${(row.amount_usd ?? 0).toFixed(3)}</em></li>)}</ul>}
        {est?.fits_budget === false ? <p className="inline-notice error-text">Оценката надхвърля тавана. Вдигни тавана или избери „Кадри с движение“.</p>
          : <button className="primary-button large" disabled={busy} onClick={() => void confirm()}><ShieldCheck size={17} />{amount > 0 ? `Потвърди ~$${amount.toFixed(2)} и започни` : "Започни (безплатно)"}</button>}</>}
      {ACTIVE.includes(project.status) && <><p className="inline-notice">{project.stage || "работи"} · {project.pct ?? 0}%</p><progress className="progress" max={100} value={project.pct ?? 0} /></>}
      {(project.status === "failed" || project.status === "interrupted") && <p className="inline-notice error-text">{project.error || "Atelier спря задачата."}</p>}
      {project.status === "done" && <><video className="generated-video" src={`/api/v1/atelier/musicvideo/${encodeURIComponent(project.project)}/video`} controls /><div className="assembly-links"><a className="primary-button" href={`/api/v1/atelier/musicvideo/${encodeURIComponent(project.project)}/video`} download>Изтегли клипа</a></div></>}
    </div>}
    {error && <p className="inline-notice error-text" role="alert">{error}</p>}
  </details>;
}
