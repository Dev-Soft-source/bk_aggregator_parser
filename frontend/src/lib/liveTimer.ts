/** Tick clock locally when API sends minute-style matchTime (e.g. 36'). */
export function formatLiveTimer(match: {
  timerDisplay: string | null;
  timerSeconds: number | null;
  scoreUpdatedAt: string | null;
  scoreFunction: string | null;
}): string {
  const minuteStyle =
    match.timerDisplay != null && /^\d+(\+\d+)?'$/.test(match.timerDisplay.trim());
  if (match.timerSeconds != null && match.scoreUpdatedAt && minuteStyle) {
    const baseMs = new Date(match.scoreUpdatedAt).getTime();
    const elapsedSec = Math.max(0, Math.floor((Date.now() - baseMs) / 1000));
    const totalMinutes = Math.floor((match.timerSeconds + elapsedSec) / 60);
    return `${totalMinutes}'`;
  }
  return match.timerDisplay ?? "—";
}
