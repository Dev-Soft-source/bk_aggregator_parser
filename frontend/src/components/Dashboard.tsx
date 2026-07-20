"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { MatchList } from "@/components/MatchList";
import { StatsBar } from "@/components/StatsBar";
import { DEFAULT_SPORT_LABEL } from "@/lib/sports";
import { KNOWN_SITES, siteLabel } from "@/lib/site";
import type { LiveMatch, MatchesResponse, SiteOption } from "@/lib/types";

const POLL_MS = Number(process.env.NEXT_PUBLIC_POLL_INTERVAL_MS ?? 3500);

type PlaceFilter = "live" | "line" | "all";

function matchesTeamSearch(match: LiveMatch, query: string): boolean {
  const q = query.trim().toLocaleLowerCase();
  if (!q) return true;
  const haystack = [match.team1, match.team2, match.leagueName]
    .filter(Boolean)
    .join(" ")
    .toLocaleLowerCase();
  return haystack.includes(q);
}

export function Dashboard() {
  const [data, setData] = useState<MatchesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [place, setPlace] = useState<PlaceFilter>("live");
  const [userSite, setUserSite] = useState<string | null>(null);
  const [userSport, setUserSport] = useState<string | null>(null);
  const [teamSearch, setTeamSearch] = useState("");

  const load = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const params = new URLSearchParams({ place });
      if (userSite) {
        params.set("site", userSite);
      }
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
  }, [place, userSite, userSport]);

  useEffect(() => {
    const initial = window.setTimeout(() => {
      void load();
    }, 0);
    const id = setInterval(load, POLL_MS);
    return () => {
      window.clearTimeout(initial);
      clearInterval(id);
    };
  }, [load]);

  const siteOptions: SiteOption[] =
    data?.sites ??
    KNOWN_SITES.map((site) => ({
      siteName: site.siteName,
      label: site.label,
      matchCount: 0,
    }));

  const activeSite = userSite ?? data?.selectedSite ?? null;
  const activeSport = userSport ?? data?.selectedSport ?? null;
  const activeLabel =
    data?.sports.find((s) => s.sportName === activeSport)?.label ??
    DEFAULT_SPORT_LABEL;
  const activeSiteLabel =
    activeSite === "all"
      ? "All sites"
      : siteOptions.find((site) => site.siteName === activeSite)?.label ??
        (activeSite ? siteLabel(activeSite) : "—");
  const isAllSites = activeSite === "all";

  const filteredMatches = useMemo(() => {
    const matches = data?.matches ?? [];
    if (!teamSearch.trim()) return matches;
    return matches.filter((match) => matchesTeamSearch(match, teamSearch));
  }, [data?.matches, teamSearch]);

  const searchActive = Boolean(teamSearch.trim());

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">
            Live sportsbook
          </h1>
          <p className="text-sm text-slate-400">
            {activeLabel} · {activeSiteLabel} · auto-refresh every {POLL_MS / 1000}s
            {searchActive ? (
              <>
                {" "}
                ·{" "}
                <span className="text-slate-300">
                  {filteredMatches.length} match
                  {filteredMatches.length === 1 ? "" : "es"} for &quot;
                  {teamSearch.trim()}&quot;
                </span>
              </>
            ) : null}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <input
              type="search"
              value={teamSearch}
              onChange={(event) => setTeamSearch(event.target.value)}
              placeholder="Search team…"
              aria-label="Search team"
              className="w-44 rounded-lg border border-slate-700 bg-slate-900 py-1.5 pl-3 pr-8 text-sm text-slate-200 placeholder:text-slate-500 focus:border-amber-500/60 focus:outline-none focus:ring-1 focus:ring-amber-500/40 sm:w-56"
            />
            {teamSearch ? (
              <button
                type="button"
                onClick={() => setTeamSearch("")}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
                aria-label="Clear search"
              >
                ×
              </button>
            ) : null}
          </div>
          <select
            value={activeSite ?? data?.selectedSite ?? KNOWN_SITES[0].siteName}
            onChange={(event) => {
              setUserSite(event.target.value);
              setUserSport(null);
            }}
            className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-slate-200"
            aria-label="Site"
          >
            <option value="all">All sites</option>
            {siteOptions.map((site) => (
              <option key={site.siteName} value={site.siteName}>
                {site.label} ({site.matchCount})
              </option>
            ))}
          </select>
          {(["live", "line", "all"] as const).map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => {
                setPlace(p);
                setUserSport(null);
              }}
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
            Check DATABASE_URL in frontend/.env.local and that the backend pollers are
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
                Sports {activeSiteLabel !== "—" ? `· ${activeSiteLabel}` : ""}
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
              <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-8 text-center text-slate-400">
                <p>
                  No {activeLabel} matches for &quot;{place}&quot;.
                  {activeSite ? (
                    <>
                      {" "}
                      Site: <span className="text-slate-300">{activeSiteLabel}</span>.
                      Ensure{" "}
                      <code className="text-amber-400/90">frontend/.env.local</code>{" "}
                      <code className="text-amber-400/90">DATABASE_URL</code> points to the
                      shared database, then run:
                    </>
                  ) : (
                    " Run the backend pollers:"
                  )}
                </p>
                {data.pollCommand ? (
                  <code className="mt-2 block text-amber-400">
                    cd backend && {data.pollCommand}
                  </code>
                ) : (
                  <div className="mt-2 space-y-1 text-amber-400">
                    <code className="block">cd backend && python main.py poll</code>
                    <code className="block">
                      cd backend && python main.py poll ligastavok-live
                    </code>
                    <code className="block">cd backend && python main.py poll bet365</code>
                  </div>
                )}
              </div>
            ) : filteredMatches.length === 0 ? (
              <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-8 text-center text-slate-400">
                <p>
                  No teams matching &quot;
                  <span className="text-slate-200">{teamSearch.trim()}</span>
                  &quot;.
                </p>
                <button
                  type="button"
                  onClick={() => setTeamSearch("")}
                  className="mt-3 rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
                >
                  Clear search
                </button>
              </div>
            ) : (
              <MatchList
                matches={filteredMatches}
                singleSport={!isAllSites}
                paginationKey={`${place}|${activeSite ?? ""}|${activeSport ?? ""}|${teamSearch.trim().toLocaleLowerCase()}`}
              />
            )}
          </div>
        </div>
      ) : !error ? (
        <p className="text-center text-slate-400">Loading…</p>
      ) : null}
    </div>
  );
}
