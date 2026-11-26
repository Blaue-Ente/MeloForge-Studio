export type Progress = { pct: number; stage: string; stage_label: string; eta_seconds: number | null; elapsed_seconds: number } | null | undefined;

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.max(5, Math.round(seconds / 5) * 5)} сек.`;
  const minutes = Math.round(seconds / 60);
  return minutes < 60 ? `${minutes} мин.` : `${Math.floor(minutes / 60)} ч. ${minutes % 60} мин.`;
}

/** Progress bar with stage and remaining-time estimate for a running job. */
export function JobProgress({ progress, fallback }: { progress: Progress; fallback?: string }) {
  if (!progress) return fallback ? <p className="inline-notice">{fallback}</p> : null;
  const pct = Math.max(2, Math.min(99, progress.pct));
  return <div className="job-progress" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
    <div className="job-progress-bar"><span style={{ width: `${pct}%` }} /></div>
    <div className="job-progress-text"><b>{progress.stage_label}</b><span>{Math.round(progress.pct)}%</span>
      <em>{progress.eta_seconds !== null && progress.eta_seconds > 0 ? `остават ~${formatDuration(progress.eta_seconds)}` : "почти готово"} · минаха {formatDuration(progress.elapsed_seconds)}</em></div>
  </div>;
}
