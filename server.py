"""
Maharashtra Courts backend — focused app for advocate queries.

Three features:
  1. Court hierarchy (district → complex), saved to localStorage
  2. All Cases by Advocate (one-shot search across history)
  3. Daily Cause List by Advocate (scan all courts on a date)

Plus a case-detail endpoint that fetches the rich case-history HTML
from the home/viewHistory endpoint, parses it into structured JSON.
"""

import asyncio
import os
import re
import time

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_file

from bharat_courts import DistrictCourtClient
from bharat_courts.districtcourts.parser import (
    parse_complex_value,
    parse_case_status_html,
    parse_cause_list_html,
)
from bs4 import BeautifulSoup

load_dotenv()

app = Flask(__name__)
PORT = int(os.getenv("FLASK_PORT", 5002))
STATE = "1"  # Maharashtra
MAX_RETRIES = 3


# ── infrastructure ─────────────────────────────────────────────────────

def _run(coro):
    """Run async coro with retries — eCourts drops connections under load."""
    for attempt in range(MAX_RETRIES):
        try:
            return asyncio.run(coro())
        except Exception as e:
            if "disconnect" in str(e).lower() or "reset" in str(e).lower():
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2 * (attempt + 1))
                    continue
            raise


def _ok(data, **extra):
    return jsonify({"data": data, "count": len(data) if isinstance(data, list) else 1, **extra})


def _err(msg, status=400):
    return jsonify({"error": msg}), status


def _require(*names):
    vals = {}
    for n in names:
        v = request.args.get(n)
        if not v:
            return None, _err(f"missing required parameter: {n}")
        vals[n] = v
    return vals, None


def _norm(s):
    """Normalize for advocate-name matching: lowercase, strip spaces+periods."""
    return re.sub(r"[\s.]+", "", (s or "").lower())


# ── routes ─────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return send_file("index.html")


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


# ─── Court hierarchy (no CAPTCHA) ──

@app.get("/api/districts")
def districts():
    async def _go():
        async with DistrictCourtClient() as c:
            return await c.list_districts(STATE)
    try:
        d = _run(_go)
        items = [{"code": k, "name": v} for k, v in sorted(d.items(), key=lambda x: x[1])]
        return _ok(items)
    except Exception as e:
        return _err(str(e), 500)


@app.get("/api/complexes")
def complexes():
    p, err = _require("dist")
    if err:
        return err
    async def _go():
        async with DistrictCourtClient() as c:
            return await c.list_complexes(STATE, p["dist"])
    try:
        d = _run(_go)
        items = [{"code": k, "name": v} for k, v in sorted(d.items(), key=lambda x: x[1])]
        return _ok(items)
    except Exception as e:
        return _err(str(e), 500)


# ─── All Cases by Advocate (one-shot search across history) ──

@app.get("/api/search-advocate")
def search_advocate():
    """Search every case the advocate has appeared in (uses eCourts submitAdvName)."""
    p, err = _require("dist", "complex", "advocate")
    if err:
        return err
    status = request.args.get("status", "Both")
    code, _, _ = parse_complex_value(p["complex"])

    async def _go():
        async with DistrictCourtClient() as c:
            def build_form(captcha):
                return {
                    "radAdvt": "1",
                    "advocate_name": p["advocate"],
                    "case_status": status,
                    "adv_captcha_code": captcha,
                    "state_code": STATE,
                    "dist_code": p["dist"],
                    "court_complex_code": code,
                    "est_code": "",
                    "case_type": "",
                }
            result = await c._post_with_captcha_retry(
                "casestatus/submitAdvName", build_form,
                state_code=STATE, dist_code=p["dist"],
                court_complex_code=code, est_code="",
            )
            html = result.get("adv_data", "")
            cases = parse_case_status_html(html)
            # Also extract viewHistory params per case so the UI can call /api/case-detail
            vh_calls = re.findall(r"viewHistory\(([^)]+)\)", html)
            vh_map = {}
            for call in vh_calls:
                args = [a.strip().strip("'") for a in call.split(",")]
                if len(args) >= 3:
                    cino = args[1]
                    vh_map[cino] = {
                        "case_no_id": args[0],
                        "cino": args[1],
                        "court_code": args[2],
                        "search_by": args[8] if len(args) > 8 else "CScaseNumber",
                    }
            out = []
            for cs in cases:
                d = _case_to_dict(cs)
                if cs.cnr_number and cs.cnr_number in vh_map:
                    d["_view_params"] = vh_map[cs.cnr_number]
                out.append(d)
            return out
    try:
        return _ok(_run(_go))
    except Exception as e:
        return _err(str(e), 500)


# ─── Daily Cause List by Advocate ──

