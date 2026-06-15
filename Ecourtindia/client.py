"""
Thin Python client for the eCourtsIndia Partner API.

Docs: https://ecourtsindia.com/api/docs
Guide: https://blogs.ecourtsindia.com/2026/05/18/how-to-use-ecourtsindia-api/
Base URL: https://webapi.ecourtsindia.com

Unlike the bharat-courts scraping path (which solves a CAPTCHA per request),
this is a clean authenticated REST API: a Bearer token (eci_live_…) in the
Authorization header, JSON in, JSON out. Court-structure and enum endpoints
are free; most others consume credits.

Every JSON call returns the already-unwrapped `data` payload (or the raw body
when the endpoint isn't wrapped, e.g. court-structure), or raises
EcourtsIndiaError carrying the API's structured error code/message. The
parameter names and paths here were verified against the live API.
"""

import os

import requests

from .secret import get_api_key

DEFAULT_BASE_URL = "https://webapi.ecourtsindia.com"


class EcourtsIndiaError(Exception):
    """Raised when the API returns a structured error or the call fails."""

    def __init__(self, message, code=None, status=None, details=None, request_id=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.details = details or {}
        self.request_id = request_id

    def to_dict(self):
        return {
            "error": self.message,
            "code": self.code,
            "status": self.status,
            "details": self.details,
            "request_id": self.request_id,
        }


class EcourtsIndiaClient:
    """Synchronous client for the eCourtsIndia Partner API."""

    def __init__(self, api_key=None, base_url=None, timeout=90):
        self.api_key = api_key if api_key is not None else get_api_key()
        self.base_url = (base_url or os.getenv("ECOURTS_API_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout

    @property
    def configured(self):
        return bool(self.api_key)

    @property
    def key_source(self):
        return "env" if os.getenv("ECOURTS_API_KEY", "").strip() else ("embedded" if self.api_key else "none")

    # ── transport ──────────────────────────────────────────────────────

    def _headers(self, auth=True, accept="application/json"):
        h = {"Accept": accept}
        if auth:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _request(self, method, path, params=None, json_body=None, auth=True, raw=False):
        if auth and not self.api_key:
            raise EcourtsIndiaError(
                "ECOURTS_API_KEY is not configured on the server.",
                code="MISSING_API_KEY", status=401,
            )
        url = f"{self.base_url}{path}"
        clean = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        try:
            resp = requests.request(
                method, url,
                params=clean or None,
                json=json_body,
                headers=self._headers(auth=auth, accept="*/*" if raw else "application/json"),
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise EcourtsIndiaError(f"network error reaching eCourtsIndia: {e}", code="NETWORK_ERROR", status=502)

        if raw and resp.ok:
            return {
                "_raw": resp.content,
                "_content_type": resp.headers.get("Content-Type", "application/octet-stream"),
            }

        try:
            body = resp.json()
        except ValueError:
            if resp.ok:
                return {"_raw": resp.content, "_content_type": resp.headers.get("Content-Type", "")}
            raise EcourtsIndiaError(
                f"unexpected non-JSON response (HTTP {resp.status_code})",
                code="BAD_RESPONSE", status=resp.status_code,
            )

        if not resp.ok or (isinstance(body, dict) and body.get("error")):
            err = body.get("error") if isinstance(body, dict) else None
            meta = body.get("meta") if isinstance(body, dict) else None
            if isinstance(err, dict):
                raise EcourtsIndiaError(
                    err.get("message") or "API error", code=err.get("code"),
                    status=resp.status_code, details=err.get("details"),
                    request_id=(meta or {}).get("requestId") or (meta or {}).get("request_id"),
                )
            raise EcourtsIndiaError(
                str(err) or f"API error (HTTP {resp.status_code})", status=resp.status_code,
                request_id=(meta or {}).get("requestId") or (meta or {}).get("request_id"),
            )

        # Wrapped responses are {"data": ..., "meta": {...}}; court-structure
        # endpoints return a bare list. Carry meta onto dict payloads.
        if isinstance(body, dict) and "data" in body:
            data = body["data"]
            if isinstance(data, dict) and isinstance(body.get("meta"), dict):
                data.setdefault("_meta", body["meta"])
            return data
        return body

    # ── case ───────────────────────────────────────────────────────────

    def get_case(self, cnr):
        """Full case record by 16-char CNR."""
        return self._request("GET", f"/api/partner/case/{cnr}")

    def refresh_case(self, cnr):
        """Queue an async re-scrape from the official eCourts source."""
        return self._request("POST", f"/api/partner/case/{cnr}/refresh")

    def bulk_refresh(self, cnrs):
        """Queue 2–50 CNRs at once. Returns refreshed/queued/invalid breakdown."""
        return self._request("POST", "/api/partner/case/bulk-refresh", json_body={"cnrs": list(cnrs)})

    # ── orders (three formats) ─────────────────────────────────────────

    def order_pdf(self, cnr, filename):
        """Digitally-signed order PDF (binary). Returns {_raw, _content_type}."""
        return self._request("GET", f"/api/partner/case/{cnr}/order/{filename}", raw=True)

    def order_md(self, cnr, filename):
        """OCR-cleaned markdown for an order."""
        return self._request("GET", f"/api/partner/case/{cnr}/order-md/{filename}")

    def order_ai(self, cnr, filename):
        """Order markdown plus structured AI analysis (summary, key points, outcome)."""
        return self._request("GET", f"/api/partner/case/{cnr}/order-ai/{filename}")

    # ── search ─────────────────────────────────────────────────────────

    def search(self, **kwargs):
        """
        Full-text + faceted case search. Accepts (PascalCase as the API expects):
        Query, Advocates, Judges, Petitioners, Respondents, Litigants,
        CourtCodes, CaseTypes, StateCodes, CaseStatuses, BenchTypes,
        FilingYears, FilingDateFrom, FilingDateTo, HasOrders, HasJudgments,
        SortBy, SortOrder, IncludeFacetCounts, Page, PageSize (max 100).
        """
        params = dict(kwargs)
        if params.get("PageSize"):
            params["PageSize"] = min(int(params["PageSize"]), 100)
        return self._request("GET", "/api/partner/search", params=params)

    # ── cause list ─────────────────────────────────────────────────────

    def causelist_search(self, q=None, date=None, start_date=None, end_date=None,
                         judge=None, advocate=None, state=None, district_code=None,
                         court_complex_code=None, court=None, court_no=None,
                         bench=None, litigant=None, list_type=None, limit=50, offset=0):
        """Search cause-list listings (window: ~1 day back to 7 days forward)."""
        params = {
            "q": q, "date": date, "startDate": start_date, "endDate": end_date,
            "judge": judge, "advocate": advocate, "state": state,
            "districtCode": district_code, "courtComplexCode": court_complex_code,
            "court": court, "courtNo": court_no, "bench": bench, "litigant": litigant,
            "listType": list_type, "limit": min(int(limit or 50), 100), "offset": offset,
        }
        return self._request("GET", "/api/partner/causelist/search", params=params)

    def causelist_available_dates(self, state=None, district_code=None,
                                  court_complex_code=None, court_no=None, court=None):
        """Dates (newest first) that have cause-list data for the given scope."""
        params = {
            "state": state, "districtCode": district_code,
            "courtComplexCode": court_complex_code, "courtNo": court_no, "court": court,
        }
        return self._request("GET", "/api/partner/causelist/available-dates", params=params)

    # ── reference data (free, no billing) ──────────────────────────────

    def get_enums(self, types=None):
        """Live enum reference. `types` is an optional comma-separated string."""
        return self._request("GET", "/api/partner/enums", params={"types": types})

    # Court structure is fully nested (verified against the live API).
    _CS = "/api/partner/causelist/court-structure"

    def states(self):
        return self._request("GET", f"{self._CS}/states")

    def districts(self, state):
        return self._request("GET", f"{self._CS}/states/{state}/districts")

    def complexes(self, state, district_code):
        return self._request("GET", f"{self._CS}/states/{state}/districts/{district_code}/complexes")

    def courts(self, state, district_code, complex_code):
        return self._request(
            "GET",
            f"{self._CS}/states/{state}/districts/{district_code}/complexes/{complex_code}/courts",
        )
