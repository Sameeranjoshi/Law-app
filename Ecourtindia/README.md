# eCourtsIndia API integration

A clean, authenticated alternative data source for the Maharashtra Courts app,
backed by the [eCourtsIndia Partner API](https://ecourtsindia.com/api/docs)
([developer guide](https://blogs.ecourtsindia.com/2026/05/18/how-to-use-ecourtsindia-api/)).

Where the rest of the app scrapes the district-court portal via
[`bharat-courts`](https://github.com/iamshouvikmitra/bharat-courts) (CAPTCHA per
request, Maharashtra-only), this path hits a REST API: Bearer token in, JSON
out, **national coverage, no CAPTCHA**. It powers the self-contained **eCourts
API** tab in the UI (with a sub-tab per feature) and acts as a faster, broader
competitor to the scraping path. It is fully additive — the original routes and
tabs are untouched.

## Layout

| File | Purpose |
|------|---------|
| `client.py` | `EcourtsIndiaClient` — synchronous wrapper over the REST API (depends only on `requests`). Paths/params verified against the live API. |
| `routes.py` | `eci_bp` Flask blueprint mounted at `/api/eci/*` by `server.py`. |
| `secret.py` | API-key resolution (env var → embedded obfuscated key). |
| `__init__.py` | Re-exports `EcourtsIndiaClient`, `EcourtsIndiaError`, `eci_bp`, `get_api_key`. |

## Configuration / the API key

The key is resolved by `secret.get_api_key()`:

1. **`ECOURTS_API_KEY`** env var (preferred — set it in `.env` locally or as a
   Render env var; it always wins).
2. An **embedded, XOR-obfuscated key** baked into `secret.py`, so the app runs
   out-of-the-box on a fresh Render deploy with no manual setup.

> ⚠️ The embedded key is obfuscated, **not** truly secret — the passphrase is in
> `secret.py`, so anyone with the repo can reverse it. It only keeps the raw
> token from being plainly greppable and lets the app self-configure. For real
> protection, set `ECOURTS_API_KEY` as a Render secret and rotate the key.
> To regenerate the blob after a rotation: `python -c "from Ecourtindia.secret import obfuscate; print(obfuscate('eci_live_...'))"`.

When no key resolves, authenticated routes return a clean `401 MISSING_API_KEY`
and the UI shows a "configure your key" banner — nothing crashes. The key is
read once at startup, so restart after changing it.

## HTTP routes (`/api/eci`)

| Method & path | Backed by | Notes |
|---------------|-----------|-------|
| `GET /status` | — | `configured`, `key_source` (env/embedded), `base_url`. No upstream call. |
| `GET /case/<cnr>` | `get_case` | Full case record by 16-char CNR. |
| `POST /case/<cnr>/refresh` | `refresh_case` | Queue an async re-scrape. |
| `POST /case/bulk-refresh` | `bulk_refresh` | Body `{"cnrs":[...]}` (2–50). Returns refreshed/queued/invalid. |
| `GET /case/<cnr>/order/<file>` | `order_pdf` | Streams the signed PDF (`inline`). |
| `GET /case/<cnr>/order-md/<file>` | `order_md` | OCR-cleaned markdown + `pdfBase64`. |
| `GET /case/<cnr>/order-ai/<file>` | `order_ai` | Markdown + structured AI analysis. |
| `GET /search` | `search` | Accepts PascalCase **or** lower-cased keys (`Query`, `Advocates`, `Litigants`, `CourtCodes`, `CaseTypes`, `StateCodes`, `FilingYears`, `Page`, `PageSize`≤100, …). |
| `GET /causelist/search` | `causelist_search` | `q`, `advocate`, `judge`, `state`, `districtCode`, `date`, `listType` (CIVIL/CRIMINAL), `limit`, `offset`. Window ~1 day back → 7 forward. |
| `GET /causelist/available-dates` | `causelist_available_dates` | Dates (newest first) for a scope. |
| `GET /enums` | `get_enums` | Live enum reference (free). `?types=caseType,...` |
| `GET /structure/states` | `states` | Free. Court hierarchy (fully nested). |
| `GET /structure/states/<state>/districts` | `districts` | |
| `GET /structure/states/<state>/districts/<dc>/complexes` | `complexes` | |
| `GET /structure/states/<state>/districts/<dc>/complexes/<cc>/courts` | `courts` | |

## Using the client directly

```python
from Ecourtindia import EcourtsIndiaClient, EcourtsIndiaError

client = EcourtsIndiaClient()                 # resolves key via secret.get_api_key()
try:
    case  = client.get_case("HBHC010537062008")
    hits  = client.search(Advocates="Joshi", StateCodes="MH", PageSize=50)
    today = client.causelist_search(advocate="Joshi", state="MH")
    md    = client.order_md("BRPU010070382025", "order-1.pdf")
    comps = client.complexes("MH", "26")
except EcourtsIndiaError as e:
    print(e.code, e.status, e.message)
```

Every JSON method returns the already-unwrapped `data` payload; court-structure
endpoints return a bare list. Errors raise `EcourtsIndiaError` carrying the
upstream `code`, HTTP `status`, `details`, and `request_id`.

## Refresh workflow

1. `POST /api/eci/case/<cnr>/refresh` (or `bulk-refresh`) → queued immediately.
2. Wait ~10–30s (≥30s for bulk).
3. `GET /api/eci/case/<cnr>` for the updated record (poll `entityInfo.dateModified`).

## Key conventions (from the API guide)

- **CNR**: 16 chars, `[A-Z]{4}\d{12}`.
- High-court codes need a bench suffix (e.g. `DLHC01`); NCLT codes a trailing `0` (`NCLTDL0`).
- Enum codes (`courtCode`, `caseType`, …) are *search filters only*; response `caseCategory` is free-form text.
- Party arrays are plain strings; advocates are parallel arrays (`petitioners` / `petitionerAdvocates`).
- Order filenames come from `judgmentOrders[].orderUrl` — use the bare name (e.g. `order-1.pdf`).
- Search paginates max 100/page; loop until `hasNextPage` is false. Back off on `429`.
