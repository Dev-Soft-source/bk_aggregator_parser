import { NextRequest, NextResponse } from "next/server";

import { fetchLiveDashboard } from "@/lib/queries";
import { pollCommandForSite } from "@/lib/site";
import { siteName } from "@/lib/db";
import type { MatchesResponse } from "@/lib/types";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = request.nextUrl;
    const place = searchParams.get("place") || "live";
    const limit = Math.min(Number(searchParams.get("limit") ?? 5000), 5000);
    const sport = searchParams.get("sport");

    const { matches, sports, selectedSport, stats } = await fetchLiveDashboard(
      place === "all" ? null : place,
      limit,
      sport,
    );

    const site = siteName();
    const body: MatchesResponse = {
      matches,
      sports,
      selectedSport,
      stats,
      fetchedAt: new Date().toISOString(),
      siteName: site,
      pollCommand: pollCommandForSite(site),
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
