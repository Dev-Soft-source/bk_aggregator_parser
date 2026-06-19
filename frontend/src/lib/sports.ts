/** DB sport_name → English label for the category menu. */
const DISPLAY_LABELS: Record<string, string> = {
  Football: "Soccer",
  Футбол: "Soccer",
  Soccer: "Soccer",
  Футзал: "Futsal",
  Баскетбол: "Basketball",
  Basketball: "Basketball",
  Теннис: "Tennis",
  Tennis: "Tennis",
  Хоккей: "Hockey",
  Hockey: "Hockey",
  Волейбол: "Volleyball",
  Volleyball: "Volleyball",
  "Настольный теннис": "Table tennis",
  "Table tennis": "Table tennis",
  Гандбол: "Handball",
  Handball: "Handball",
  Бейсбол: "Baseball",
  Baseball: "Baseball",
  Регби: "Rugby",
  Rugby: "Rugby",
  Дартс: "Darts",
  Darts: "Darts",
  "Пляжный волейбол": "Beach volleyball",
  "E-sport": "E-sport",
  Киберспорт: "E-sport",
};

const SOCCER_NAMES = new Set(["Football", "Футбол", "Soccer"]);

export const DEFAULT_SPORT_LABEL = "Soccer";

export function sportDisplayLabel(sportName: string): string {
  return DISPLAY_LABELS[sportName] ?? sportName;
}

export function isSoccerSport(sportName: string): boolean {
  return SOCCER_NAMES.has(sportName);
}

export function pickDefaultSportName(sportNames: string[]): string | null {
  const soccer = sportNames.find(isSoccerSport);
  if (soccer) return soccer;
  const byLabel = sportNames.find(
    (name) => sportDisplayLabel(name) === DEFAULT_SPORT_LABEL,
  );
  return byLabel ?? sportNames[0] ?? null;
}

export function sortSportNames(names: string[]): string[] {
  return [...names].sort((a, b) => {
    const aSoccer = isSoccerSport(a);
    const bSoccer = isSoccerSport(b);
    if (aSoccer !== bSoccer) return aSoccer ? -1 : 1;
    return sportDisplayLabel(a).localeCompare(sportDisplayLabel(b));
  });
}
