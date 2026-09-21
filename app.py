"""
Pensum soppquiz: keyboard-first quiz.

Much like soppquiz.mooo.com: a random species from pensum.json is picked,
a few CC-licensed photos are fetched (Artsobservasjoner.no when available,
otherwise other CC sources), and you type/select the species name and its
edibility status.

The quiz is fully controllable from the keyboard:
  * type the species name -> arrow keys + Enter to pick from the suggestions
  * type the edibility status as its code: s/smm/im/g/mg
  * Enter submits, Enter advances to the next question

Run with:  flask --app app run   (or  python3 app.py)
Place your real pensum.json (list of {"norsknavn": ..., "normstatus": ...,
"kommentar": ...}) in this directory before going live.
"""

import json
import logging
import random
import re
import time
import threading

import urllib3
import requests
import os

from flask import Flask, jsonify, request
from markupsafe import escape

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("soppquiz")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE = "https://artsobservasjoner.no"
UA = ("Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/115.0")

PENSUM_PATH = "pensum.json"
IMAGES_PER_QUESTION = 4
IMAGE_CACHE_TTL = 15 * 60  # seconds

# Hvilke bilder som brukes: "artsobs" -> kun artsobservasjoner.no, "all" ->
# alle CC-lisensierte bilder via GBIF (Artsobservasjoner, iNaturalist m.fl.).
IMAGE_SOURCE = (os.environ.get("IMAGE_SOURCE") or "artsobs").strip().lower()

# Norsk navn (små bokstaver) -> latinsk navn, bygget fra pensum.json ved
# lasting. Brukes til å koble et pensum-navn til en GBIF usageKey.
_LATIN_BY_NAME = {}

# Edibility statuses, keyed by the short code.
STATUS = {
    "s": "spiselig",
    "smm": "spiselig med merknad",
    "im": "ikke matsopp",
    "g": "giftig",
    "mg": "meget giftig",
}

# Revers kart: fullt norsk statusord -> kort kode (for pensum.json som lagrer
# normstatus som tekst fremfor kode).
_CODE_FROM_FULL = {full: code for code, full in STATUS.items()}


def _code_for(text):
    """Fullt norsk statusord -> kort kode. Faller tilbake på forbokstaver."""
    t = (text or "").strip().lower()
    if not t:
        return ""
    if t in _CODE_FROM_FULL:
        return _CODE_FROM_FULL[t]
    initials = "".join(word[0] for word in t.split())
    return initials if initials in STATUS else ""


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Bildesøk via GBIF-API (api.gbif.org)
#
# Pensumet oppgis med latinsknavn. For hver art:
#   1. species/match  -> finn godtatt usageKey (følger synonymer)
#   2. occurrence/search (mediaType=StillImage) -> bilde-URLer
# Prefererer bilder fra Artsobservasjoner/MediaLibrary (samme bilder som
# den opprinnelige quizzen brukte), men faller tilbake på alle andre
# StillImage-medier GBIF har. Resultatene disk-cachet, så quizzen er rask
# og tåler korte nettverksbrudd uten å felle spørsmål.
# ---------------------------------------------------------------------------

GBIF_BASE = "https://api.gbif.org/v1"
_gbif_session = requests.Session()
_gbif_session.headers.update({"User-Agent": UA, "Accept": "application/json"})

IMAGE_CACHE_TTL = 24 * 60 * 60  # disk-cache gyldig i ett døgn
DISK_CACHE_PATH = os.environ.get(
    "DISK_CACHE_PATH", "soppquiz_cache.json"
)  # disk-cachefil (override for f.eks. Docker-volum)
_recent = []  # recently shown species, to avoid immediate repeats


def _latin_for(name):
    """latinsknavn fra pensum for et norsk navn (fra load-time-lista)."""
    return _LATIN_BY_NAME.get(name) or ""


# --- takson-oppslag ----------------------------------------------------------

def _follow_synonym_species_match(resp):
    """Utpek godtatt usageKey fra et species/match-svar."""
    if not isinstance(resp, dict):
        return None
    status = resp.get("status") or ""
    usage = resp.get("usageKey")
    if status == "SYNONYM":
        return resp.get("acceptedUsageKey") or usage
    if resp.get("matchType") == "NONE":
        return None
    return usage


