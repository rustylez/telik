#!/usr/bin/env python3
"""Collects the fixtures of the coming days into sport.json, the file Telik's row "Sport live" reads.

Runs once a day as a GitHub Action in the public repository (see sport.yml next to this file);
Telik itself only downloads the result. Python's standard library is all it needs.

Sources, chosen for terms that allow this use:
- OpenLigaDB (https://www.openligadb.de), licensed under ODbL 1.0: fixtures of the Bundesliga and
  the Champions League. These entries of sport.json are therefore under ODbL 1.0 as well and
  name OpenLigaDB as their source.
- TheSportsDB (https://www.thesportsdb.com), free API key: fixtures of the other football
  leagues and of the national teams' competitions, read round by round (a whole round is the one question the free key answers in full;
  "what is on that day" is cut to three matches). Its terms allow to "scrape, copy and modify
  content returned from the API using the official end points"; the free key is for projects
  that are not published in an app store.
- Wikidata (CC0): how each team is called in German, Russian and English, by the Wikidata id a
  source gives for a team, or else by a search for the team's name among the clubs of its sport.
  Guides write "Бавария" or "FC Bayern München"; Telik needs these spellings to find a match in
  a guide. A national team is called by its country there ("Германия - Нидерланды"), so for
  these the country's names are taken.

Team badges are left out on purpose: no source grants rights to the pictures it links.

Names are asked from Wikidata once per team and kept in sport-teams.json, so a daily run only
asks for teams it has not seen. What Wikidata gets wrong is corrected in sport-names.json, which
is merged over it: {"search": {"soccer|Lazio": "Q2609"}, "Q2609": {"names": ["…"], "label": {"ru": "…"}}}.

A league whose source does not answer keeps its fixtures of the last run, so one bad day at a
source does not empty the row.

Usage: collect.py [output directory [time]]
  output directory: default the current directory.
  time: "2026-11-10T00:00" (UTC) to collect as if it were then, for checking against an older guide.
"""
import gzip
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# The services ask clients to name themselves with a way to reach them.
USER_AGENT = "telik-sportfeed/1 (https://github.com/rustylez/telik)"
DAYS_AHEAD = 7
# A match that began this long ago may still be running; Telik drops older ones itself.
HOURS_BACK = 4
LANGUAGES = ("de", "ru", "en")
MAX_NAME_CHARS = 40

# The Wikidata entity of each sport, as clubs name it in "sport" (P641).
SPORT_ENTITY = {"soccer": "Q2736", "hockey": "Q41466", "basketball": "Q5372"}
# What a hit must not be an "instance of" (P31): stadium, football stadium, sports venue, arena.
VENUES = {"Q483110", "Q1154710", "Q1076486", "Q641226"}

# OpenLigaDB league shortcut -> sport, league name, and its name by language.
OPENLIGADB = {
    "bl1": ("soccer", "Bundesliga", {"ru": "Бундеслига"}),
    "ucl": ("soccer", "Champions League", {"ru": "Лига чемпионов"}),
}

# In place of a league's country: its teams are national teams.
NATIONS = "nations"

# TheSportsDB league id -> sport, league name, its name by language, and the Wikidata entity of
# the league's country (P17 of its clubs), which tells "Brest" in France from "Brest" in Belarus.
THESPORTSDB = {
    4328: ("soccer", "Premier League", {"ru": "Премьер-лига"}, "Q145"),
    4335: ("soccer", "La Liga", {"ru": "Ла Лига"}, "Q29"),
    4332: ("soccer", "Serie A", {"ru": "Серия А"}, "Q38"),
    4334: ("soccer", "Ligue 1", {"ru": "Лига 1"}, "Q142"),
    4355: ("soccer", "Russian Premier League", {"ru": "РПЛ", "de": "Russische Premjer-Liga"}, "Q159"),
    4339: ("soccer", "Süper Lig", {"ru": "Суперлига Турции", "en": "Turkish Süper Lig"}, "Q43"),
    # Clubs from all over Europe: no country to go by.
    4481: ("soccer", "Europa League", {"ru": "Лига Европы"}, None),
    5071: ("soccer", "Conference League", {"ru": "Лига конференций"}, None),
    # National teams.
    4490: ("soccer", "Nations League", {"ru": "Лига наций"}, NATIONS),
    5518: ("soccer", "World Cup Qualifying", {"ru": "Отбор на чемпионат мира", "de": "WM-Qualifikation"}, NATIONS),
    4429: ("soccer", "World Cup", {"ru": "Чемпионат мира", "de": "Weltmeisterschaft"}, NATIONS),
    4502: ("soccer", "European Championship", {"ru": "Чемпионат Европы", "de": "Europameisterschaft"}, NATIONS),
}
THESPORTSDB_KEY = "123"
# 30 requests a minute are allowed; staying well below, as the limit is counted per address.
THESPORTSDB_PAUSE_S = 4
# The round of the next match and the one after it: enough for a week, also with a midweek round.
ROUNDS_AHEAD = 2


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
    return json.loads(data) if data.strip() else {}


