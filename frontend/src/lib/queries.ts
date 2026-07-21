import { defaultSiteName, getPool } from "./db";
import { KNOWN_SITES } from "./site";
import {
  pickDefaultSportName,
  sortSportNames,
  sportDisplayLabel,
} from "./sports";
import type {
  DashboardStats,
  LiveMatch,
  OddsLine,
  SiteOption,
  SportCategory,
} from "./types";

const SPORT_NAME_SQL = `CASE WHEN sp.reference_sport_id = 1 THEN 'Football' ELSE sp.name_en END`;
const ALL_SITES = "all";

function sqlSiteFilter(column: string): string {
  return `($1::text = '${ALL_SITES}' OR ${column} = $1)`;
}

const SPORTS_SQL = `
SELECT
    ${SPORT_NAME_SQL} AS sport_name,
    COUNT(*)::int AS match_count
FROM matches m
JOIN sites st ON st.id = m.site_id
JOIN sports sp ON sp.site_id = m.site_id AND sp.id = m.sport_id
WHERE ${sqlSiteFilter("st.name")}
  AND ($2::text IS NULL OR m.place = $2)
GROUP BY 1
ORDER BY match_count DESC, sport_name ASC
`;

const SITES_SQL = `
SELECT
    st.name AS site_name,
    COUNT(*)::int AS match_count
FROM sites st
LEFT JOIN matches m ON m.site_id = st.id
  AND ($1::text IS NULL OR m.place = $1)
GROUP BY st.id, st.name
ORDER BY st.name ASC
`;

const MATCHES_SQL = `
SELECT
    st.name AS site_name,
    m.id AS match_id,
    m.team1,
    m.team2,
    m.place,
    m.start_time,
    m.priority,
    ${SPORT_NAME_SQL} AS sport_name,
    l.name AS league_name,
    c.name AS country_name,
    ms.score1,
    ms.score2,
    ms.timer_display,
    ms.timer_seconds,
    ms.timer_updated_at AS score_updated_at,
    ms.score_function,
    bs.state AS betting_state,
    snap.imported_at AS last_updated
FROM matches m
JOIN sites st ON st.id = m.site_id
JOIN sports sp ON sp.site_id = m.site_id AND sp.id = m.sport_id
LEFT JOIN leagues l ON l.site_id = m.site_id AND l.id = m.league_id
LEFT JOIN countries c ON c.id = l.country_id
LEFT JOIN match_scores ms ON ms.site_id = m.site_id AND ms.match_id = m.id
LEFT JOIN betting_status bs ON bs.site_id = m.site_id AND bs.match_id = m.id
LEFT JOIN import_snapshots snap ON snap.id = m.snapshot_id
WHERE ${sqlSiteFilter("st.name")}
  AND ($2::text IS NULL OR m.place = $2)
  AND ($4::text IS NULL OR ${SPORT_NAME_SQL} = $4)
ORDER BY
    st.name ASC,
    c.name ASC NULLS LAST,
    l.name ASC NULLS LAST,
    m.priority DESC NULLS LAST,
    m.start_time ASC NULLS LAST
LIMIT $3
`;

const STATS_SQL = `
SELECT
    (SELECT COUNT(*)::int FROM matches m
     JOIN sites st ON st.id = m.site_id
     WHERE ${sqlSiteFilter("st.name")} AND m.place = 'live') AS live_matches,
    (SELECT COUNT(*)::int FROM odds_lines o
     JOIN sites st ON st.id = o.site_id
     WHERE ${sqlSiteFilter("st.name")}) AS total_odds,
    s.imported_at,
    s.packet_version
FROM import_snapshots s
JOIN sites st ON st.id = s.site_id
WHERE ${sqlSiteFilter("st.name")}
ORDER BY s.id DESC
LIMIT 1
`;

function oddsFactorIds(): number[] {
  const raw = process.env.ODDS_FACTOR_IDS ?? "921,922,923";
  return raw.split(",").map((s) => parseInt(s.trim(), 10)).filter((n) => !Number.isNaN(n));
}

const OUTCOME_LABELS: Record<number, string> = {
  921: "1",
  922: "X",
  923: "2",
};

function sortOddsByConfig(lines: OddsLine[], factorIds: number[]): OddsLine[] {
  const byFactor = new Map(lines.map((line) => [line.factorId, line]));
  return factorIds
    .map((id) => byFactor.get(id))
    .filter((line): line is OddsLine => line !== undefined);
}

