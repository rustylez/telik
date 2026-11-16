# telik
Telik: installation files and update information. No source code.

## Sport fixtures

`sport.json` lists football matches of the coming days (Bundesliga, Champions League) for Telik's row "Sport live". It is written once a day by `tools/sportfeed/collect.py` (see `.github/workflows/sport.yml`).

- Fixtures: data from [OpenLigaDB](https://www.openligadb.de), licensed under [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/). The fixtures in `sport.json` are made available under the same licence.
- Team names in German, Russian and English: [Wikidata](https://www.wikidata.org), CC0. `sport-teams.json` keeps them between runs.
