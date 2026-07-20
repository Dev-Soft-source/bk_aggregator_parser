export const KNOWN_SITES = [
  { siteName: "fonbet.com", label: "Fonbet" },
  { siteName: "ligastavok.ru", label: "Liga Stavok" },
  { siteName: "bet365.com", label: "Bet365" },
  { siteName: "betcity.ru", label: "Betcity" },
  { siteName: "1xbet.com", label: "1xBet" },
] as const;

export function siteLabel(siteName: string): string {
  return KNOWN_SITES.find((site) => site.siteName === siteName)?.label ?? siteName;
}

/** Backend poll CLI hint for the configured bookmaker site. */
export function pollCommandForSite(siteName: string): string {
  switch (siteName) {
    case "bet365.com":
      return "python main.py poll bet365";
    case "ligastavok.ru":
      // Also: python main.py poll ligastavok-line
      return "python main.py poll ligastavok-live";
    case "betcity.ru":
      return "python main.py poll betcity --browser";
    case "1xbet.com":
      return "python main.py poll lxbet-live";
    default:
      return "python main.py poll";
  }
}

export function pollCommandForSelection(siteName: string): string | null {
  if (siteName === "all") {
    return null;
  }
  return pollCommandForSite(siteName);
}