async def _fetch_cause_list_raw(client, dist, complex_code, court_no, court_name, date_str, civil):
    """
    Fetch a cause list using the raw eCourts endpoint.
    The bharat-courts SDK's cause_list() looks for 'causelist_data', but the
    actual response field is 'case_data'. This bypasses that bug, and also
    returns the raw HTML so we can extract viewHistory params per row.
    """
    def build_form(captcha):
        return {
            "CL_court_no": court_no,
            "causelist_date": date_str,
            "cause_list_captcha_code": captcha,
            "court_name_txt": court_name,
            "state_code": STATE,
            "dist_code": dist,
            "court_complex_code": complex_code,
            "est_code": "",
            "cicri": "civ" if civil else "cri",
            "selprevdays": "0",
        }
    result = await client._post_with_captcha_retry(
        "cause_list/submitCauseList", build_form,
        state_code=STATE, dist_code=dist,
        court_complex_code=complex_code, est_code="",
    )
    html = result.get("case_data", "")
    return parse_cause_list_html(html), html


def _parse_view_history_calls(html):
    """
    Extract every viewHistory() call from cause list HTML and return a list
    of dicts keyed by case_number text (for matching back to parsed entries).
    """
    out = []
    calls = re.findall(r"viewHistory\(([^)]+)\)", html)
    for call in calls:
        args = [a.strip().strip("'") for a in call.split(",")]
        if len(args) >= 3:
            out.append({
                "case_no_id": args[0],
                "cino": args[1],
                "court_code": args[2],
                "search_by": args[8] if len(args) > 8 else "CauseList",
            })
    return out


def _parse_case_no_from_text(text):
    """Extract case type and number-year from a cause list case_number string.
    e.g. 'ViewR.C.S./13/2024Next hearing date:- 15-06-2026' → ('R.C.S.', '13', '2024')."""
    s = (text or "").replace("View", "").split("Next")[0].strip()
    m = re.match(r"^([A-Za-z. ]+\.?)/(\d+)/(\d{4})$", s)
    if m:
        return m.group(1).strip(), m.group(2), m.group(3)
    return s, "", ""


@app.get("/api/scan-advocate")
def scan_advocate():
    """Scan every court's cause list on a date and filter for an advocate name."""
    p, err = _require("dist", "complex", "advocate")
    if err:
        return err
    date_str = request.args.get("date", "")
    civil_arg = request.args.get("civil", "both").lower()
    code, _, _ = parse_complex_value(p["complex"])
    needle = _norm(p["advocate"])

    if civil_arg in ("true", "civil"):
        list_types = [True]
    elif civil_arg in ("false", "criminal"):
        list_types = [False]
    else:
        list_types = [True, False]

    async def _go():
        async with DistrictCourtClient() as c:
            courts = await c.list_cause_list_courts(STATE, p["dist"], code, "")
            real = {cn: name for cn, name in courts.items() if cn != "D"}
            matches = []
            scanned = []
            for court_no, court_name in real.items():
                for civil in list_types:
                    tag = "civil" if civil else "criminal"
                    scanned.append(f"{court_no}/{tag}")
                    try:
                        entries, raw_html = await _fetch_cause_list_raw(
                            c, p["dist"], code, court_no, court_name, date_str, civil,
                        )
                    except Exception:
                        continue
                    vh_list = _parse_view_history_calls(raw_html)
                    # Pair viewHistory data with parsed entries by index
                    for idx, e in enumerate(entries):
                        ap = e.advocate_petitioner or ""
                        ar = e.advocate_respondent or ""
                        if needle in _norm(ap) or needle in _norm(ar):
                            case_type, num, year = _parse_case_no_from_text(e.case_number)
                            vh = vh_list[idx] if idx < len(vh_list) else {}
                            matches.append({
                                "case_number": (e.case_number or "").replace("View", "").split("Next")[0].strip(),
                                "case_type": case_type,
                                "case_number_only": num,
                                "year": year,
                                "petitioner": e.petitioner.split("versus")[0].strip() if e.petitioner else "",
                                "respondent": (
                                    e.respondent.split("vs")[0].strip() if e.respondent
                                    else (e.petitioner.split("versus")[1].split("vs")[0].strip()
                                          if e.petitioner and "versus" in e.petitioner else "")
                                ),
                                "advocate_petitioner": ap,
                                "advocate_respondent": ar,
                                "advocate_role": "petitioner" if needle in _norm(ap) else "respondent",
                                "court_no": court_no,
                                "court_name": court_name,
                                "list_type": tag,
                                "cnr_number": vh.get("cino", ""),
                                "_view_params": vh,
                            })
            return matches, scanned
    try:
        matches, scanned = _run(_go)
        return _ok(matches, courts_scanned=scanned, date=date_str or "today", advocate=p["advocate"])
    except Exception as e:
        return _err(str(e), 500)


# ─── Case detail (for "View Details" buttons) ──

def _text(el):
    if el is None:
        return ""
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()


