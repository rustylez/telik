# telik
Telik: installation files and update information. No source code.

## Sport fixtures

`sport.json` lists football matches of the coming days for Telik's row "Sport live". It is written once a day by `tools/sportfeed/collect.py` (see `.github/workflows/sport.yml`). Each fixture names its source.

- Bundesliga, Champions League: data from [OpenLigaDB](https://www.openligadb.de), licensed under [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/). These fixtures in `sport.json` are made available under the same licence.
- Premier League, La Liga, Serie A, Ligue 1, Russian Premier League, Europa League, Conference League, and the national teams (Nations League, World Cup and its qualifying, European Championship): data from [TheSportsDB](https://www.thesportsdb.com), read through its free API.
- Team and country names in German, Russian and English: [Wikidata](https://www.wikidata.org), CC0. `sport-teams.json` keeps them between runs, `sport-names.json` holds corrections.
