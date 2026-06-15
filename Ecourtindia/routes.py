"""
Flask blueprint exposing the eCourtsIndia Partner API to the frontend.

Mounted under /api/eci/* by server.py. Each route is a thin pass-through to
EcourtsIndiaClient, translating EcourtsIndiaError into a clean JSON error
with the upstream HTTP status preserved.

This is the "competitor" data path: same UI, but backed by the eCourtsIndia
REST API (no CAPTCHA, national coverage) instead of the bharat-courts
district-court scraper.
"""

from flask import Blueprint, jsonify, request

from .client import EcourtsIndiaClient, EcourtsIndiaError

eci_bp = Blueprint("eci", __name__, url_prefix="/api/eci")

# One shared client; reads ECOURTS_API_KEY from the environment on each
# attribute access via the constructor default, so a key added after boot
# still requires a restart — fine for this deployment model.
_client = EcourtsIndiaClient()


def _ok(data, **extra):
    if isinstance(data, list):
        return jsonify({"data": data, "count": len(data), **extra})
    return jsonify({"data": data, **extra})


def _handle(fn):
    """Run a client call, mapping EcourtsIndiaError to a JSON error response."""
    try:
        return _ok(fn())
    except EcourtsIndiaError as e:
        return jsonify(e.to_dict()), (e.status or 400)
    except Exception as e:  # noqa: BLE001 — last-resort guard for the route
        return jsonify({"error": str(e)}), 500


@eci_bp.get("/status")
def status():
    """Tell the frontend whether the API key is configured (no upstream call)."""
    return jsonify({
        "configured": _client.configured,
        "base_url": _client.base_url,
    })


@eci_bp.get("/case/<cnr>")
def case(cnr):
    return _handle(lambda: _client.get_case(cnr))


@eci_bp.post("/case/<cnr>/refresh")
def refresh(cnr):
    return _handle(lambda: _client.refresh_case(cnr))


@eci_bp.post("/case/bulk-refresh")
def bulk_refresh():
    body = request.get_json(silent=True) or {}
    cnrs = body.get("cnrs") if isinstance(body, dict) else body
    if not isinstance(cnrs, list) or not cnrs:
        return jsonify({"error": "body must be a JSON array of CNRs, or {\"cnrs\": [...]}"}), 400
    return _handle(lambda: _client.bulk_refresh(cnrs))


@eci_bp.get("/search")
def search():
    a = request.args
    return _handle(lambda: _client.search(
        query=a.get("query") or a.get("q"),
        advocates=a.get("advocates") or a.get("advocate"),
        judges=a.get("judges"),
        petitioners=a.get("petitioners"),
        respondents=a.get("respondents"),
        litigants=a.get("litigants"),
        court_codes=a.get("courtCodes"),
        case_types=a.get("caseTypes"),
        case_statuses=a.get("caseStatuses"),
        page=int(a.get("page", 1)),
        page_size=int(a.get("pageSize", 20)),
    ))


@eci_bp.get("/causelist/search")
def causelist_search():
    a = request.args
    return _handle(lambda: _client.causelist_search(
        q=a.get("q"),
        date=a.get("date"),
        start_date=a.get("startDate"),
        end_date=a.get("endDate"),
        judge=a.get("judge"),
        advocate=a.get("advocate"),
        state=a.get("state"),
        district_code=a.get("districtCode"),
        court_complex_code=a.get("courtComplexCode"),
        court=a.get("court"),
        court_no=a.get("courtNo"),
        bench=a.get("bench"),
        litigant=a.get("litigant"),
        list_type=a.get("listType"),
        limit=int(a.get("limit", 50)),
        offset=int(a.get("offset", 0)),
    ))


@eci_bp.get("/causelist/available-dates")
def causelist_available_dates():
    a = request.args
    return _handle(lambda: _client.causelist_available_dates(
        state=a.get("state"),
        district_code=a.get("districtCode"),
        court_complex_code=a.get("courtComplexCode"),
        court_no=a.get("courtNo"),
        court=a.get("court"),
    ))


@eci_bp.get("/enums")
def enums():
    return _handle(lambda: _client.get_enums(types=request.args.get("types")))


# ── court structure (free, no billing) ──

@eci_bp.get("/structure/states")
def structure_states():
    return _handle(_client.states)


@eci_bp.get("/structure/states/<state>/districts")
def structure_districts(state):
    return _handle(lambda: _client.districts(state))


@eci_bp.get("/structure/districts/<district_code>/complexes")
def structure_complexes(district_code):
    return _handle(lambda: _client.complexes(district_code))


@eci_bp.get("/structure/complexes/<complex_code>/courts")
def structure_courts(complex_code):
    return _handle(lambda: _client.courts(complex_code))
