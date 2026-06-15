# eCourtsIndia API integration

A clean, authenticated alternative data source for the Maharashtra Courts app,
backed by the [eCourtsIndia Partner API](https://ecourtsindia.com/api/docs).

Where the rest of the app scrapes the district-court portal via
[`bharat-courts`](https://github.com/iamshouvikmitra/bharat-courts) (solving a
CAPTCHA per request, Maharashtra-only), this path hits a REST API: a Bearer
token in, JSON out, national coverage, no CAPTCHA. It powers the **eCourts API**
tab in the UI and can act as a faster, broader competitor to the scraping path.

## Layout

| File | Purpose |
|------|---------|
| `client.py` | `EcourtsIndiaClient` — synchronous wrapper over the REST API (depends only on `requests`). |
| `routes.py` | `eci_bp` Flask blueprint mounted at `/api/eci/*` by `server.py`. |
| `__init__.py` | Re-exports `EcourtsIndiaClient`, `EcourtsIndiaError`, `eci_bp`. |

## Configuration

Set the API key in the environment (`.env` locally, env vars on Render):

```
ECOURTS_API_KEY=eci_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# optional, defaults to https://webapi.ecourtsindia.com
ECOURTS_API_BASE_URL=
```

When the key is missing, every authenticated route returns a clean
`401 MISSING_API_KEY` and the UI shows a "configure your key" banner — nothing
crashes. The key is read once at startup, so restart after changing it.

## HTTP routes (`/api/eci`)

| Method & path | Backed by | Notes |
|---------------|-----------|-------|
| `GET /status` | — | Reports whether the key is configured (no upstream call). |
| `GET /case/<cnr>` | `get_case` | Full case record by 16-char CNR. |
| `POST /case/<cnr>/refresh` | `refresh_case` | Queue a fresh scrape (~5–10s). |
| `POST /case/bulk-refresh` | `bulk_refresh` | Body: JSON array of 2–50 CNRs, or `{"cnrs":[...]}`. |
| `GET /search` | `search` | Text + faceted case search. `query`, `advocates`, `litigants`, `page`, `pageSize` (≤100). |
| `GET /causelist/search` | `causelist_search` | `q`, `date`, `listType` (CIVIL/CRIMINAL), offset-based paging. |
| `GET /causelist/available-dates` | `causelist_available_dates` | Dates with cause-list data for a scope. |
| `GET /enums` | `get_enums` | Live enum reference (free). |
| `GET /structure/...` | `states`/`districts`/`complexes`/`courts` | Court hierarchy (free). |

## Using the client directly

```python
from Ecourtindia import EcourtsIndiaClient, EcourtsIndiaError

client = EcourtsIndiaClient()           # reads ECOURTS_API_KEY from env
try:
    case = client.get_case("MHAU010012342024")
    hits = client.search(advocates="Joshi", page_size=50)
    today = client.causelist_search(advocate="Joshi", list_type="CIVIL")
except EcourtsIndiaError as e:
    print(e.code, e.status, e.message)
```

Every method returns the already-unwrapped `data` payload from the API's
`{"data": ..., "meta": ...}` envelope. Errors raise `EcourtsIndiaError`
carrying the upstream `code`, HTTP `status`, `details`, and `request_id`.

## Refresh workflow

1. `POST /api/eci/case/<cnr>/refresh` → status `QUEUED`.
2. Wait ~10s (≥30s for `bulk-refresh`).
3. `GET /api/eci/case/<cnr>` for the updated record.

## Key conventions (from the API guide)

- **CNR**: 16 chars, `[A-Z]{4}\d{12}`.
- High-court codes need a bench suffix (e.g. `DLHC01`); NCLT codes need a trailing `0` (e.g. `NCLTDL0`).
- Enum codes (`courtCode`, `caseType`, …) are *search filters only*; case categories in responses are free-form court text.
- Party arrays are plain strings, not objects.
- Implement exponential backoff on `429 RATE_LIMIT_EXCEEDED`.
