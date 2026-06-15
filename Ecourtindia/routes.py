"""
Flask blueprint exposing the full eCourtsIndia Partner API to the frontend.

Mounted under /api/eci/* by server.py. Each route is a thin pass-through to
EcourtsIndiaClient, translating EcourtsIndiaError into a clean JSON error
with the upstream HTTP status preserved.

This is an additive, self-contained "competitor" data path (the eCourts API
tab in the UI) — it does not touch the original bharat-courts scraping routes.
"""

from flask import Blueprint, Response, jsonify, request

from .client import EcourtsIndiaClient, EcourtsIndiaError

eci_bp = Blueprint("eci", __name__, url_prefix="/api/eci")

_client = EcourtsIndiaClient()


def _ok(data, **extra):
    if isinstance(data, list):
        return jsonify({"data": data, "count": len(data), **extra})
    return jsonify({"data": data, **extra})


def _handle(fn):
    try:
        return _ok(fn())
    except EcourtsIndiaError as e:
        return jsonify(e.to_dict()), (e.status or 400)
    except Exception as e:  # noqa: BLE001 — last-resort guard for the route
        return jsonify({"error": str(e)}), 500


@eci_bp.get("/status")
def status():
    """Whether the API key is configured (no upstream call)."""
    return jsonify({
        "configured": _client.configured,
        "key_source": _client.key_source,
        "base_url": _client.base_url,
    })


# ── case ───────────────────────────────────────────────────────────────

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
        return jsonify({"error": 'body must be {"cnrs": [...]} or a JSON array'}), 400
    return _handle(lambda: _client.bulk_refresh(cnrs))


# ── orders ──────────────────────────────────────────────────────────────

@eci_bp.get("/case/<cnr>/order/<path:filename>")
def order_pdf(cnr, filename):
    """Stream the signed order PDF straight to the browser."""
    try:
        res = _client.order_pdf(cnr, filename)
    except EcourtsIndiaError as e:
        return jsonify(e.to_dict()), (e.status or 400)
    ct = res.get("_content_type") or "application/pdf"
    return Response(
        res.get("_raw", b""),
        mimetype=ct,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@eci_bp.get("/case/<cnr>/order-md/<path:filename>")
def order_md(cnr, filename):
    return _handle(lambda: _client.order_md(cnr, filename))


@eci_bp.get("/case/<cnr>/order-ai/<path:filename>")
def order_ai(cnr, filename):
    return _handle(lambda: _client.order_ai(cnr, filename))


# ── search ──────────────────────────────────────────────────────────────

# Map the lower-cased query keys the frontend may send to the PascalCase the
# API expects, so callers don't have to remember the casing.
_SEARCH_KEYS = [
    "Query", "Advocates", "Judges", "Petitioners", "Respondents", "Litigants",
    "CourtCodes", "CaseTypes", "StateCodes", "CaseStatuses", "BenchTypes",
    "FilingYears", "FilingDateFrom", "FilingDateTo", "HasOrders", "HasJudgments",
    "SortBy", "SortOrder", "IncludeFacetCounts", "Page", "PageSize",
]


@eci_bp.get("/search")
def search():
    a = request.args
    lower = {k.lower(): k for k in _SEARCH_KEYS}
    params = {}
    for k, v in a.items():
        if v == "":
            continue
        canonical = lower.get(k.lower(), k)  # accept exact or lower-cased keys
        params[canonical] = v
    if not params:
        return jsonify({"error": "provide at least one search parameter (e.g. Query, Advocates, Litigants)"}), 400
    return _handle(lambda: _client.search(**params))


# ── cause list ──────────────────────────────────────────────────────────

@eci_bp.get("/causelist/search")
def causelist_search():
    a = request.args
    return _handle(lambda: _client.causelist_search(
        q=a.get("q"), date=a.get("date"), start_date=a.get("startDate"),
        end_date=a.get("endDate"), judge=a.get("judge"), advocate=a.get("advocate"),
        state=a.get("state"), district_code=a.get("districtCode"),
        court_complex_code=a.get("courtComplexCode"), court=a.get("court"),
        court_no=a.get("courtNo"), bench=a.get("bench"), litigant=a.get("litigant"),
        list_type=a.get("listType"), limit=int(a.get("limit", 50)),
        offset=int(a.get("offset", 0)),
    ))


@eci_bp.get("/causelist/available-dates")
def causelist_available_dates():
    a = request.args
    return _handle(lambda: _client.causelist_available_dates(
        state=a.get("state"), district_code=a.get("districtCode"),
        court_complex_code=a.get("courtComplexCode"), court_no=a.get("courtNo"),
        court=a.get("court"),
    ))


# ── reference data ──────────────────────────────────────────────────────

@eci_bp.get("/enums")
def enums():
    return _handle(lambda: _client.get_enums(types=request.args.get("types")))


@eci_bp.get("/structure/states")
def structure_states():
    return _handle(_client.states)


@eci_bp.get("/structure/states/<state>/districts")
def structure_districts(state):
    return _handle(lambda: _client.districts(state))


@eci_bp.get("/structure/states/<state>/districts/<district_code>/complexes")
def structure_complexes(state, district_code):
    return _handle(lambda: _client.complexes(state, district_code))


@eci_bp.get("/structure/states/<state>/districts/<district_code>/complexes/<complex_code>/courts")
def structure_courts(state, district_code, complex_code):
    return _handle(lambda: _client.courts(state, district_code, complex_code))