def _match_taxon_key(latin):
    """Returner (usageKey, scientific_name) eller (None, None)."""
    try:
        r = _gbif_session.get(
            f"{GBIF_BASE}/species/match",
            params={"name": latin, "limit": 1},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        uk = _follow_synonym_species_match(data)
        if uk and data.get("matchType") != "NONE":
            return uk, data.get("scientificName") or latin
    except Exception as exc:  # noqa: BLE001
        log.warning("GBIF species/match %r mislyktes: %s", latin, exc)
    return None, None


_GENUS_FALLBACK_TOKENS = (
    "seksjon", "seksjoner", "avdeling", "gruppe", "gruppen",
    "spp", "spp.", "m.fl", "m.fl.", "agg",
)


def _strip_taxon_suffix(latin):
    """Fjern 'seksjon X', 'spp.', 'm.fl.' osv. fra et gruppe-/artsnavn."""
    parts = [p for p in re.split(r"\s+", latin.strip()) if p]
    tail = parts[0] if parts else ""
    return tail.replace(",", "")


GBIF_BACKBONE_DATASET = "d7dddbf4-2cf0-4f39-9b2a-bb099caae36c"
ARTSSOBS_DATASET_KEY = "b124e1e0-4755-430f-9eab-894f25a9b59c"  # Norwegian Species Observation Service


def _match_genus_backbone_key(genus):
    """Bare slektsnavn -> godtatt genus-key fra GBIF-backbone.

    species/match gir ofte matchType NONE for soppslekter ("multiple equal
    matches", f.eks. Scleroderma/Flammulina), så vi sjekker backbone direkte.
    """
    if not genus:
        return None
    try:
        r = _gbif_session.get(
            f"{GBIF_BASE}/species/search",
            params={
                "q": genus,
                "datasetKey": GBIF_BACKBONE_DATASET,
                "rank": "GENUS",
                "limit": 5,
            },
            timeout=30,
        )
        r.raise_for_status()
        for tax in r.json().get("results", []) or []:
            sci = ((tax.get("scientificName") or "").split(",")[0].strip()
                   .split()[0] if tax.get("scientificName") else "")
            if sci.lower() != genus.lower():
                continue
            if tax.get("taxonomicStatus") == "ACCEPTED":
                return tax.get("key")
    except Exception as exc:  # noqa: BLE001
        log.warning("GBIF species/search (genus) %r mislyktes: %s", genus, exc)
    return None


def resolve_taxon_key(latin):
    """Familie/Gruppe/Alias-latinsknavn -> godtatt usageKey, med genus-fallback."""
    if not latin:
        return None
    uk, _ = _match_taxon_key(latin)
    if uk:
        return uk
    genus = _strip_taxon_suffix(latin)
    if genus and genus.lower()[0] != latin.strip().lower()[0]:
        return None
    uk2, _ = _match_taxon_key(genus)
    if uk2:
        return uk2
    uk3 = _match_genus_backbone_key(genus)
    return uk3


# --- bildehenting ------------------------------------------------------------

# Kun Creative Commons-lisensierte bilder brukes. GBIF leverer lisensen både som
# kortkode (CC0_1_0, CC_BY_4_0, CC_BY_SA_4_0, CC_BY_NC_4_0 …) og som full URL
# (http://creativecommons.org/licenses/by-nc/4.0/legalcode).
def _is_cc_license(lic):
    """True hvis en GBIF-lisenskode er en Creative Commons-lisens."""
    lic = (lic or "").strip()
    if not lic:
        return False
    if "creativecommons" in lic.lower():
        return True
    code = lic.upper().replace("-", "_")
    return code == "CC" or code.startswith("CC0") or code.startswith("CC_BY")


def _is_artsobs_image(url):
    """True hvis bildet kommer fra artsobservasjoner.no."""
    return "artsobservasjoner" in (url or "").lower()


def _license_label(lic):
    """Kort, lesbar etikett for en GBIF-lisens (kortkode eller full URL)."""
    lic = (lic or "").strip()
    if not lic:
        return ""
    low = lic.lower()
    if "creativecommons.org" in low:
        m = re.search(r"/(?:licenses|publicdomain)/([a-z0-9\-]+)/([0-9.]+)", low)
        if m:
            code, ver = m.group(1), m.group(2).rstrip(".")
            if code == "zero":
                return f"CC0 {ver}"
            return "CC " + code.upper() + " " + ver
        return "Creative Commons"
    code = low.upper().replace("-", "_")
    if code.startswith("CC0"):
        ver = code[3:].lstrip("_").replace("_", ".")
        return ("CC0 " + ver).strip()
    if code.startswith("CC_"):
        tokens = code[3:].split("_")
        elems = [t for t in tokens if t.isalpha()]
        ver = ".".join(t for t in tokens if t.isdigit())
        return ("CC " + "-".join(elems) + (" " + ver if ver else "")).strip()
    return lic


def _owner_for(occ, med):
    """Fotograf/rettighetshaver for et medie, med fornuftige fallback."""
    for cand in (med.get("rightsHolder"), med.get("creator"),
                 occ.get("rightsHolder"), occ.get("recordedBy")):
        if cand and str(cand).strip():
            return str(cand).strip()
    return ""


def _images_for(usage_key):
    """Bilder for en usageKey, som dikter med url/fotograf/lisens.

    Prefererer Artsobservasjoner; hvis den kilden ikke har noen CC-bilder for
    arten faller vi tilbake til andre CC-lisensierte GBIF-medier.
    """
    def collect(dataset_key, require_artsobs):
        params = {"taxonKey": usage_key, "mediaType": "StillImage", "limit": 300}
        if dataset_key:
            # Artsobservasjoner-bildene er i GBIF-datasettet "Norwegian Species
            # Observation Service". Direkte datasett-søk gir mye bedre utbytte
            # enn å filtrere bort i etterkant fra et generisk takson-søk.
            params["datasetKey"] = dataset_key
        out = []
        try:
            r = _gbif_session.get(
                f"{GBIF_BASE}/occurrence/search",
                params=params,
                timeout=30,
            )
            r.raise_for_status()
            for occ in r.json().get("results", []) or []:
                occ_license = occ.get("license") or ""
                for med in occ.get("media", []) or []:
                    if med.get("type") != "StillImage":
                        continue
                    lic = med.get("license") or occ_license
                    if not _is_cc_license(lic):
                        continue
                    ident = (med.get("identifier") or "").strip()
                    if not ident:
                        continue
                    is_artsobs = _is_artsobs_image(ident)
                    if require_artsobs and not is_artsobs:
                        continue
                    out.append({
                        "url": ident,
                        "owner": _owner_for(occ, med),
                        "license": _license_label(lic),
                        "license_url": lic if lic.lower().startswith("http") else "",
                        "source": "artsobs" if is_artsobs else "other",
                    })
        except Exception as exc:  # noqa: BLE001
            log.warning("GBIF occurrence/search uk=%s mislyktes: %s", usage_key, exc)
        return out

    if IMAGE_SOURCE == "all":
        images = collect(None, False)
    else:
        images = collect(ARTSSOBS_DATASET_KEY, True)
        if not images:
            # Fallback: Artsobservasjoner mangler bilder for denne arten, så vi
            # bruker andre CC-lisensierte kilder (iNaturalist m.fl.).
            images = collect(None, False)

    seen = set()
    unique = []
    for img in images:
        if img["url"] in seen:
            continue
        seen.add(img["url"])
        unique.append(img)
    unique.sort(key=lambda i: 0 if i["source"] == "artsobs" else 1)
    return unique


# --- disk-cache for takson- og bilderesultater -------------------------------

_CACHE_LOCK = threading.Lock()
_cached_offline = set()


def _load_disk_cache():
    try:
        with open(DISK_CACHE_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_disk_cache(cache):
    tmp = DISK_CACHE_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, ensure_ascii=False)
        os.replace(tmp, DISK_CACHE_PATH)
    except OSError as exc:
        log.warning("kunne ikke skrive %s: %s", DISK_CACHE_PATH, exc)


def _normalize_cached(entry):
    """Cachet oppslag -> liste av bildedikter, eller None hvis ingenting cachet.

    Eldre cache skrev bare URL-strenger under nøkkelen "urls".
    """
    imgs = entry.get("images")
    if imgs is None:
        urls = entry.get("urls")
        if urls is None:
            return None
        imgs = [
            {"url": u, "owner": "", "license": "", "license_url": "",
             "source": "artsobs" if _is_artsobs_image(u) else "other"}
            for u in urls
        ]
    return imgs


def fetch_images(species, latin=None):
    """Return (images, error_text_or_None). Disk-cachet per art i ett døgn."""
    latin = (latin or _latin_for(species) or "").strip()
    now = time.time()
    key = species.lower()

    with _CACHE_LOCK:
        cache = _load_disk_cache()
        entry = cache.get(key) or {}

        # Gyldig disk-cache? Tomme treff caches ikke som gyldige, slik at nye
        # kilder/fallback kan prøves på nytt.
        ts = entry.get("ts") or 0
        imgs = _normalize_cached(entry)
        if now - ts < IMAGE_CACHE_TTL and imgs:
            return [dict(i) for i in imgs], None
        if key in _cached_offline:
            return [], "nettverksfeil (cached offline). Trykk R for nytt forsøk"

    # Unn deg litt fart: bruk nett i bakgrunnen én gang, deretter cache.
    uk = resolve_taxon_key(latin) if latin else None
    if not uk:
        with _CACHE_LOCK:
            cache = _load_disk_cache()
            cache[key] = {"ts": now, "images": []}
            _save_disk_cache(cache)
            _cached_offline.add(key)
        return [], f"fant ikke GBIF-takson for '{species}'"

    images = _images_for(uk)

    with _CACHE_LOCK:
        cache = _load_disk_cache()
        cache[key] = {"ts": now, "images": images, "uk": uk}
        # Synkroniser nedskriving (kun én skriving av gangen)
        _save_disk_cache(cache)
        if not images:
            _cached_offline.add(key)

    if not images:
        return [], f"ingen bilder i GBIF for '{species}'"
    return images, None


# Pensum data
# ---------------------------------------------------------------------------

def load_pensum():
    try:
        with open(PENSUM_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        log.error("Kunne ikke lese %s: %s", PENSUM_PATH, exc)
        return []

    if isinstance(data, dict):
        for key in ("art", "sopper", "arter", "pensum"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = []

    pensum = []
    seen = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        name = (item.get("norsknavn") or "").strip()
        if not name:
            continue
        code = _code_for(item.get("normstatus") or "") or _code_for(item.get("normstatus_kode") or "")
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        _LATIN_BY_NAME[name] = (item.get("latinsknavn") or "").strip()
        pensum.append({
            "name": name,
            "code": code,
            "full": STATUS.get(code) if code else (item.get("normstatus") or "").strip(),
            "comment": (item.get("kommentar") or "").strip(),
        })
    return pensum


PENSUM = load_pensum()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/", methods=["GET"])
@app.route("/guess", methods=["GET"])
def quiz():
    if not PENSUM:
        return (
            "<h1>Pensum soppquiz</h1>"
            "<p>Fant ikke &quot;pensum.json&quot; eller filen er tom. "
            "Legg den i samme mappe som app.py og last siden på nytt.</p>"
        )

    # Avoid showing the same species too soon after it was shown.
    repeat_window = min(5, max(1, len(PENSUM) // 2))
    candidates = [a for a in PENSUM if a["name"] not in _recent] or PENSUM
    art = random.choice(candidates)
    _recent.append(art["name"])
    del _recent[:-repeat_window]

    images, error = fetch_images(art["name"])
    random.shuffle(images)
    images = images[:IMAGES_PER_QUESTION]

    names = sorted({a["name"] for a in PENSUM}, key=str.lower)
    answer = {
        "name": art["name"],
        "status": art["code"],
        "full": art["full"] or STATUS.get(art["code"]),
        "comment": art["comment"],
    }

    html = PAGE_TEMPLATE
    html = html.replace("__PENSUM__", json.dumps(names, ensure_ascii=False))
    html = html.replace("__ANSWER__", json.dumps(answer, ensure_ascii=False))
    html = html.replace("__GRID__", _images_grid(images, error))
    html = html.replace("__SOURCE_TEXT__", _source_footer_text())
    return html


def _source_footer_text():
    """Tekst i footeren som beskriver bildekildene ut fra IMAGE_SOURCE."""
    if IMAGE_SOURCE == "artsobs":
        return ('<a href="https://artsobservasjoner.no" target="_blank" rel="noopener">'
                "Artsobservasjoner.no</a> (kun Creative Commons-lisensiert, "
                "med andre CC-kilder der Artsobservasjoner mangler)")
    return ("GBIF-bilder fra <a href=\"https://artsobservasjoner.no\" "
            "target=\"_blank\" rel=\"noopener\">Artsobservasjoner.no</a>, "
            "iNaturalist m.fl. (kun Creative Commons-lisensiert)")


@app.route("/search")
def search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return "Bruk ?q=&lt;navn&gt;", 400
    images, error = fetch_images(q)
    grid = _images_grid(images, error)
    body = f"<h1>{escape(q)}</h1>" + grid + '<p><a href="/">Gå tilbake til quizzen</a></p>'
    return _wrap_page(body)


@app.route("/healthz")
def healthz():
    return jsonify({"pensum": len(PENSUM)})


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def _images_grid(images, error):
    if not images:
        msg = "Kunne ikke hente bilder fra GBIF (%s). Trykk R for et nytt spørsmål."
        return f'<div class="placeholder" id="noimages">{msg % escape(str(error))}</div>'
    cells = []
    for img in images:
        url = img.get("url") or ""
        owner = img.get("owner") or ""
        license_label = img.get("license") or ""
        tip = "Foto: " + owner if owner else "Bilde"
        if license_label:
            tip += " (" + license_label + ")"
        cells.append(
            '<a class="cell" href="%s" target="_blank" rel="noopener">'
            '<img src="%s" alt="" loading="eager">'
            '<span class="cc" title="%s">CC</span>'
            "</a>" % (escape(url), escape(url), escape(tip))
        )
    return '<div class="grid">%s</div>' % "".join(cells)


def _wrap_page(body):
    return (
        "<!doctype html><html lang=\"no\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        "<title>Pensum soppquiz</title></head><body "
        f'style="font-family:system-ui,sans-serif;padding:20px;">{body}'
        '<footer style="margin-top:30px;font-size:12px;color:#8a745f;">'
        'Contact: Donn Morrison <a href="mailto:donn@tuta.io">donn@tuta.io</a>'
        "</footer></body></html>"
    )


# ---------------------------------------------------------------------------
# The quiz page (static shell; __PLACEHOLDERS__ get swapped in at runtime)
# ---------------------------------------------------------------------------

PAGE_TEMPLATE = """<!doctype html>
<html lang="no">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pensum soppquiz</title>
<style>
  :root{
    --bg:#f5efe3; --card:#fffdf7; --ink:#2c1e12; --muted:#8a745f;
    --accent:#6d4a2f; --line:#e6d9c4;
    --ok:#2e7d32; --ko:#c62828;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
       font:16px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;}
  .wrap{max-width:960px;margin:0 auto;padding:18px 16px 60px;}
  header{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:6px;}
  h1{font-size:26px;margin:0;}
  .score{margin-left:auto;font-size:13px;color:var(--muted);white-space:nowrap;}
  .score b{color:var(--ink);}
  .hintbar{color:var(--muted);font-size:13px;border-bottom:1px solid var(--line);
           padding-bottom:10px;margin-bottom:16px;}
  kbd{display:inline-block;min-width:16px;text-align:center;padding:0 5px;border-radius:5px;
      background:#efe4d0;border:1px solid #d9c5a3;border-bottom-width:2px;font:inherit;font-size:12px;}
  .panel{background:var(--card);border:1px solid var(--line);border-radius:14px;
         padding:20px;box-shadow:0 10px 30px rgba(80,55,20,.06);}
  .question{font-size:18px;font-weight:600;margin:0 0 14px;}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;}
  .cell{position:relative;display:block;border-radius:10px;overflow:hidden;border:1px solid var(--line);
        background:#efe7d8;aspect-ratio:1/1;}
  .cell img{width:100%;height:100%;object-fit:cover;display:block;transition:transform .12s ease;}
  .cell:hover img{transform:scale(1.03);}
  .cc{position:absolute;right:6px;bottom:6px;padding:2px 6px;border-radius:6px;
      background:rgba(0,0,0,.62);color:#fff;font-size:11px;font-weight:700;line-height:1.2;
      letter-spacing:.02em;cursor:help;user-select:none;}
  .placeholder{border:1px dashed var(--line);border-radius:10px;padding:26px;color:var(--ko);
               background:#fdf3ee;}
  .inputs{display:grid;grid-template-columns:2fr 1fr;gap:10px;margin-top:4px;}
  @media (max-width:560px){.inputs{grid-template-columns:1fr;}}
  .field label{font-size:13px;color:var(--muted);display:block;margin-bottom:4px;}
  input[type="text"]{width:100%;padding:10px 12px;border:1.5px solid var(--line);border-radius:10px;
                     font:inherit;color:inherit;background:#fff;}
  input[type="text"]:focus{outline:2px solid var(--accent);border-color:var(--accent);}
  .autocomplete{position:relative;}
  #suggest{position:absolute;left:0;right:0;top:calc(100% + 4px);margin:0;padding:4px;list-style:none;
           background:#fff;border:1px solid var(--line);border-radius:10px;box-shadow:0 12px 30px
           rgba(60,35,10,.14);z-index:20;max-height:264px;overflow:auto;}
  #suggest li{padding:8px 10px;border-radius:7px;cursor:pointer;}
  #suggest li.sel{background:var(--accent);color:#fff;}
  #suggest li.empty{color:var(--muted);cursor:default;}
  .actions{display:flex;align-items:center;gap:12px;margin-top:16px;flex-wrap:wrap;}
  button.primary{font:inherit;font-weight:700;padding:10px 18px;border:0;border-radius:10px;
                 background:var(--accent);color:#fff;cursor:pointer;}
  button.primary:disabled{background:#cbb9a0;cursor:default;}
  button.primary:hover:not(:disabled){filter:brightness(1.08);}
  .shortcut{color:var(--muted);font-size:12px;}
  .feedback{margin-top:16px;border-radius:12px;padding:16px 18px;border:1px solid var(--line);
            background:var(--card);}
  .feedback .line{margin:6px 0;}
  .ok{color:var(--ok);font-weight:600;}
  .ko{color:var(--ko);font-weight:600;}
  .feedback .answer{font-size:17px;font-weight:700;margin:10px 0 4px;}
  .feedback .comment{color:var(--muted);}
  .feedback .next{margin-top:12px;color:var(--muted);}
  footer{color:var(--muted);font-size:12px;margin-top:18px;text-align:center;}
  .hidden{display:none;}
  .legend{cursor:help; color:#8a8f98; font-weight:bold; padding-left:4px; user-select:none;}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Pensum soppquiz</h1>
    <div class="score" id="score"></div>
  </header>

  <div class="hintbar">
    <kbd>&darr;</kbd>/<kbd>&uarr;</kbd> bla i forslag &middot; normstatus skrives som
    <kbd title="s = spiselig">s</kbd>/<kbd title="smm = spiselig med merknad">smm</kbd>/<kbd title="im = ikke matsopp">im</kbd>/<kbd title="g = giftig">g</kbd>/<kbd title="mg = meget giftig">mg</kbd> &middot;
    <kbd>Enter</kbd> svar / neste &middot; <kbd>Esc</kbd> lukk &middot; <kbd>R</kbd> nytt sp&oslash;rsm&aring;l
  </div>

  <main class="panel">
    <p class="question">Hvilken sopp er dette, og hvilken normstatus har den?</p>
    __GRID__

    <div class="inputs">
      <div class="field">
        <label for="name">Art (skriv &amp; velg fra listen)</label>
        <div class="autocomplete">
          <input type="text" id="name" autocomplete="off" spellcheck="false"
                 placeholder="Skriv norsk navn&hellip;" aria-autocomplete="list">
          <ul id="suggest" class="hidden"></ul>
        </div>
      </div>
      <div class="field">
        <label for="code">Normstatus
          <span class="legend" tabindex="0" role="button" aria-label="Vis normstatus-forkortelser"
                title="s = spiselig&#10;smm = spiselig med merknad&#10;im = ikke matsopp&#10;g = giftig&#10;mg = meget giftig">?</span>
        </label>
        <input type="text" id="code" autocomplete="off" spellcheck="false" maxlength="3"
               placeholder="s/smm/im/g/mg" title="s = spiselig, smm = spiselig med merknad, im = ikke matsopp, g = giftig, mg = meget giftig">
      </div>
    </div>

    <div class="actions">
      <button class="primary" id="submit" disabled>Svar p&aring; quizzen</button>
      <span class="shortcut" id="submithint">fyll ut art + status &rarr; <kbd>Enter</kbd></span>
    </div>
  </main>

  <div id="feedback" class="hidden"></div>
  <footer>Bilder fra __SOURCE_TEXT__ &middot; Contact: Donn Morrison <a href="mailto:donn@tuta.io">donn@tuta.io</a></footer>
</div>

<script>
(function(){
  "use strict";
  var NAMES = __PENSUM__;      // all species names, for the autocomplete
  var ANSWER = __ANSWER__;     // {name, status, full, comment} of this question
  var CODES = ["s", "smm", "im", "g", "mg"];
  var MAX_SUG = 8;

  var nameInput = document.getElementById("name");
  var codeInput = document.getElementById("code");
  var suggest  = document.getElementById("suggest");
  var submitBtn = document.getElementById("submit");
  var submitHint = document.getElementById("submithint");
  var feedbackBox = document.getElementById("feedback");
  var scoreBox = document.getElementById("score");

  var status = null;               // selected code, or null
  var selIdx = 0, current = [];
  var listOpen = false, answered = false;
  var noImages = !!document.getElementById("noimages");

  function norm(s){ return String(s || "").trim().toLowerCase(); }
  function esc(s){ return String(s).replace(/[&<>"']/g, function(c){
      return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];
  }); }

  /* ---------- score (persisted in localStorage) ---------- */
  function loadScore(){
    try { var s = JSON.parse(localStorage.getItem("soppquiz_score")); return s || {a:0,b:0,n:0}; }
    catch (e) { return {a:0,b:0,n:0}; }
  }
  function saveScore(s){ try { localStorage.setItem("soppquiz_score", JSON.stringify(s)); } catch(e){} }
  function renderScore(){
    var s = loadScore();
    scoreBox.innerHTML = "Art riktig: <b>" + s.a + "</b>/" + s.n +
      " &middot; begge riktig: <b>" + s.b + "</b>" +
      (s.n ? ' &middot; <a href="#" id="resetscore">nullstill</a>' : "");
    var rs = document.getElementById("resetscore");
    if (rs){ rs.addEventListener("click", function(e){ e.preventDefault(); saveScore({a:0,b:0,n:0}); renderScore(); }); }
  }

  /* ---------- status: typed code s/smm/im/g/mg ---------- */
  // Resolve a status from the typed text. The input is never rewritten, so
  // typing character-by-character always matches what the user typed.
  function statusFromCodeText(t){
    if (CODES.indexOf(t) !== -1) return t;
    var pref = [];
    CODES.forEach(function(c){ if (c.indexOf(t) === 0) pref.push(c); });
    return pref.length === 1 ? pref[0] : null;
  }

  codeInput.addEventListener("input", function(){
    status = statusFromCodeText(norm(codeInput.value));
    syncSubmit();
  });

  codeInput.addEventListener("keydown", function(e){
    if (e.key === "Enter"){ e.preventDefault(); e.stopPropagation(); submit(); }
  });

  /* ---------- name autocomplete ---------- */
  function matches(q){
    q = norm(q);
    if (!q) return [];
    var prefix = [], rest = [];
    NAMES.forEach(function(n){
      var l = norm(n);
      if (l.indexOf(q) === 0) prefix.push(n);
      else if (l.indexOf(q) > -1) rest.push(n);
    });
    return prefix.concat(rest).slice(0, MAX_SUG);
  }

  function openList(items){
    current = items; listOpen = items.length > 0;
    suggest.innerHTML = "";
    if (!items.length){
      var empty = document.createElement("li");
      empty.className = "empty";
      empty.textContent = "Ingen arter funnet";
      suggest.appendChild(empty);
    } else {
      items.forEach(function(nm, i){
        var li = document.createElement("li");
        li.textContent = nm;
        li.addEventListener("mousemove", function(){ setIdx(i); });
        li.addEventListener("click", function(){ choose(i); });
        suggest.appendChild(li);
      });
    }
    suggest.classList.remove("hidden");
    setIdx(0);
  }

  function setIdx(i){
    if (!current.length) return;
    selIdx = Math.max(0, Math.min(i, current.length - 1));
    var lis = suggest.children;
    for (var j = 0; j < lis.length; j++) lis[j].classList.toggle("sel", j === selIdx);
    var el = lis[selIdx];
    if (el && el.scrollIntoView) el.scrollIntoView({block:"nearest"});
  }

  function closeList(){
    listOpen = false;
    suggest.classList.add("hidden");
  }

  function choose(i){
    if (!current.length) return;
    nameInput.value = current[i];
    closeList();
    syncSubmit();
    codeInput.focus();
    codeInput.select();
  }

  nameInput.addEventListener("input", function(){
    openList(matches(nameInput.value));
    syncSubmit();
  });

  nameInput.addEventListener("keydown", function(e){
    if (e.key === "ArrowDown"){ if (listOpen && current.length){ e.preventDefault(); setIdx(selIdx + 1); } }
    else if (e.key === "ArrowUp"){ if (listOpen && current.length){ e.preventDefault(); setIdx(selIdx - 1); } }
    else if (e.key === "Escape"){ closeList(); }
    else if (e.key === "Enter"){
      e.preventDefault();
      if (listOpen && current.length) choose(selIdx);
      else codeInput.focus();
    }
    else if (e.key === "Tab"){
      if (listOpen && current.length){ e.preventDefault(); choose(selIdx); }
    }
  });

  nameInput.addEventListener("blur", function(){ setTimeout(closeList, 140); });

  /* ---------- submit & feedback ---------- */
  function syncSubmit(){
    var ready = norm(nameInput.value) !== "" && status !== null;
    submitBtn.disabled = !ready;
    if (!ready){
      if (!norm(nameInput.value)) submitHint.innerHTML = "skriv arten &rarr; <kbd>Enter</kbd>";
      else submitHint.innerHTML = "skriv status (s/smm/im/g/mg) &rarr; <kbd>Enter</kbd>";
    } else {
      submitHint.innerHTML = "trykk <kbd>Enter</kbd> for &aring; svare";
    }
  }

  function submit(){
    if (answered){ next(); return; }
    if (noImages) return;
    var typed = norm(nameInput.value);
    if (!typed){ nameInput.focus(); return; }
    if (status === null){ codeInput.focus(); return; }

    var artOK = typed === norm(ANSWER.name);
    var statOK = status === ANSWER.status;
    answered = true;
    record(artOK, statOK);
    feedbackBox.innerHTML =
      (artOK
        ? '<div class="line ok">Art: riktig</div>'
        : '<div class="line ko">Art: feil</div>') +
      (statOK
        ? '<div class="line ok">Normstatus: riktig</div>'
        : '<div class="line ko">Normstatus: feil &mdash; riktig er '
          + esc(ANSWER.full || ANSWER.status) + "</div>") +
      '<div class="answer">' + esc(ANSWER.name) +
        (ANSWER.status ? " &middot; " + esc(ANSWER.status) : "") + "</div>" +
      (artOK && statOK
        ? '<div class="line ok">Alt riktig!</div>'
        : "") +
      (ANSWER.comment
        ? '<div class="comment">' + esc(ANSWER.comment) + "</div>"
        : "") +
      '<div class="next">Trykk <kbd>Enter</kbd> for neste sp&oslash;rsm&aring;l.</div>';
    feedbackBox.classList.remove("hidden");
    feedbackBox.scrollIntoView({block:"nearest"});
  }

  function record(artOK, statOK){
    var s = loadScore();
    s.n++; if (artOK) s.a++; if (artOK && statOK) s.b++;
    saveScore(s); renderScore();
  }

  function next(){ window.location.href = "/"; }

  /* ---------- global keys ---------- */
  document.addEventListener("keydown", function(e){
    var tag = e.target && e.target.tagName;

    if (answered){
      if (e.key === "Enter"){ e.preventDefault(); next(); }
      return;
    }
    if ((e.key === "R" || e.key === "r") && tag !== "INPUT"){
      window.location.href = "/";
      return;
    }
    if (e.key === "Enter"){
      if (tag === "INPUT") return;
      e.preventDefault();
      submit();
    }
  });

  submitBtn.addEventListener("click", submit);

  /* ---------- init ---------- */
  renderScore();
  if (noImages){
    var cont = document.querySelector(".inputs");
    if (cont) cont.classList.add("hidden");
    var act = document.querySelector(".actions");
    if (act) act.classList.add("hidden");
  } else {
    syncSubmit();
    nameInput.focus();
  }
})();
</script>
</body>
</html>
"""


# Optional: mount the archived "old" quiz at /old/ inside the same process,
# so no reverse-proxy path rewriting is needed. Enabled with SERVE_OLD=1
# (expects an `old_app.py` module with its own Flask `app` in /app).
if os.environ.get("SERVE_OLD") == "1":
    from werkzeug.middleware.dispatcher import DispatcherMiddleware
    import old_app

    application = DispatcherMiddleware(app, {"/old": old_app.app})
    log.info("Archived quiz mounted at /old/ via DispatcherMiddleware")


if __name__ == "__main__":
    from werkzeug.serving import run_simple

    port = int(os.environ.get("PORT", "5000"))
    target = application if os.environ.get("SERVE_OLD") == "1" else app
    run_simple("0.0.0.0", port, target, threaded=True, use_reloader=False)