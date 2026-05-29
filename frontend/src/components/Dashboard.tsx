"use client";

import { useCallback, useEffect, useState } from "react";

import { MatchList } from "@/components/MatchList";
import { StatsBar } from "@/components/StatsBar";
import type { MatchesResponse } from "@/lib/types";

const POLL_MS = Number(process.env.NEXT_PUBLIC_POLL_INTERVAL_MS ?? 3500);

type PlaceFilter = "live" | "line" | "all";

export function Dashboard() {
  const [data, setData] = useState<MatchesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [place, setPlace] = useState<PlaceFilter>("live");

  const load = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const res = await fetch(`/api/matches?place=${place}`, {
        cache: "no-store",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error ?? `HTTP ${res.status}`);
      }
      const json: MatchesResponse = await res.json();
      setData(json);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    } finally {
      setIsRefreshing(false);
    }
  }, [place]);

  useEffect(() => {
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">
            Live sportsbook
          </h1>
          <p className="text-sm text-slate-400">
            Auto-refresh every {POLL_MS / 1000}s from PostgreSQL
          </p>
        </div>
        <div className="flex gap-2">
          {(["live", "line", "all"] as const).map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setPlace(p)}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                place === p
                  ? "bg-amber-500 text-slate-950"
                  : "bg-slate-800 text-slate-300 hover:bg-slate-700"
              }`}
            >
              {p}
            </button>
          ))}
          <button
            type="button"
            onClick={() => load()}
            disabled={isRefreshing}
            className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800 disabled:opacity-50"
          >
            Refresh
          </button>
        </div>
      </div>

      {error ? (
        <div className="rounded-xl border border-rose-800 bg-rose-950/50 p-4 text-rose-200">
          {error}
          <p className="mt-2 text-sm text-rose-300/80">
            Check DATABASE_URL in frontend/.env.local and that the backend poller is
            running.
          </p>
        </div>
      ) : null}

      {data ? (
        <>
          <StatsBar
            stats={data.stats}
            fetchedAt={data.fetchedAt}
            isRefreshing={isRefreshing}
          />
          {data.matches.length === 0 ? (
            <p className="rounded-xl border border-slate-800 bg-slate-900/50 p-8 text-center text-slate-400">
              No matches for filter &quot;{place}&quot;.               Run the backend poller:
              <code className="mt-2 block text-amber-400">
                python backend/main.py poll ligastavok
              </code>
            </p>
          ) : (
            <MatchList matches={data.matches} />
          )}
        </>
      ) : !error ? (
        <p className="text-center text-slate-400">Loading…</p>
      ) : null}
    </div>
  );
}
