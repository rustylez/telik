#!/usr/bin/env python3
"""Collects the fixtures of the coming days into sport.json, the file Telik's row "Sport live" reads.

Runs once a day as a GitHub Action in the public repository (see sport.yml next to this file);
Telik itself only downloads the result. Python's standard library is all it needs.

Sources, chosen for terms that allow this use:
- OpenLigaDB (https://www.openligadb.de), licensed under ODbL 1.0: fixtures of the Bundesliga and
  the Champions League. The fixture part of sport.json is therefore under ODbL 1.0 as well and
  names OpenLigaDB as its source.
- Wikidata (CC0): how each team is called in German, Russian and English, by the Wikidata id
  OpenLigaDB gives for a team, or else by a search for the team's name among the clubs of its
  sport. Guides write "Бавария" or "FC Bayern München"; Telik needs these spellings to find a
  match in a guide.

Team badges are left out on purpose: OpenLigaDB grants no rights to the pictures it links and
asks not to embed them, and no other source grants them either.

Names are asked from Wikidata once per team and kept in sport-teams.json, so a daily run only
asks for teams it has not seen. A wrong or missing spelling is corrected in sport-names.json
({"<wikidata id>": {"names": ["…"], "label": {"ru": "…"}}}), which is merged over what Wikidata says.

Usage: collect.py [output directory [time]]
  output directory: default the current directory.
  time: "2026-11-10T00:00" (UTC) to collect as if it were then, for checking against an older guide.
"""
import gzip
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Both services ask clients to name themselves with a way to reach them.
USER_AGENT = "telik-sportfeed/1 (https://github.com/rustylez/telik)"
DAYS_AHEAD = 7
# A match that began this long ago may still be running; Telik drops older ones itself.
HOURS_BACK = 4
LANGUAGES = ("de", "ru", "en")
MAX_NAME_CHARS = 40

# The Wikidata entity of each sport, as clubs name it in "sport" (P641).
SPORT_ENTITY = {"soccer": "Q2736", "hockey": "Q41466", "basketball": "Q5372"}

# OpenLigaDB league shortcut -> sport, league name, and its name by language.
OPENLIGADB = {
    "bl1": ("soccer", "Bundesliga", {"ru": "Бундеслига"}),
    "ucl": ("soccer", "Champions League", {"ru": "Лига чемпионов"}),
}


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
    return json.loads(data)


def season(now):
    """The year a season is filed under: 2026 for 2026/27, which begins in summer."""
    return now.year if now.month >= 7 else now.year - 1


def openligadb(now):
    events = []
    first = now - timedelta(hours=HOURS_BACK)
    last = now + timedelta(days=DAYS_AHEAD)
    for shortcut, (sport, league, league_label) in OPENLIGADB.items():
        matches = fetch(f"https://api.openligadb.de/getmatchdata/{shortcut}/{season(now)}")
        for match in matches:
            start = datetime.strptime(match["matchDateTimeUTC"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if not first <= start <= last:
                continue
            events.append({
                "id": f"openligadb:{match['matchID']}",
                "sport": sport,
                "league": league,
                "leagueLabel": league_label,
                "start": int(start.timestamp()),
                "home": team(match["team1"], sport),
                "away": team(match["team2"], sport),
            })
        # One request per league a day; a pause between them all the same.
        time.sleep(1)
    return events


def team(source, sport):
    """A team as the source names it; "wikidata" and "sport" are taken out again once the names are added."""
    names = [source.get("teamName"), source.get("shortName")]
    return {"name": source["teamName"], "names": [n for n in names if n], "wikidata": source.get("wikidataId") or None, "sport": sport}


def wikidata_search(name, sport):
    """The Wikidata id of the club called [name] that plays [sport], or None: the first search hit with that sport."""
    query = urllib.parse.urlencode({"action": "wbsearchentities", "search": name, "language": "en", "type": "item", "limit": 8, "format": "json"})
    hits = [hit["id"] for hit in fetch("https://www.wikidata.org/w/api.php?" + query).get("search", [])]
    time.sleep(1)
    if not hits:
        return None
    query = urllib.parse.urlencode({"action": "wbgetentities", "ids": "|".join(hits), "props": "claims", "format": "json"})
    entities = fetch("https://www.wikidata.org/w/api.php?" + query).get("entities", {})
    time.sleep(1)
    for hit in hits:
        sports = [claim["mainsnak"].get("datavalue", {}).get("value", {}).get("id") for claim in entities.get(hit, {}).get("claims", {}).get("P641", [])]
        if SPORT_ENTITY[sport] in sports:
            return hit
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


def variants(name):
    """[name] and its shorter forms: without a club prefix, without a number at the end ("Шальке 04" → "Шальке")."""
    result = [name]
    for prefix in PREFIXES:
        if name.startswith(prefix + " "):
            result.append(name[len(prefix) + 1:])
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
    events = sorted(openligadb(now), key=lambda e: (e["start"], e["id"]))

    known = read(out / "sport-teams.json", {})
    fixed = read(out / "sport-names.json", {})
    sides = [event[side] for event in events for side in ("home", "away")]
    # A team the source gives no Wikidata id for: searched by name once, the answer (also "none") kept.
    found = known.setdefault("search", {})
    for side in sides:
        sport = side.pop("sport")
        if not side["wikidata"]:
            key = f"{sport}|{side['name']}"
            if key not in found:
                found[key] = wikidata_search(side["name"], sport)
            side["wikidata"] = found[key]
    missing = {side["wikidata"] for side in sides if side["wikidata"]} - set(known)
    if missing:
        known.update(wikidata_names(missing))
    write(out / "sport-teams.json", known)

    for side in sides:
        entity_id = side.pop("wikidata")
        label = {}
        names = list(side["names"])
        for entry in (known.get(entity_id), fixed.get(entity_id)):
            if entry:
                names += entry.get("names", [])
                label.update(entry.get("label", {}))
        side["names"] = unique(form for n in names if usable(n) for form in variants(n))
        side["label"] = label

    write(out / "sport.json", {
        "version": 1,
        "generated": int(now.timestamp()),
        "license": "Fixtures: OpenLigaDB (www.openligadb.de), ODbL 1.0. Team names: Wikidata, CC0.",
        "events": events,
    })
    print(f"{len(events)} fixtures, {len(missing)} teams newly named")


if __name__ == "__main__":
    main()