def season(now):
    """The year a season is filed under: 2026 for 2026/27, which begins in summer."""
    return now.year if now.month >= 7 else now.year - 1


def in_window(start, now):
    return now - timedelta(hours=HOURS_BACK) <= start <= now + timedelta(days=DAYS_AHEAD)


def side(name, sport, wikidata=None, more=(), country=None):
    """A team as the source names it; "wikidata", "sport" and "country" are taken out again once the names are added."""
    return {"name": name, "names": [n for n in (name, *more) if n], "wikidata": wikidata or None, "sport": sport, "country": country}


def openligadb(shortcut, now):
    sport, league, league_label = OPENLIGADB[shortcut]
    events = []
    for match in fetch(f"https://api.openligadb.de/getmatchdata/{shortcut}/{season(now)}"):
        start = datetime.strptime(match["matchDateTimeUTC"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if not in_window(start, now):
            continue
        home, away = match["team1"], match["team2"]
        events.append({
            "id": f"openligadb:{match['matchID']}",
            "source": "OpenLigaDB",
            "sport": sport,
            "league": league,
            "leagueLabel": league_label,
            "start": int(start.timestamp()),
            "home": side(home["teamName"], sport, home.get("wikidataId"), [home.get("shortName")], "Q183" if shortcut == "bl1" else None),
            "away": side(away["teamName"], sport, away.get("wikidataId"), [away.get("shortName")], "Q183" if shortcut == "bl1" else None),
        })
    # One request per league a day; a pause between them all the same.
    time.sleep(1)
    return events


def thesportsdb_fetch(query):
    """One question to TheSportsDB, with a pause after it; waits a minute and asks again when told to slow down."""
    for attempt in range(3):
        try:
            answer = fetch(f"https://www.thesportsdb.com/api/v1/json/{THESPORTSDB_KEY}/{query}")
            time.sleep(THESPORTSDB_PAUSE_S)
            return answer
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == 2:
                raise
            time.sleep(65)
    raise AssertionError("not reached")


def thesportsdb(league_id, now):
    sport, league, league_label, country = THESPORTSDB[league_id]
    coming = thesportsdb_fetch(f"eventsnextleague.php?id={league_id}").get("events") or []
    if not coming:
        return []
    first_round = int(coming[0]["intRound"])
    season_name = urllib.parse.quote(coming[0]["strSeason"])
    events = []
    for number in range(first_round, first_round + ROUNDS_AHEAD):
        matches = thesportsdb_fetch(f"eventsround.php?id={league_id}&r={number}&s={season_name}").get("events") or []
        for match in matches:
            # "2026-11-21T14:30:00", UTC. A match without a time yet has none to look for in a guide.
            if not match.get("strTimestamp") or match.get("strPostponed") == "yes":
                continue
            start = datetime.strptime(match["strTimestamp"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            if not in_window(start, now):
                continue
            events.append({
                "id": f"thesportsdb:{match['idEvent']}",
                "source": "TheSportsDB",
                "sport": sport,
                "league": league,
                "leagueLabel": league_label,
                "start": int(start.timestamp()),
                "home": side(match["strHomeTeam"], sport, country=country),
                "away": side(match["strAwayTeam"], sport, country=country),
            })
    return events


def wikidata_search(name, sport, country):
    """
    The Wikidata id of the club called [name] that plays [sport], or None. Sources shorten names
    ("Valencia", "Lazio"), under which Wikidata lists the city or region first, so the usual club
    forms are tried as well. Taken is the first hit of that sport in [country] that is no
    stadium; where no try gives one, the first hit of that sport anywhere (Monaco plays in the
    French league). Wikidata's search puts the best known entry first, which is nearly always
    the club itself and not its reserve or women's team; what still goes wrong is set right in
    sport-names.json.
    """
    elsewhere = None
    for search in (name, f"{name} FC", f"FC {name}", f"{name} CF", f"{name} football club"):
        query = urllib.parse.urlencode({"action": "wbsearchentities", "search": search, "language": "en", "type": "item", "limit": 8, "format": "json"})
        hits = [hit["id"] for hit in fetch("https://www.wikidata.org/w/api.php?" + query).get("search", [])]
        time.sleep(1)
        if not hits:
            continue
        query = urllib.parse.urlencode({"action": "wbgetentities", "ids": "|".join(hits), "props": "claims", "format": "json"})
        entities = fetch("https://www.wikidata.org/w/api.php?" + query).get("entities", {})
        time.sleep(1)
        for hit in hits:
            claims = entities.get(hit, {}).get("claims", {})

            def values(prop):
                return {claim["mainsnak"].get("datavalue", {}).get("value", {}).get("id") for claim in claims.get(prop, [])}

            if SPORT_ENTITY[sport] not in values("P641") or values("P31") & VENUES:
                continue
            if country is None or country in values("P17"):
                return hit
            elsewhere = elsewhere or hit
    return elsewhere


# How TheSportsDB shortens some countries, and what their national team is filed under.
NATION_NAMES = {"N.Ireland": "Northern Ireland", "Bosnia-Herzegovina": "Bosnia and Herzegovina", "Ireland": "Republic of Ireland"}


def wikidata_nation(name, sport):
    """
    The Wikidata id of the country whose national team is called [name], or None: the national
    team is searched, and the country it plays for is read from it ("country for sport", P1532,
    which is England for England where "country" would say United Kingdom). Lists and history
    articles about a team carry no such entry, so they are passed over.
    """
    name = NATION_NAMES.get(name, name)
    for search in (f"{name} national football team", f"{name} men's national football team", f"{name} national association football team"):
        query = urllib.parse.urlencode({"action": "wbsearchentities", "search": search, "language": "en", "type": "item", "limit": 5, "format": "json"})
        hits = [hit["id"] for hit in fetch("https://www.wikidata.org/w/api.php?" + query).get("search", [])]
        time.sleep(1)
        if not hits:
            continue
        query = urllib.parse.urlencode({"action": "wbgetentities", "ids": "|".join(hits), "props": "claims", "format": "json"})
        entities = fetch("https://www.wikidata.org/w/api.php?" + query).get("entities", {})
        time.sleep(1)
        for hit in hits:
            claims = entities.get(hit, {}).get("claims", {})

            def values(prop):
                return [claim["mainsnak"].get("datavalue", {}).get("value", {}).get("id") for claim in claims.get(prop, [])]

            countries = [c for c in values("P1532") if c]
            if SPORT_ENTITY[sport] in values("P641") and countries:
                return countries[0]
    return None


def wikidata_names(ids):
    """Labels and aliases of the Wikidata entities [ids] in LANGUAGES: {id: {"label": {...}, "names": [...]}}."""
    result = {}
    ids = sorted(ids)
    for i in range(0, len(ids), 50):
        query = urllib.parse.urlencode({
            "action": "wbgetentities", "ids": "|".join(ids[i:i + 50]), "props": "labels|aliases",
            "languages": "|".join(LANGUAGES), "format": "json",
        })
        entities = fetch("https://www.wikidata.org/w/api.php?" + query).get("entities", {})
        for entity_id, entity in entities.items():
            label = {language: value["value"] for language, value in entity.get("labels", {}).items()}
            names = list(label.values())
            for aliases in entity.get("aliases", {}).values():
                names += [alias["value"] for alias in aliases]
            result[entity_id] = {"label": label, "names": names}
        time.sleep(1)
    return result


def usable(name):
    """Whether a spelling helps to find a team: not a sentence, and not a note in brackets."""
    return 3 <= len(name) <= MAX_NAME_CHARS and "(" not in name and "," not in name


# What clubs carry before their name; guides often leave it out ("РБ Лейпциг" is just "Лейпциг").
PREFIXES = ("1. FC", "1. FSV", "FC", "FK", "SC", "SV", "VfB", "VfL", "TSG", "RB", "AS", "AC", "ФК", "РБ", "ХК", "БК", "ПФК")
# And after it ("Arsenal F.C.", "Valencia CF").
SUFFIXES = ("F.C.", "FC", "CF", "C.F.", "A.F.C.", "AFC", "S.K.", "SK")


def variants(name):
    """[name] and its shorter forms: without what clubs carry before or after it, without a number at the end ("Шальке 04" → "Шальке")."""
    result = [name]
    for prefix in PREFIXES:
        if name.startswith(prefix + " "):
            result.append(name[len(prefix) + 1:])
    for suffix in SUFFIXES:
        if name.endswith(" " + suffix):
            result.append(name[:-len(suffix) - 1])
    for form in list(result):
        words = form.split(" ")
        if len(words) > 1 and words[-1].isdigit():
            result.append(" ".join(words[:-1]))
    # A short form must still say something: "FC 04" would leave nothing.
    return [form for form in result if form == name or len(form) >= 4]


def unique(names):
    seen = set()
    result = []
    for name in names:
        key = name.casefold()
        if key not in seen:
            seen.add(key)
            result.append(name)
    return result


def read(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    now = datetime.strptime(sys.argv[2], "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc) if len(sys.argv) > 2 else datetime.now(timezone.utc)
    before = read(out / "sport.json", {}).get("events", [])

    events = []
    kept = []
    leagues = [(openligadb, key, OPENLIGADB[key][1]) for key in OPENLIGADB] + [(thesportsdb, key, THESPORTSDB[key][1]) for key in THESPORTSDB]
    for collect, key, league in leagues:
        try:
            events += collect(key, now)
        except (OSError, ValueError, KeyError) as error:
            # The source is down, slow or answers something else today: the last run's fixtures stay.
            old = [event for event in before if event.get("league") == league and in_window(datetime.fromtimestamp(event["start"], timezone.utc), now)]
            kept += old
            print(f"{league}: not read ({type(error).__name__}: {error}); {len(old)} fixtures kept from the last run")

    known = read(out / "sport-teams.json", {})
    fixed = read(out / "sport-names.json", {})
    sides = [event[place] for event in events for place in ("home", "away")]
    # A team the source gives no Wikidata id for: searched by name once, the answer (also "none") kept.
    found = known.setdefault("search", {})
    found.update(fixed.get("search", {}))
    for team in sides:
        sport = team.pop("sport")
        country = team.pop("country")
        team["nation"] = country == NATIONS
        if team["nation"]:
            key = f"nation|{team['name']}"
            if key not in found:
                found[key] = wikidata_nation(team["name"], sport)
            team["wikidata"] = found[key]
        elif not team["wikidata"]:
            key = f"{sport}|{team['name']}"
            if key not in found:
                found[key] = wikidata_search(team["name"], sport, country)
            team["wikidata"] = found[key]
    missing = {team["wikidata"] for team in sides if team["wikidata"]} - set(known)
    if missing:
        known.update(wikidata_names(missing))
    write(out / "sport-teams.json", known)

    for team in sides:
        entity_id = team.pop("wikidata")
        nation = team.pop("nation")
        label = {}
        names = list(team["names"])
        for entry in (known.get(entity_id), fixed.get(entity_id)):
            if entry:
                # A country has dozens of other names ("BRD", "FRG"); a guide uses its plain one.
                names += list(entry.get("label", {}).values()) if nation and entry is not fixed.get(entity_id) else entry.get("names", [])
                label.update(entry.get("label", {}))
        team["names"] = unique(form for n in names if usable(n) for form in variants(n))
        team["label"] = label

    events = sorted(events + kept, key=lambda e: (e["start"], e["id"]))
    # Every league the file may hold, also one without a match this week: Telik offers them for
    # choosing, and a league added here appears there without a new Telik.
    tables = [OPENLIGADB[key] for key in OPENLIGADB] + [THESPORTSDB[key][:3] for key in THESPORTSDB]
    write(out / "sport.json", {
        "version": 1,
        "generated": int(now.timestamp()),
        # Shown by Telik at the row.
        "credit": ", ".join(unique(event["source"] for event in events if event.get("source"))),
        "license": "Fixtures marked OpenLigaDB: www.openligadb.de, ODbL 1.0. Fixtures marked TheSportsDB: www.thesportsdb.com. Team names: Wikidata, CC0.",
        "leagues": [{"name": name, "sport": sport, "label": label} for sport, name, label in tables],
        "events": events,
    })
    unnamed = sorted({team["name"] for team in sides if not team["label"]})
    print(f"{len(events)} fixtures, {len(missing)} teams newly named" + (f"; without a Wikidata entry: {', '.join(unnamed)}" if unnamed else ""))


if __name__ == "__main__":
    main()
