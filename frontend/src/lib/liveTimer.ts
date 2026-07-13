/** Tick match clocks locally between API polls. */

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

export function formatLiveTimer(match: {
  timerDisplay: string | null;
  timerSeconds: number | null;
  scoreUpdatedAt: string | null;
  scoreFunction: string | null;
}): string {
  const display = match.timerDisplay?.trim() || null;
  if (!display) {
    return "—";
  }

  // Explicit freeze (Betcity m_tmr.is_run=0 → score_function "stop").
  if (match.scoreFunction === "stop") {
    return display;
  }

  if (match.timerSeconds == null || !match.scoreUpdatedAt) {
    return display;
  }

  const baseMs = new Date(match.scoreUpdatedAt).getTime();
  if (Number.isNaN(baseMs)) {
    return display;
  }

  const elapsedSec = Math.max(0, Math.floor((Date.now() - baseMs) / 1000));
  const totalSec = match.timerSeconds + elapsedSec;

  // Fonbet-style minute clock: 36' / 45+2'
  if (/^\d+(\+\d+)?'$/.test(display)) {
    return `${Math.floor(totalSec / 60)}'`;
  }

  // Betcity / mm:ss clocks: advance seconds between polls.
  if (/^\d{1,3}:\d{2}$/.test(display)) {
    const mins = Math.floor(totalSec / 60);
    const secs = totalSec % 60;
    return `${pad2(mins)}:${pad2(secs)}`;
  }

  return display;
}