type MainOdds = {
  odd1: number | null;
  oddX: number | null;
  odd2: number | null;
};

/** Prefer 1/X/2 (921/922/923) from the primary market when several collide. */
function pickDisplayOdds(lines: OddsLine[]): MainOdds {
  const preferredMarkets = [1777, 1763, 1453, 1450, 1446, 910080, 920054, 780112, 170153];

  const primary = lines.filter(
    (line) =>
      (line.factorId === 921 || line.factorId === 922 || line.factorId === 923) &&
      !line.isHandicapTotal,
  );
  if (primary.length > 0) {
    const byMarket = new Map<number | null, OddsLine[]>();
    for (const line of primary) {
      const key = line.lineParam;
      const group = byMarket.get(key) ?? [];
      group.push(line);
      byMarket.set(key, group);
    }
    const ranked = [...byMarket.entries()].sort(([a], [b]) => {
      const ia = a == null ? 99 : preferredMarkets.indexOf(a);
      const ib = b == null ? 99 : preferredMarkets.indexOf(b);
      const ra = ia === -1 ? 50 + (a ?? 9_999_999) : ia;
      const rb = ib === -1 ? 50 + (b ?? 9_999_999) : ib;
      return ra - rb;
    });
    const best = ranked[0]?.[1] ?? primary;
    const byFactor = new Map(best.map((line) => [line.factorId, line.odds]));
    return {
      odd1: byFactor.get(921) ?? null,
      oddX: byFactor.get(922) ?? null,
      odd2: byFactor.get(923) ?? null,
    };
  }

  const factorIds = oddsFactorIds().filter((id) => id !== 922);
  const configured = sortOddsByConfig(lines, factorIds);
  if (configured.length >= 2) {
    return {
      odd1: configured[0]?.odds ?? null,
      oddX: null,
      odd2: configured[1]?.odds ?? null,
    };
  }

  const byMarket = new Map<string, OddsLine[]>();
  for (const line of lines) {
    if (line.isHandicapTotal) continue;
    const key = line.lineParam != null ? String(line.lineParam) : "none";
    const group = byMarket.get(key) ?? [];
    group.push(line);
    byMarket.set(key, group);
  }

  const groups = [...byMarket.entries()]
    .filter(([, group]) => group.length >= 2)
    .sort(([a], [b]) => {
      const pa = a === "none" ? 9_999_999 : Number(a);
      const pb = b === "none" ? 9_999_999 : Number(b);
      const ia = preferredMarkets.indexOf(pa);
      const ib = preferredMarkets.indexOf(pb);
      if (ia !== -1 || ib !== -1) {
        return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
      }
      return pa - pb;
    });

  for (const [, group] of groups) {
    const sorted = [...group].sort((x, y) => x.factorId - y.factorId);
    return {
      odd1: sorted[0]?.odds ?? null,
      oddX: null,
      odd2: sorted[1]?.odds ?? null,
    };
  }

  return { odd1: null, oddX: null, odd2: null };
}

const ODDS_FOR_MATCHES_SQL = `
SELECT DISTINCT ON (o.match_id, o.factor_id, o.line_param)
    st.name AS site_name,
    o.match_id,
    o.factor_id,
    o.odds::float8 AS odds,
    o.line_param_text,
    o.is_handicap_total,
    o.market_event_name,
    o.line_param
FROM odds_lines o
JOIN sites st ON st.id = o.site_id
WHERE ${sqlSiteFilter("st.name")}
  AND o.match_id = ANY($2::bigint[])
ORDER BY o.match_id, o.factor_id, o.line_param,
    o.snapshot_id DESC NULLS LAST
`;

function mapMatch(
  row: Record<string, unknown>,
  mainOdds: { odd1: number | null; oddX: number | null; odd2: number | null },
): LiveMatch {
  return {
    matchId: Number(row.match_id),
    siteName: String(row.site_name),
    team1: row.team1 as string | null,
    team2: row.team2 as string | null,
    place: String(row.place),
    startTime: row.start_time
      ? new Date(row.start_time as string).toISOString()
      : null,
    priority: row.priority != null ? Number(row.priority) : null,
    sportName: String(row.sport_name),
    leagueName: row.league_name as string | null,
    countryName: row.country_name as string | null,
    score1: row.score1 != null ? Number(row.score1) : null,
    score2: row.score2 != null ? Number(row.score2) : null,
    timerDisplay: row.timer_display as string | null,
    timerSeconds: row.timer_seconds != null ? Number(row.timer_seconds) : null,
    scoreUpdatedAt: row.score_updated_at
      ? new Date(row.score_updated_at as string).toISOString()
      : null,
    scoreFunction: row.score_function as string | null,
    bettingState: row.betting_state as string | null,
    odd1: mainOdds.odd1,
    oddX: mainOdds.oddX,
    odd2: mainOdds.odd2,
    lastUpdated: row.last_updated
      ? new Date(row.last_updated as string).toISOString()
      : null,
  };
}

