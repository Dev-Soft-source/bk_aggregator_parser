/** Backend poll CLI hint for the configured bookmaker site. */
export function pollCommandForSite(siteName: string): string {
  switch (siteName) {
    case "bet365.com":
      return "python main.py poll bet365";
    case "ligastavok.ru":
      return "python main.py poll ligastavok --browser";
    default:
      return "python main.py poll";
  }
}
