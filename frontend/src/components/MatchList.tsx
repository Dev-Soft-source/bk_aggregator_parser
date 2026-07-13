"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { formatLiveTimer } from "@/lib/liveTimer";
import type { LiveMatch } from "@/lib/types";

interface MatchListProps {
  matches: LiveMatch[];
  singleSport?: boolean;
  /** When this changes (search/filters), pagination resets to page 1. */
  paginationKey?: string;
}

const PAGE_SIZES = [50, 70, 100] as const;
type PageSize = (typeof PAGE_SIZES)[number];
const DEFAULT_PAGE_SIZE: PageSize = 50;

const stateStyles: Record<string, string> = {
  unblocked: "text-emerald-400",
  blocked: "text-rose-400",
  partial: "text-amber-400",
};

function sortMatches(matches: LiveMatch[], singleSport: boolean) {
  return [...matches].sort((a, b) => {
    if (!singleSport) {
      const bySport = a.sportName.localeCompare(b.sportName);
      if (bySport !== 0) return bySport;
    }

    const byCountry = (a.countryName ?? "").localeCompare(b.countryName ?? "");
    if (byCountry !== 0) return byCountry;

    const byLeague = (a.leagueName ?? "").localeCompare(b.leagueName ?? "");
    if (byLeague !== 0) return byLeague;

    return (a.team1 ?? "").localeCompare(b.team1 ?? "");
  });
}

function formatScore(match: LiveMatch) {
  if (match.score1 != null && match.score2 != null) {
    return `${match.score1} : ${match.score2}`;
  }
  return "—";
}

function formatOdd(value: number | null) {
  return value != null ? value.toFixed(2) : "—";
}

type OddsSnapshot = { odd1: number | null; oddX: number | null; odd2: number | null };
type OddHighlight = "up" | "down" | null;
type MatchHighlight = { odd1: OddHighlight; oddX: OddHighlight; odd2: OddHighlight };

function oddHighlightClass(direction: OddHighlight): string {
  if (direction === "up") {
    return "bg-emerald-600/45 text-emerald-100";
  }
  if (direction === "down") {
    return "bg-rose-600/45 text-rose-100";
  }
  return "text-slate-200";
}

function computeHighlight(
  current: number | null,
  previous: number | null | undefined,
): OddHighlight {
  if (current == null || previous == null) {
    return null;
  }
  if (current > previous) return "up";
  if (current < previous) return "down";
  return null;
}

