import asyncio
import os
import re
import time

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_file

from bharat_courts import DistrictCourtClient
from bharat_courts.districtcourts.parser import parse_complex_value, parse_case_status_html, parse_cause_list_html

load_dotenv()

app = Flask(__name__)
PORT = int(os.getenv("FLASK_PORT", 5002))
STATE = "1"  # Maharashtra
MAX_RETRIES = 3


# ── helpers ──────────────────────────────────────────────────────────

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


async def _discover_court_nos(client, dist, complex_code, date_str, civil):
    try:
        await client.cause_list(
            state_code=STATE, dist_code=dist,
            court_complex_code=complex_code, est_code="",
            court_no="__probe__", causelist_date=date_str, civil=civil,
        )
        return []
    except Exception as ex:
        m = re.search(r"Available:\s*(\[[^\]]+\])", str(ex))
        if not m:
            return []
        return [c for c in re.findall(r"'([^']+)'", m.group(1)) if c != "D"]


# ── routes ───────────────────────────────────────────────────────────

@app.get("/")
def index():
    return send_file("index.html")


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


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


@app.get("/api/case-types")
def case_types():
    p, err = _require("dist", "complex")
    if err:
        return err
    code, _, _ = parse_complex_value(p["complex"])
    async def _go():
        async with DistrictCourtClient() as c:
            return await c.list_case_types(STATE, p["dist"], code, "")
    try:
        d = _run(_go)
        items = [{"code": k, "name": v} for k, v in sorted(d.items(), key=lambda x: x[1])]
        return _ok(items)
    except Exception as e:
        return _err(str(e), 500)


@app.get("/api/cause-list")
def cause_list():
    p, err = _require("dist", "complex")
    if err:
        return err
    date_str = request.args.get("date", "")
    civil = request.args.get("civil", "true").lower() != "false"
    code, _, _ = parse_complex_value(p["complex"])

    async def _go():
        async with DistrictCourtClient() as c:
            court_nos = await _discover_court_nos(c, p["dist"], code, date_str, civil)
            all_entries = []
            for cno in court_nos:
                try:
                    entries = await c.cause_list(
                        state_code=STATE, dist_code=p["dist"],
                        court_complex_code=code, est_code="",
                        court_no=cno, causelist_date=date_str, civil=civil,
                    )
                    for e in entries:
                        all_entries.append({
                            "item_number": e.item_number,
                            "case_number": e.case_number,
                            "case_type": e.case_type,
                            "petitioner": e.petitioner,
                            "respondent": e.respondent,
                            "advocate_petitioner": e.advocate_petitioner,
                            "advocate_respondent": e.advocate_respondent,
                            "court_number": e.court_number,
                            "judge": e.judge,
                            "listing_date": e.listing_date,
                        })
                except Exception:
                    continue
            return all_entries, court_nos
    try:
        entries, court_nos = _run(_go)
        return _ok(entries, court_nos_scanned=court_nos, date=date_str or "today")
    except Exception as e:
        return _err(str(e), 500)


@app.get("/api/search-party")
def search_party():
    p, err = _require("dist", "complex", "party")
    if err:
        return err
    year = request.args.get("year", "2025")
    status = request.args.get("status", "Both")
    code, _, _ = parse_complex_value(p["complex"])

    async def _go():
        async with DistrictCourtClient() as c:
            cases = await c.case_status_by_party(
                state_code=STATE, dist_code=p["dist"],
                court_complex_code=code, est_code="",
                party_name=p["party"], year=year, status_filter=status,
            )
            return [_case_to_dict(cs) for cs in cases]
    try:
        return _ok(_run(_go))
    except Exception as e:
        return _err(str(e), 500)


@app.get("/api/case")
def case_lookup():
    p, err = _require("dist", "complex", "case_type", "case_number", "year")
    if err:
        return err
    code, _, _ = parse_complex_value(p["complex"])

    async def _go():
        async with DistrictCourtClient() as c:
            cases = await c.case_status(
                state_code=STATE, dist_code=p["dist"],
                court_complex_code=code, est_code="",
                case_type=p["case_type"], case_number=p["case_number"],
                year=p["year"],
            )
            return [_case_to_dict(cs) for cs in cases]
    try:
        return _ok(_run(_go))
    except Exception as e:
        return _err(str(e), 500)


@app.get("/api/search-advocate")
def search_advocate():
    """Search cases by advocate name — calls eCourts submitAdvName directly."""
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
                "casestatus/submitAdvName",
                build_form,
                state_code=STATE,
                dist_code=p["dist"],
                court_complex_code=code,
                est_code="",
            )
            html = result.get("adv_data", "")
            cases = parse_case_status_html(html)
            return [_case_to_dict(cs) for cs in cases]
    try:
        return _ok(_run(_go))
    except Exception as e:
        return _err(str(e), 500)


