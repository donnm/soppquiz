# Pensum Soppquiz

This is a simple quiz for studying the NSNF pensum for the **prøve for soppsakkyndige** (the Norwegian exam to become a certified mushroom inspector).

The quiz is designed to be keyboard only for speed. Each question shows photos of a species and asks for:

1. What is this mushroom? (Norwegian name, e.g., *rød fluesopp*)
2. What is its **normlistestatus**? Answer using the standard NSNF codes `s` / `smm` / `im` / `g` / `mg`. (See below for abbreviations)

A live instance runs at <https://soppquiz.mooo.com> (the original version is archived at <https://soppquiz.mooo.com/old/>, and kept in this repo as `old_app.py` for reference).

---

## Keyboard workflow

| Key / action | What it does |
| --- | --- |
| `↑` / `↓` | Browse the species suggestions |
| `Enter` | Submit the answer, then advance to the next question |
| `Esc` | Close / clear the current input |
| `R` | Skip to a new random question |
| Type a code | Enter the normstatus in the status field (`s`, `smm`, `im`, `g`, `mg`) |

Start typing the Norwegian name and pick from the autocomplete list. Feedback shows whether the name and/or status were right, with the normlistestatus comment (merknad) if one exists.

### Normstatus codes

| Code | Meaning |
| --- | --- |
| `s` | Spiselig |
| `smm` | Spiselig med merknad |
| `im` | Ikke matsopp |
| `g` | Giftig |
| `mg` | Meget giftig |

Hover the `?` next to the Normstatus field (or the codes in the hint bar) to see this legend.

## Photo sources

Images are pulled from **Artsobservasjoner.no** (via the GBIF dataset *Norwegian Species Observation Service*), and only **Creative Commons-licensed** photos are used. Each photo has a small `CC` badge in its bottom right corner; hover it to see the photographer and the license. The source is linked in the site footer.

`IMAGE_SOURCE` (env) selects the source:

| Value | Images |
| --- | --- |
| `artsobs` (default) | Artsobservasjoner when available, otherwise other CC sources for species Artsobservasjoner has no photos of |
| `all` | Any CC-licensed image in the GBIF aggregate (Artsobservasjoner, iNaturalist, etc.) |

## Keeping the pensum current

The NSNF normlist is revised by the Fagmykologisk råd, and statuses change over time (a species can be reclassified between `spiselig`, `ikke matsopp`, `giftig`, and `meget giftig`, or a change to its merknad), and the exam pensum is updated yearly.

The quiz content lives entirely in **`pensum.json`**. Update it each year when the new normlist/pensum is published:

```json
{
  "id": "98",
  "norsknavn": "potetrøyksopper",
  "latinsknavn": "Scleroderma spp",
  "normstatus": "giftig",
  "kommentar": null
}
```

- `norsknavn` and `latinsknavn`: identification answers (Norwegian name required; empty/`null` optional latin is fine, and the app also matches genus-level entries).
- `normstatus`: must be one of `spiselig`, `spiselig med merknad`, `ikke matsopp`, `giftig`, `meget giftig`.
- `kommentar`: optional NSNF comment shown to the learner after answering.

The live pensum currently covers 148 species/groups, all with usable CC-licensed photos. Three species (skarp gulkremle, grønnkremle, gullskjellsopp) have no Artsobservasjoner photos and are filled from other CC sources in the GBIF aggregate.

## Running locally

```bash
docker compose up --build
```

Environment variables (all optional):

| Variable | Default | Purpose |
| --- | --- | --- |
| `IMAGE_SOURCE` | `artsobs` | `artsobs` or `all` (see above) |
| `DISK_CACHE_PATH` | in-memory only | File path for caching the image/photo lookup results to disk |
| `PORT` | `5000` | Internal HTTP port |

The project ships a `Dockerfile` (Flask + Werkzeug, served via `python app.py`).

## Links

- **Normlisten** (NSNF): <https://soppognyttevekster.no/sopp/normlisten/>
- **Normlisten 2026** (PDF): <https://soppognyttevekster.no/wp-content/uploads/2026/04/Normlisten-2026.pdf>
- **Pensumliste for prøve for soppsakkyndige** (PDF): <https://soppognyttevekster.no/wp-content/uploads/2026/05/Pensumliste-SSK-2026-3-1-1.pdf>
- **Soppsakkyndig course & becoming a soppkontrollør** (NSNF): <https://soppognyttevekster.no/sopp/hvordan-jobber-forbundet-med-sopp/>
- **Retningslinjer for prøve for soppsakkyndige** (PDF): <https://soppognyttevekster.no/wp-content/uploads/2024/06/Retningslinjer_Prove-for-soppsakkyndige_231231-.docx.pdf>
- **Soppkontroll** (NSNF): <https://soppkontroll.no/>