def _parse_case_detail(html):
    """Parse the home/viewHistory response HTML into structured JSON."""
    soup = BeautifulSoup(html, "html.parser")
    out = {
        "case_details": {},
        "case_status": {},
        "petitioners": [],
        "respondents": [],
        "acts": [],
        "case_history": [],
        "interim_orders": [],
        "process_details": [],
        "transfer_details": [],
    }

    def grab_label_table(heading_text):
        """Find a heading-table pair and turn it into a key→value dict."""
        for h in soup.find_all(["h2", "h3"]):
            if heading_text.lower() in _text(h).lower():
                tbl = h.find_next("table")
                if not tbl:
                    return {}
                kv = {}
                for tr in tbl.find_all("tr"):
                    cells = tr.find_all(["td", "th"])
                    if len(cells) == 2:
                        kv[_text(cells[0]).rstrip(":")] = _text(cells[1])
                    elif len(cells) == 4:
                        kv[_text(cells[0]).rstrip(":")] = _text(cells[1])
                        kv[_text(cells[2]).rstrip(":")] = _text(cells[3])
                return kv
        return {}

    out["case_details"] = grab_label_table("Case Details")
    out["case_status"] = grab_label_table("Case Status")

    # Petitioner and Advocate
    for h in soup.find_all(["h2", "h3", "h4"]):
        ht = _text(h).lower()
        if "petitioner" in ht and "advocate" in ht:
            target = h.find_next("table")
            if target:
                for tr in target.find_all("tr"):
                    txt = _text(tr)
                    if txt:
                        out["petitioners"].append(txt)
            break
    for h in soup.find_all(["h2", "h3", "h4"]):
        ht = _text(h).lower()
        if "respondent" in ht and "advocate" in ht:
            target = h.find_next("table")
            if target:
                for tr in target.find_all("tr"):
                    txt = _text(tr)
                    if txt:
                        out["respondents"].append(txt)
            break

    # Acts
    for h in soup.find_all(["h2", "h3"]):
        if _text(h).strip().lower() == "acts":
            tbl = h.find_next("table")
            if tbl:
                rows = tbl.find_all("tr")
                for tr in rows[1:]:
                    cells = tr.find_all(["td", "th"])
                    if len(cells) >= 2:
                        out["acts"].append({
                            "act": _text(cells[0]),
                            "section": _text(cells[1]),
                        })
            break

    # Case History
    for h in soup.find_all(["h2", "h3"]):
        if "case history" in _text(h).lower():
            tbl = h.find_next("table")
            if tbl:
                rows = tbl.find_all("tr")
                for tr in rows[1:]:
                    cells = tr.find_all(["td", "th"])
                    if len(cells) >= 4:
                        out["case_history"].append({
                            "judge": _text(cells[0]),
                            "business_date": _text(cells[1]),
                            "hearing_date": _text(cells[2]),
                            "purpose": _text(cells[3]),
                        })
            break

    # Interim Orders
    for h in soup.find_all(["h2", "h3"]):
        if "interim orders" in _text(h).lower():
            tbl = h.find_next("table")
            if tbl:
                rows = tbl.find_all("tr")
                for tr in rows[1:]:
                    cells = tr.find_all(["td", "th"])
                    if len(cells) >= 3:
                        out["interim_orders"].append({
                            "order_no": _text(cells[0]),
                            "order_date": _text(cells[1]),
                            "order_details": _text(cells[2]),
                        })
            break

    return out


@app.get("/api/case-detail")
def case_detail():
    """Fetch full case detail via eCourts home/viewHistory.

    Required: case_no_id, cino, court_code, dist, complex (+ optional search_by).
    No CAPTCHA needed for viewHistory.
    """
    p, err = _require("case_no_id", "cino", "court_code", "dist", "complex")
    if err:
        return err
    search_by = request.args.get("search_by", "CScaseNumber")
    code, _, _ = parse_complex_value(p["complex"])

    async def _go():
        async with DistrictCourtClient() as c:
            await c._init_session()
            await c._setup_court(
                state_code=STATE, dist_code=p["dist"],
                court_complex_code=code, est_code="",
            )
            form = {
                "court_code": p["court_code"],
                "state_code": STATE,
                "dist_code": p["dist"],
                "court_complex_code": code,
                "case_no": p["case_no_id"],
                "cino": p["cino"],
                "hideparty": "",
                "search_flag": search_by,
                "search_by": search_by,
            }
            result = await c._post_ajax("home/viewHistory", form)
            html = result.get("data_list", "")
            return _parse_case_detail(html)
    try:
        return jsonify(_run(_go))
    except Exception as e:
        return _err(str(e), 500)


# ── shared helpers ─────────────────────────────────────────────────────

def _case_to_dict(c):
    return {
        "case_number": c.case_number,
        "case_type": c.case_type,
        "cnr_number": c.cnr_number,
        "filing_number": c.filing_number,
        "registration_number": c.registration_number,
        "registration_date": c.registration_date,
        "petitioner": c.petitioner,
        "respondent": c.respondent,
        "status": c.status,
        "court_name": c.court_name,
        "judges": c.judges,
        "next_hearing_date": c.next_hearing_date,
    }


if __name__ == "__main__":
    print(f"\n  Maharashtra Courts → http://localhost:{PORT}\n")
    app.run(host="localhost", port=PORT, debug=True)