function formatStartTime(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function matchKey(match: LiveMatch): string {
  return `${match.siteName}:${match.matchId}`;
}

export function MatchList({
  matches,
  singleSport = false,
  paginationKey = "",
}: MatchListProps) {
  const baselineOddsRef = useRef<Map<string, OddsSnapshot>>(new Map());
  const [oddHighlights, setOddHighlights] = useState<Map<string, MatchHighlight>>(new Map());
  const [pageSize, setPageSize] = useState<PageSize>(DEFAULT_PAGE_SIZE);
  const [page, setPage] = useState(1);
  const [, tick] = useState(0);

  useEffect(() => {
    const nextHighlights = new Map<string, MatchHighlight>();
    const nextBaseline = new Map<string, OddsSnapshot>();
    for (const match of matches) {
      const key = matchKey(match);
      const base = baselineOddsRef.current.get(key);
      nextHighlights.set(key, {
        odd1: computeHighlight(match.odd1, base?.odd1),
        oddX: computeHighlight(match.oddX, base?.oddX),
        odd2: computeHighlight(match.odd2, base?.odd2),
      });
      nextBaseline.set(key, {
        odd1: match.odd1,
        oddX: match.oddX,
        odd2: match.odd2,
      });
    }
    const flush = window.setTimeout(() => {
      setOddHighlights(nextHighlights);
    }, 0);
    baselineOddsRef.current = nextBaseline;
    return () => window.clearTimeout(flush);
  }, [matches]);

  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const sorted = useMemo(
    () => sortMatches(matches, singleSport),
    [matches, singleSport],
  );

  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const currentPage = Math.min(page, totalPages);

  useEffect(() => {
    setPage(1);
  }, [pageSize, singleSport, paginationKey]);

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages);
    }
  }, [page, totalPages]);

  const pageMatches = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return sorted.slice(start, start + pageSize);
  }, [sorted, currentPage, pageSize]);

  const rangeStart = sorted.length === 0 ? 0 : (currentPage - 1) * pageSize + 1;
  const rangeEnd = Math.min(currentPage * pageSize, sorted.length);

  let lastSport = "";
  let lastCountry = "";

  const rows: ReactNode[] = [];
  const colSpan = singleSport ? 11 : 14;

  for (const match of pageMatches) {
    const countryKey = match.countryName ?? "—";

    if (!singleSport && match.sportName !== lastSport) {
      rows.push(
        <tr key={`sport-${match.sportName}`} className="bg-slate-800/60">
          <td
            colSpan={colSpan}
            className="px-4 py-2 text-sm font-semibold uppercase tracking-wide text-amber-400"
          >
            {match.sportName}
          </td>
        </tr>,
      );
      lastSport = match.sportName;
      lastCountry = "";
    }

    if (countryKey !== lastCountry) {
      rows.push(
        <tr key={`country-${match.sportName}-${countryKey}`} className="bg-slate-800/30">
          {!singleSport ? <td className="px-4 py-1.5" /> : null}
          <td
            colSpan={singleSport ? colSpan : colSpan - 1}
            className="px-4 py-1.5 text-xs font-medium text-slate-300"
          >
            {countryKey}
          </td>
        </tr>,
      );
      lastCountry = countryKey;
    }

    const state = match.bettingState ?? "—";
    const stateClass = stateStyles[state] ?? "text-slate-400";
    const key = matchKey(match);
    const highlight = oddHighlights.get(key);
    const odd1Class = oddHighlightClass(highlight?.odd1 ?? null);
    const oddXClass = oddHighlightClass(highlight?.oddX ?? null);
    const odd2Class = oddHighlightClass(highlight?.odd2 ?? null);

    rows.push(
      <tr key={key} className="transition hover:bg-slate-800/40">
        {!singleSport ? (
          <>
            <td className="px-4 py-3 text-slate-600">·</td>
            <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-400">
              {match.siteName}
            </td>
          </>
        ) : null}
        <td
          className="max-w-[200px] truncate px-4 py-3 text-slate-400"
          title={match.leagueName ?? undefined}
        >
          {match.leagueName ?? "—"}
        </td>
        <td className="max-w-[160px] truncate px-4 py-3 text-right text-white">
          {match.team1 ?? "—"}
        </td>
        <td className="whitespace-nowrap px-4 py-3 text-center font-semibold tabular-nums text-amber-400">
          {formatScore(match)}
        </td>
        <td className="max-w-[160px] truncate px-4 py-3 text-white">
          {match.team2 ?? "—"}
        </td>
        <td className="whitespace-nowrap px-4 py-3 text-center text-slate-300">
          {formatLiveTimer(match)}
        </td>
        <td className="whitespace-nowrap px-4 py-3">
          <span className="rounded bg-slate-800 px-2 py-0.5 text-xs uppercase text-slate-300">
            {match.place}
          </span>
        </td>
        <td
          className={`whitespace-nowrap px-4 py-3 text-xs font-medium capitalize ${stateClass}`}
        >
          {state}
        </td>
        <td
          className={`whitespace-nowrap px-4 py-3 text-center tabular-nums ${odd1Class}`}
        >
          {formatOdd(match.odd1)}
        </td>
        <td
          className={`whitespace-nowrap px-4 py-3 text-center tabular-nums ${oddXClass}`}
        >
          {formatOdd(match.oddX)}
        </td>
        <td
          className={`whitespace-nowrap px-4 py-3 text-center tabular-nums ${odd2Class}`}
        >
          {formatOdd(match.odd2)}
        </td>
        <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-500">
          {formatStartTime(match.startTime)}
        </td>
      </tr>,
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/50 shadow-lg shadow-black/20">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[960px] border-collapse text-left text-sm">
          <thead>
            <tr className="border-b border-slate-800 bg-slate-900 text-xs font-medium uppercase tracking-wide text-slate-400">
              {!singleSport ? (
                <>
                  <th className="px-4 py-3">Sport</th>
                  <th className="px-4 py-3">Site</th>
                </>
              ) : (
                <th className="px-4 py-3">Country</th>
              )}
              <th className="px-4 py-3 text-right">Team 1</th>
              <th className="px-4 py-3 text-center">Score</th>
              <th className="px-4 py-3">Team 2</th>
              <th className="px-4 py-3 text-center">Timer</th>
              <th className="px-4 py-3">Place</th>
              <th className="px-4 py-3">State</th>
              <th className="px-4 py-3 text-center">1</th>
              <th className="px-4 py-3 text-center">X</th>
              <th className="px-4 py-3 text-center">2</th>
              <th className="px-4 py-3">Start</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/80">{rows}</tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-800 px-4 py-2.5 text-xs text-slate-500">
        <div>
          {sorted.length === 0
            ? "0 matches"
            : `${rangeStart}–${rangeEnd} of ${sorted.length} match${sorted.length === 1 ? "" : "es"}`}
          {singleSport ? " · by country, league" : " · sorted by sport, country, league"}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2">
            <span className="text-slate-500">Per page</span>
            <select
              value={pageSize}
              onChange={(event) => setPageSize(Number(event.target.value) as PageSize)}
              className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200"
              aria-label="Matches per page"
            >
              {PAGE_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </label>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={currentPage <= 1}
              className="rounded-md border border-slate-700 px-2 py-1 text-slate-300 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
              aria-label="Previous page"
            >
              Prev
            </button>
            <span className="min-w-[4.5rem] px-1 text-center tabular-nums text-slate-400">
              {currentPage} / {totalPages}
            </span>
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={currentPage >= totalPages}
              className="rounded-md border border-slate-700 px-2 py-1 text-slate-300 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
              aria-label="Next page"
            >
              Next
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
