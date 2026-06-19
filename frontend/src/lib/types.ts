export interface SportCategory {
  sportName: string;
  label: string;
  matchCount: number;
}

export interface OddsLine {
  factorId: number;
  odds: number;
  lineParamText: string | null;
  isHandicapTotal: boolean;
  marketEventName: string | null;
  outcomeLabel?: string;
}

export interface LiveMatch {
  matchId: number;
  team1: string | null;
  team2: string | null;
  place: string;
  startTime: string | null;
  priority: number | null;
  sportName: string;
  leagueName: string | null;
  countryName: string | null;
  score1: number | null;
  score2: number | null;
  timerDisplay: string | null;
  timerSeconds: number | null;
  scoreUpdatedAt: string | null;
  scoreFunction: string | null;
  bettingState: string | null;
  odd1: number | null;
  odd2: number | null;
  lastUpdated: string | null;
}

export interface DashboardStats {
  liveMatches: number;
  totalOdds: number;
  lastSnapshotAt: string | null;
  packetVersion: number | null;
}

export interface MatchesResponse {
  matches: LiveMatch[];
  sports: SportCategory[];
  selectedSport: string | null;
  stats: DashboardStats;
  fetchedAt: string;
}
