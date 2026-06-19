import { getPool, siteName } from "./db";
import {
  pickDefaultSportName,
  sortSportNames,
  sportDisplayLabel,
} from "./sports";
import type { DashboardStats, LiveMatch, OddsLine, SportCategory } from "./types";

const SPORT_NAME_SQL = `CASE WHEN sp.reference_sport_id = 1 THEN 'Football' ELSE sp.name_en END`;

const SPORTS_SQL = `
SELECT
    ${SPORT_NAME_SQL} AS sport_name,
    COUNT(*)::int AS match_count
FROM matches m
JOIN sites st ON st.id = m.site_id
JOIN sports sp ON sp.site_id = m.site_id AND sp.id = m.sport_id
WHERE st.name = $1
  AND ($2::text IS NULL OR m.place = $2)
GROUP BY 1
ORDER BY match_count DESC, sport_name ASC
`;

const MATCHES_SQL = `
SELECT
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
WHERE st.name = $1
  AND ($2::text IS NULL OR m.place = $2)
  AND ($4::text IS NULL OR ${SPORT_NAME_SQL} = $4)
ORDER BY
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
     WHERE st.name = $1 AND m.place = 'live') AS live_matches,
    (SELECT COUNT(*)::int FROM odds_lines o
     JOIN sites st ON st.id = o.site_id
     WHERE st.name = $1) AS total_odds,
    s.imported_at,
    s.packet_version
FROM import_snapshots s
JOIN sites st ON st.id = s.site_id
WHERE st.name = $1
ORDER BY s.id DESC
LIMIT 1
`;

function oddsFactorIds(): number[] {
  const raw = process.env.ODDS_FACTOR_IDS ?? "921,923";
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

/** Prefer 921/923; fall back to other two-way winner markets (tennis, basketball, …). */
function pickDisplayOdds(lines: OddsLine[]): OddsLine[] {
  const factorIds = oddsFactorIds();
  const configured = sortOddsByConfig(lines, factorIds);
  if (configured.length >= 2) {
    return configured.slice(0, 2);
  }

  const by921923 = sortOddsByConfig(lines, [921, 923]);
  if (by921923.length >= 2) {
    return by921923;
  }

  const byMarket = new Map<string, OddsLine[]>();
  for (const line of lines) {
    if (line.isHandicapTotal) continue;
    const key = line.lineParam != null ? String(line.lineParam) : "none";
    const group = byMarket.get(key) ?? [];
    group.push(line);
    byMarket.set(key, group);
  }

  const preferredMarkets = [1777, 1763, 1450, 1446, 910080, 920054, 780112, 170153];
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
    const std = sortOddsByConfig(group, [921, 923]);
    if (std.length >= 2) return std;
    return group.slice(0, 2);
  }

  return configured;
}

const ODDS_FOR_MATCHES_SQL = `
SELECT DISTINCT ON (o.match_id, o.factor_id, o.line_param)
    o.match_id,
    o.factor_id,
    o.odds::float8 AS odds,
    o.line_param_text,
    o.is_handicap_total,
    o.market_event_name,
    o.line_param
FROM odds_lines o
JOIN sites st ON st.id = o.site_id
WHERE st.name = $1
  AND o.match_id = ANY($2::bigint[])
ORDER BY o.match_id, o.factor_id, o.line_param,
    o.snapshot_id DESC NULLS LAST
`;

function mapMatch(
  row: Record<string, unknown>,
  mainOdds: OddsLine[],
): LiveMatch {
  return {
    matchId: Number(row.match_id),
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
    odd1: mainOdds[0]?.odds ?? null,
    odd2: mainOdds[1]?.odds ?? null,
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

export async function fetchLiveDashboard(
  place: string | null = "live",
  limit = 80,
  sportName: string | null = null,
): Promise<{
  matches: LiveMatch[];
  sports: SportCategory[];
  selectedSport: string | null;
  stats: DashboardStats;
}> {
  const pool = getPool();
  const site = siteName();

  const sportsResult = await pool.query(SPORTS_SQL, [site, place]);
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
    pool.query(MATCHES_SQL, [site, place, limit, selectedSport]),
    pool.query(STATS_SQL, [site]),
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
  const oddsByMatch = new Map<number, OddsLine[]>();

  if (matchIds.length > 0) {
    const oddsResult = await pool.query(ODDS_FOR_MATCHES_SQL, [site, matchIds]);
    for (const row of oddsResult.rows) {
      const matchId = Number(row.match_id);
      const list = oddsByMatch.get(matchId) ?? [];
      list.push(mapOdds(row));
      oddsByMatch.set(matchId, list);
    }
  }

  const matches = matchesResult.rows.map((row) => {
    const matchId = Number(row.match_id);
    const picked = pickDisplayOdds(oddsByMatch.get(matchId) ?? []);
    return mapMatch(row, picked);
  });

  return { matches, sports, selectedSport, stats };
}
