import { NextRequest, NextResponse } from "next/server";

import { fetchLiveDashboard } from "@/lib/queries";
import type { MatchesResponse } from "@/lib/types";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = request.nextUrl;
    const place = searchParams.get("place") || "live";
    const limit = Math.min(Number(searchParams.get("limit") ?? 80), 200);

    const { matches, stats } = await fetchLiveDashboard(
      place === "all" ? null : place,
      limit,
    );

    const body: MatchesResponse = {
      matches,
      stats,
      fetchedAt: new Date().toISOString(),
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