@app.get("/api/advocate-causelist")
def advocate_causelist():
    """Get an advocate's cause list for a date, by bar registration number."""
    p, err = _require("dist", "complex", "bar_state", "bar_code", "bar_year", "date")
    if err:
        return err
    code, _, _ = parse_complex_value(p["complex"])

    async def _go():
        async with DistrictCourtClient() as c:
            def build_form(captcha):
                return {
                    "radAdvt": "3",
                    "adv_bar_state": p["bar_state"],
                    "adv_bar_code": p["bar_code"],
                    "adv_bar_year": p["bar_year"],
                    "caselist_date": p["date"],
                    "adv_captcha_code": captcha,
                    "state_code": STATE,
                    "dist_code": p["dist"],
                    "court_complex_code": code,
                    "est_code": "",
                    "case_type": "",
                }
            result = await c._post_with_captcha_retry(
                "casestatus/submitAdvName",
                build_form,
                state_code=STATE,
                dist_code=p["dist"],
                court_complex_code=code,
                est_code="",
            )
            html = result.get("adv_data", "")
            cases = parse_case_status_html(html)
            return [_case_to_dict(cs) for cs in cases]
    try:
        return _ok(_run(_go))
    except Exception as e:
        return _err(str(e), 500)


async def _list_cl_courts(client, dist, complex_code):
    """Get the full court_no → court_name mapping from fillCauseList."""
    return await client.list_cause_list_courts(STATE, dist, complex_code, "")


async def _fetch_cause_list_raw(client, dist, complex_code, court_no, court_name, date_str, civil):
    """
    Fetch a cause list using the raw eCourts endpoint.
    The bharat-courts SDK's cause_list() looks for 'causelist_data' in the response,
    but the actual response field is 'case_data'. This bypasses that bug.
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
    return parse_cause_list_html(result.get("case_data", ""))


@app.get("/api/scan-advocate")
def scan_advocate():
    """Scan every court's cause list on a date and filter for an advocate name."""
    p, err = _require("dist", "complex", "advocate")
    if err:
        return err
    date_str = request.args.get("date", "")
    civil_arg = request.args.get("civil", "both").lower()
    code, _, _ = parse_complex_value(p["complex"])
    needle = p["advocate"].lower()

    # Decide which lists to scan
    if civil_arg == "true" or civil_arg == "civil":
        list_types = [True]
    elif civil_arg == "false" or civil_arg == "criminal":
        list_types = [False]
    else:
        list_types = [True, False]

    async def _go():
        async with DistrictCourtClient() as c:
            courts = await _list_cl_courts(c, p["dist"], code)
            # courts is {court_no: court_name} — filter out 'D' (district summary)
            real = {cn: name for cn, name in courts.items() if cn != "D"}
            matches = []
            scanned = []
            for court_no, court_name in real.items():
                for civil in list_types:
                    tag = "civil" if civil else "criminal"
                    scanned.append(f"{court_no}/{tag}")
                    try:
                        entries = await _fetch_cause_list_raw(
                            c, p["dist"], code, court_no, court_name, date_str, civil,
                        )
                    except Exception:
                        continue
                    for e in entries:
                        ap = (e.advocate_petitioner or "")
                        ar = (e.advocate_respondent or "")
                        if needle in ap.lower() or needle in ar.lower():
                            matches.append({
                                "case_number": (e.case_number or "").replace("View", "").split("Next")[0].strip(),
                                "petitioner": e.petitioner.split("versus")[0].strip() if e.petitioner else "",
                                "respondent": (e.respondent.split("vs")[0].strip() if e.respondent
                                               else (e.petitioner.split("versus")[1].split("vs")[0].strip()
                                                     if e.petitioner and "versus" in e.petitioner else "")),
                                "advocate_petitioner": ap,
                                "advocate_respondent": ar,
                                "advocate_role": "petitioner" if needle in ap.lower() else "respondent",
                                "court_no": court_no,
                                "court_name": court_name,
                                "list_type": tag,
                            })
            return matches, scanned
    try:
        matches, scanned = _run(_go)
        return _ok(matches, courts_scanned=scanned, date=date_str or "today", advocate=p["advocate"])
    except Exception as e:
        return _err(str(e), 500)


@app.get("/api/orders")
def orders():
    p, err = _require("dist", "complex", "case_type", "case_number", "year")
    if err:
        return err
    code, _, _ = parse_complex_value(p["complex"])

    async def _go():
        async with DistrictCourtClient() as c:
            ords = await c.court_orders(
                state_code=STATE, dist_code=p["dist"],
                court_complex_code=code, est_code="",
                case_type=p["case_type"], case_number=p["case_number"],
                year=p["year"],
            )
            return [{
                "order_date": o.order_date,
                "order_type": o.order_type,
                "judge": o.judge,
                "pdf_url": o.pdf_url,
            } for o in ords]
    try:
        return _ok(_run(_go))
    except Exception as e:
        return _err(str(e), 500)


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
