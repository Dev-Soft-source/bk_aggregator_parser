import type { DashboardStats } from "@/lib/types";

interface StatsBarProps {
  stats: DashboardStats;
  fetchedAt: string;
  isRefreshing: boolean;
}

export function StatsBar({ stats, fetchedAt, isRefreshing }: StatsBarProps) {
  const updated = stats.lastSnapshotAt
    ? new Date(stats.lastSnapshotAt).toLocaleTimeString()
    : "—";

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <StatCard label="Live matches" value={String(stats.liveMatches)} />
      <StatCard label="Odds lines" value={String(stats.totalOdds)} />
      <StatCard
        label="Packet version"
        value={stats.packetVersion != null ? String(stats.packetVersion) : "—"}
      />
      <StatCard
        label="Last DB update"
        value={updated}
        hint={isRefreshing ? "Refreshing…" : `Polled ${new Date(fetchedAt).toLocaleTimeString()}`}
      />
    </div>
  );
}

function StatCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-400">
        {label}
      </p>
      <p className="mt-1 text-2xl font-semibold text-white">{value}</p>
      {hint ? <p className="mt-1 text-xs text-slate-500">{hint}</p> : null}
    </div>
  );
}
