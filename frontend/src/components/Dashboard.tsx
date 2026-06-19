"use client";

import { useCallback, useEffect, useState } from "react";

import { MatchList } from "@/components/MatchList";
import { StatsBar } from "@/components/StatsBar";
import { DEFAULT_SPORT_LABEL } from "@/lib/sports";
import type { MatchesResponse } from "@/lib/types";

const POLL_MS = Number(process.env.NEXT_PUBLIC_POLL_INTERVAL_MS ?? 3500);

type PlaceFilter = "live" | "line" | "all";

export function Dashboard() {
  const [data, setData] = useState<MatchesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [place, setPlace] = useState<PlaceFilter>("live");
  const [userSport, setUserSport] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const params = new URLSearchParams({ place });
      if (userSport) {
        params.set("sport", userSport);
      }
      const res = await fetch(`/api/matches?${params}`, { cache: "no-store" });
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
  }, [place, userSport]);

  useEffect(() => {
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  const activeSport = userSport ?? data?.selectedSport ?? null;
  const activeLabel =
    data?.sports.find((s) => s.sportName === activeSport)?.label ??
    DEFAULT_SPORT_LABEL;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">
            Live sportsbook
          </h1>
          <p className="text-sm text-slate-400">
            {activeLabel} · auto-refresh every {POLL_MS / 1000}s
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
        <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
          <aside className="w-full shrink-0 lg:w-52">
            <nav
              className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/50"
              aria-label="Sports"
            >
              <div className="border-b border-slate-800 px-4 py-2.5 text-xs font-medium uppercase tracking-wide text-slate-500">
                Sports
              </div>
              <ul className="max-h-[420px] overflow-y-auto p-2">
                {data.sports.length === 0 ? (
                  <li className="px-3 py-2 text-sm text-slate-500">No sports</li>
                ) : (
                  data.sports.map((sport) => {
                    const isActive = sport.sportName === activeSport;
                    return (
                      <li key={sport.sportName}>
                        <button
                          type="button"
                          onClick={() => setUserSport(sport.sportName)}
                          className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm transition ${
                            isActive
                              ? "bg-amber-500/15 font-medium text-amber-400"
                              : "text-slate-300 hover:bg-slate-800"
                          }`}
                        >
                          <span>{sport.label}</span>
                          <span
                            className={`tabular-nums text-xs ${
                              isActive ? "text-amber-500/80" : "text-slate-500"
                            }`}
                          >
                            {sport.matchCount}
                          </span>
                        </button>
                      </li>
                    );
                  })
                )}
              </ul>
            </nav>
          </aside>

          <div className="min-w-0 flex-1 space-y-6">
            <StatsBar
              stats={data.stats}
              fetchedAt={data.fetchedAt}
              isRefreshing={isRefreshing}
            />
            {data.matches.length === 0 ? (
              <p className="rounded-xl border border-slate-800 bg-slate-900/50 p-8 text-center text-slate-400">
                No {activeLabel} matches for &quot;{place}&quot;.
                {data.siteName ? (
                  <>
                    {" "}
                    Site: <span className="text-slate-300">{data.siteName}</span>.
                    Ensure{" "}
                    <code className="text-amber-400/90">frontend/.env.local</code>{" "}
                    <code className="text-amber-400/90">SITE_NAME</code> matches{" "}
                    <code className="text-amber-400/90">backend/.env</code>, then run:
                  </>
                ) : (
                  " Run the backend poller:"
                )}
                <code className="mt-2 block text-amber-400">
                  cd backend && {data.pollCommand ?? "python main.py poll"}
                </code>
              </p>
            ) : (
              <MatchList matches={data.matches} singleSport />
            )}
          </div>
        </div>
      ) : !error ? (
        <p className="text-center text-slate-400">Loading…</p>
      ) : null}
    </div>
  );
}