function mapOdds(row: Record<string, unknown>): OddsLine {
  const factorId = Number(row.factor_id);
  return {
    factorId,
    odds: Number(row.odds),
    lineParam: row.line_param != null ? Number(row.line_param) : null,
    lineParamText: row.line_param_text as string | null,
    isHandicapTotal: Boolean(row.is_handicap_total),
    marketEventName: row.market_event_name as string | null,
    outcomeLabel: OUTCOME_LABELS[factorId] ?? String(factorId),
  };
}

function mergeKnownSites(
  rows: Array<{ site_name: unknown; match_count: unknown }>,
): SiteOption[] {
  const counts = new Map(
    rows.map((row) => [String(row.site_name), Number(row.match_count)]),
  );

  return KNOWN_SITES.map((site) => ({
    siteName: site.siteName,
    label: site.label,
    matchCount: counts.get(site.siteName) ?? 0,
  }));
}

export async function fetchLiveDashboard(
  place: string | null = "live",
  limit = 80,
  sportName: string | null = null,
  siteName: string | null = null,
): Promise<{
  matches: LiveMatch[];
  sports: SportCategory[];
  sites: SiteOption[];
  selectedSport: string | null;
  selectedSite: string;
  stats: DashboardStats;
}> {
  const pool = getPool();
  const selectedSite = siteName && siteName.trim() ? siteName : defaultSiteName();

  const [sitesResult, sportsResult] = await Promise.all([
    pool.query(SITES_SQL, [place]),
    pool.query(SPORTS_SQL, [selectedSite, place]),
  ]);
  const sites = mergeKnownSites(sitesResult.rows);

  const sports: SportCategory[] = sortSportNames(
    sportsResult.rows.map((row) => String(row.sport_name)),
  ).map((name) => {
    const row = sportsResult.rows.find((r) => String(r.sport_name) === name);
    return {
      sportName: name,
      label: sportDisplayLabel(name),
      matchCount: row ? Number(row.match_count) : 0,
    };
  });

  const selectedSport =
    sportName && sports.some((s) => s.sportName === sportName)
      ? sportName
      : pickDefaultSportName(sports.map((s) => s.sportName));

  const [matchesResult, statsResult] = await Promise.all([
    pool.query(MATCHES_SQL, [selectedSite, place, limit, selectedSport]),
    pool.query(STATS_SQL, [selectedSite]),
  ]);

  const statsRow = statsResult.rows[0];
  const stats: DashboardStats = {
    liveMatches: statsRow ? Number(statsRow.live_matches) : 0,
    totalOdds: statsRow ? Number(statsRow.total_odds) : 0,
    lastSnapshotAt: statsRow?.imported_at
      ? new Date(statsRow.imported_at as string).toISOString()
      : null,
    packetVersion: statsRow?.packet_version != null
      ? Number(statsRow.packet_version)
      : null,
  };

  const matchIds = matchesResult.rows.map((r) => Number(r.match_id));
  const oddsByMatch = new Map<string, OddsLine[]>();

  if (matchIds.length > 0) {
    const oddsResult = await pool.query(ODDS_FOR_MATCHES_SQL, [selectedSite, matchIds]);
    for (const row of oddsResult.rows) {
      const key = `${String(row.site_name ?? selectedSite)}:${Number(row.match_id)}`;
      const list = oddsByMatch.get(key) ?? [];
      list.push(mapOdds(row));
      oddsByMatch.set(key, list);
    }
  }

  const matches = matchesResult.rows.map((row) => {
    const key = `${String(row.site_name)}:${Number(row.match_id)}`;
    const picked = pickDisplayOdds(oddsByMatch.get(key) ?? []);
    return mapMatch(row, picked);
  });

  return { matches, sports, sites, selectedSport, selectedSite, stats };
}
