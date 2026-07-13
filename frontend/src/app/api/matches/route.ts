import { NextRequest, NextResponse } from "next/server";

import { fetchLiveDashboard } from "@/lib/queries";
import { defaultSiteName } from "@/lib/db";
import { pollCommandForSelection } from "@/lib/site";
import type { MatchesResponse } from "@/lib/types";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = request.nextUrl;
    const place = searchParams.get("place") || "live";
    const limit = Math.min(Number(searchParams.get("limit") ?? 5000), 5000);
    const sport = searchParams.get("sport");
    const site = searchParams.get("site") || defaultSiteName();

    const { matches, sports, sites, selectedSport, selectedSite, stats } =
      await fetchLiveDashboard(
      place === "all" ? null : place,
      limit,
      sport,
      site,
      );

    const body: MatchesResponse = {
      matches,
      sports,
      sites,
      selectedSport,
      selectedSite,
      stats,
      fetchedAt: new Date().toISOString(),
      pollCommand: pollCommandForSelection(selectedSite),
    };

    return NextResponse.json(body);
  } catch (error) {
    console.error("GET /api/matches", error);
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Database error" },
      { status: 500 },
    );
  }
}
