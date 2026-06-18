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

import db
from Ecourtindia import eci_bp

load_dotenv()

app = Flask(__name__)
app.register_blueprint(eci_bp)  # eCourtsIndia Partner API routes under /api/eci/*
PORT = int(os.getenv("PORT") or os.getenv("FLASK_PORT", 5002))  # Render injects PORT
STATE = "1"  # Maharashtra
MAX_RETRIES = 3

db.init()  # create tables on startup


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


def _force_refresh():
    return request.args.get("refresh", "").lower() in ("1", "true", "yes")


def _today_dd():
    return time.strftime("%d-%m-%Y", time.localtime())


def _is_past_date(date_str):
    """date_str is DD-MM-YYYY. Returns True if strictly before today."""
    try:
        t = time.strptime(date_str, "%d-%m-%Y")
        return time.mktime(t) < time.mktime(time.strptime(_today_dd(), "%d-%m-%Y"))
    except Exception:
        return False


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
    key = STATE
    if not _force_refresh():
        cached, age = db.get_cached("districts", key, db.TTL["districts"])
        if cached is not None:
            return _ok(cached, cached=True, age_seconds=age)
    async def _go():
        async with DistrictCourtClient() as c:
            return await c.list_districts(STATE)
    try:
        d = _run(_go)
        items = [{"code": k, "name": v} for k, v in sorted(d.items(), key=lambda x: x[1])]
        db.put_cached("districts", key, items, len(items))
        return _ok(items, cached=False, age_seconds=0)
    except Exception as e:
        return _err(str(e), 500)


@app.get("/api/complexes")
def complexes():
    p, err = _require("dist")
    if err:
        return err
    key = f"{STATE}/{p['dist']}"
    if not _force_refresh():
        cached, age = db.get_cached("complexes", key, db.TTL["complexes"])
        if cached is not None:
            return _ok(cached, cached=True, age_seconds=age)
    async def _go():
        async with DistrictCourtClient() as c:
            return await c.list_complexes(STATE, p["dist"])
    try:
        d = _run(_go)
        items = [{"code": k, "name": v} for k, v in sorted(d.items(), key=lambda x: x[1])]
        db.put_cached("complexes", key, items, len(items))
        return _ok(items, cached=False, age_seconds=0)
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
    cache_key = f"{p['dist']}|{code}|{_norm(p['advocate'])}|{status}"

    if not _force_refresh():
        cached, age = db.get_cached("search_advocate", cache_key, db.TTL["search_advocate"])
        if cached is not None:
            return _ok(cached, cached=True, age_seconds=age)

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
        out = _run(_go)
        # persist every case so /api/my-cases sees them
        for d in out:
            vp = d.get("_view_params", {}) or {}
            db.upsert_case({
                "cnr": d.get("cnr_number"),
                "case_number": d.get("case_number"),
                "case_type": d.get("case_type"),
                "petitioner": d.get("petitioner"),
                "respondent": d.get("respondent"),
                "status": d.get("status"),
                "next_hearing": d.get("next_hearing_date"),
                "case_no_id": vp.get("case_no_id"),
                "court_code": vp.get("court_code"),
                "advocate_seen": p["advocate"],
                "source_query": f"search_advocate:{cache_key}",
            })
        db.put_cached("search_advocate", cache_key, out, len(out))
        return _ok(out, cached=False, age_seconds=0)
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

    cache_key = f"{p['dist']}|{code}|{needle}|{date_str}|{civil_arg}"
    ttl = db.TTL["cause_list_scan_past"] if _is_past_date(date_str) else db.TTL["cause_list_scan_future"]
    if not _force_refresh():
        cached, age = db.get_cached("scan_advocate", cache_key, ttl)
        if cached is not None:
            return _ok(cached.get("matches", []), cached=True, age_seconds=age,
                       courts_scanned=cached.get("courts_scanned", []),
                       date=cached.get("date", date_str or "today"),
                       advocate=p["advocate"])

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
        # persist cases + cause list entries
        for m in matches:
            vp = m.get("_view_params", {}) or {}
            db.upsert_case({
                "cnr": m.get("cnr_number"),
                "case_number": m.get("case_number"),
                "case_type": m.get("case_type"),
                "year": m.get("year"),
                "petitioner": m.get("petitioner"),
                "respondent": m.get("respondent"),
                "court_no": m.get("court_no"),
                "court_name": m.get("court_name"),
                "case_no_id": vp.get("case_no_id"),
                "court_code": vp.get("court_code"),
                "advocate_seen": p["advocate"],
                "source_query": f"scan_advocate:{cache_key}",
            })
            if m.get("cnr_number") and date_str:
                db.upsert_cause_list_entry({
                    "date": date_str,
                    "court_no": m.get("court_no"),
                    "cnr": m.get("cnr_number"),
                    "list_type": m.get("list_type"),
                    "adv_petitioner": m.get("advocate_petitioner"),
                    "adv_respondent": m.get("advocate_respondent"),
                })
        payload = {"matches": matches, "courts_scanned": scanned, "date": date_str or "today"}
        db.put_cached("scan_advocate", cache_key, payload, len(matches))
        return _ok(matches, cached=False, age_seconds=0, courts_scanned=scanned,
                   date=date_str or "today", advocate=p["advocate"])
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

    if not _force_refresh():
        cached, age = db.get_case_detail(p["cino"], db.TTL["case_detail"])
        if cached is not None:
            cached["_cached"] = True
            cached["_age_seconds"] = age
            return jsonify(cached)

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
        detail = _run(_go)
        db.put_case_detail(p["cino"], detail)
        # If we got case_details, update next_hearing on the case row
        cs = detail.get("case_status", {})
        nh = cs.get("Next Hearing Date") or cs.get("Next Hearing")
        if nh:
            db.upsert_case({"cnr": p["cino"], "next_hearing": nh,
                            "status": cs.get("Case Stage") or cs.get("Case Status")})
        detail["_cached"] = False
        detail["_age_seconds"] = 0
        return jsonify(detail)
    except Exception as e:
        return _err(str(e), 500)


# ─── My Cases ──

@app.get("/api/my-cases")
def my_cases():
    """List every case stored in the local DB. No eCourts call."""
    advocate = request.args.get("advocate", "").strip() or None
    limit = int(request.args.get("limit", "1000"))
    rows = db.list_cases(advocate=advocate, limit=limit)
    return _ok(rows, source="cache", total_in_db=db.case_count())


@app.get("/api/stats")
def stats_endpoint():
    return jsonify(db.stats())


@app.post("/api/refresh-cache")
def refresh_cache():
    """Wipe a specific cache key (useful for forcing a re-fetch)."""
    p, err = _require("query_type", "key")
    if err:
        return err
    db.invalidate(p["query_type"], p["key"])
    return jsonify({"ok": True})


# ─── Clients + reminders ──

import csv
import io
import urllib.parse


@app.get("/api/clients")
def clients_list():
    return _ok(db.list_clients())


@app.post("/api/clients")
def clients_add():
    """Add one client. Body: form fields name, phone, notes."""
    name = (request.form.get("name") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    notes = (request.form.get("notes") or "").strip()
    if not name:
        return _err("name is required")
    cid = db.add_client(name, phone, notes)
    return jsonify({"id": cid, "ok": True})


@app.post("/api/clients/<int:cid>/delete")
def clients_delete(cid):
    db.delete_client(cid)
    return jsonify({"ok": True})


@app.post("/api/clients/upload")
def clients_upload():
    """Upload a CSV of clients.

    Expected columns: name, phone, notes (notes optional).
    Headers are case-insensitive and order-independent.
    Phones get normalized to country-code-prefixed digits.
    """
    if "file" not in request.files:
        return _err("no file uploaded")
    f = request.files["file"]
    if not f.filename:
        return _err("empty filename")
    try:
        text = f.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return _err("file must be UTF-8 encoded CSV")
    reader = csv.DictReader(io.StringIO(text))
    # Normalize headers
    if reader.fieldnames is None:
        return _err("could not parse CSV headers")
    hdr_map = {h.lower().strip(): h for h in reader.fieldnames}
    name_col = hdr_map.get("name") or hdr_map.get("client") or hdr_map.get("party")
    phone_col = hdr_map.get("phone") or hdr_map.get("mobile") or hdr_map.get("whatsapp") or hdr_map.get("contact")
    notes_col = hdr_map.get("notes") or hdr_map.get("note") or hdr_map.get("remarks")
    if not name_col:
        return _err("CSV must have a 'name' column (or 'client' / 'party')")
    added = 0
    skipped = 0
    for row in reader:
        name = (row.get(name_col) or "").strip()
        if not name:
            skipped += 1
            continue
        phone = (row.get(phone_col) or "").strip() if phone_col else ""
        notes = (row.get(notes_col) or "").strip() if notes_col else ""
        db.add_client(name, phone, notes)
        added += 1
    return jsonify({"ok": True, "added": added, "skipped": skipped})


@app.get("/api/upcoming-hearings")
def upcoming_hearings():
    """Return upcoming hearings from `cases`, each annotated with
    candidate matching clients from the local contacts."""
    days = int(request.args.get("days", "30"))
    hearings = db.upcoming_hearings(days_ahead=days)
    out = []
    for h in hearings:
        # match against both petitioner and respondent
        candidates = {}
        for party_field in ("petitioner", "respondent"):
            party = h.get(party_field) or ""
            for cl in db.find_matching_clients(party):
                k = cl["id"]
                if k not in candidates or cl["_match_score"] > candidates[k]["_match_score"]:
                    cl["_party"] = party_field
                    cl["_party_text"] = party
                    candidates[k] = cl
        h["_matches"] = list(candidates.values())
        out.append(h)
    return _ok(out, days_ahead=days)


def _build_reminder_message(client_name, case_number, parties, hearing_date,
                            court_name, lawyer_name="Adv. J.A. Joshi",
                            language="en"):
    """Build a WhatsApp reminder message body."""
    parties_str = parties or ""
    court_str = court_name or ""
    if language == "mr":  # Marathi
        return (
            f"नमस्कार {client_name},\n\n"
            f"आपल्या प्रकरण {case_number} ची सुनावणी {hearing_date} रोजी आहे.\n"
            f"न्यायालय: {court_str}\n"
            f"प्रकरण: {parties_str}\n\n"
            f"कृपया वेळेवर हजर रहावे.\n\n"
            f"— {lawyer_name}"
        )
    return (
        f"Dear {client_name},\n\n"
        f"This is a reminder that your case {case_number} has its next hearing "
        f"on {hearing_date}.\n"
        f"Court: {court_str}\n"
        f"Parties: {parties_str}\n\n"
        f"Please be prepared to attend.\n\n"
        f"— {lawyer_name}"
    )


@app.get("/api/whatsapp-link")
def whatsapp_link():
    """Build a wa.me link with a pre-filled reminder message."""
    p, err = _require("client_id", "cnr")
    if err:
        return err
    lang = request.args.get("lang", "en")
    lawyer = request.args.get("lawyer", "Adv. J.A. Joshi")

    # look up client + case
    with db.conn() as c:
        client = c.execute("SELECT * FROM clients WHERE id = ?", (p["client_id"],)).fetchone()
        case = c.execute("SELECT * FROM cases WHERE cnr = ?", (p["cnr"],)).fetchone()
    if not client:
        return _err("client not found", 404)
    if not case:
        return _err("case not found", 404)
    client = dict(client)
    case = dict(case)

    parties = f"{case.get('petitioner') or ''} vs {case.get('respondent') or ''}"
    hearing = case.get("next_hearing") or ""
    msg = _build_reminder_message(
        client_name=client["name"],
        case_number=case.get("case_number") or "",
        parties=parties,
        hearing_date=hearing,
        court_name=case.get("court_name") or "",
        lawyer_name=lawyer,
        language=lang,
    )
    phone = client.get("phone") or ""
    if not phone:
        return _err("client has no phone number", 400)
    link = f"https://wa.me/{phone}?text={urllib.parse.quote(msg)}"
    return jsonify({
        "ok": True,
        "link": link,
        "message": msg,
        "phone": phone,
        "client_name": client["name"],
    })


@app.post("/api/log-reminder")
def log_reminder_endpoint():
    """Record that a reminder was sent. client_id comes from the POST form body."""
    client_id = request.form.get("client_id")
    if not client_id:
        return _err("missing required parameter: client_id")
    cnr = request.form.get("cnr") or ""
    hearing = request.form.get("hearing_date") or ""
    message = request.form.get("message") or ""
    db.log_reminder(int(client_id), cnr, hearing, message)
    return jsonify({"ok": True})


@app.get("/api/reminders")
def reminders_list():
    return _ok(db.recent_reminders())


@app.post("/api/causelist-reminders")
def causelist_reminders():
    """Turn eCourtsIndia cause-list matters into ready-to-send reminders.

    Body (JSON): {
      "matters": [ <cause-list entries from /api/eci/causelist/search> ],
      "lang": "en"|"mr", "lawyer": "Adv. ..."
    }
    For each matter we match its parties against the local contacts and build a
    WhatsApp reminder for the listing date — so the whole day's board can go out
    in one pass. No eCourts call; pure local matching. Nothing is persisted.
    """
    body = request.get_json(silent=True) or {}
    matters = body.get("matters") or []
    if not isinstance(matters, list):
        return _err("matters must be a list")
    lang = body.get("lang", "en")
    lawyer = body.get("lawyer") or "Adv. J.A. Joshi"

    out = []
    seen = set()  # (client_id, case_number, date) → one reminder per matter
    for m in matters:
        if not isinstance(m, dict):
            continue
        date = m.get("date") or ""
        court = m.get("courtName") or m.get("court") or ""
        case_no = m.get("caseNumber")
        if isinstance(case_no, list):
            case_no = ", ".join(str(x) for x in case_no)
        case_no = case_no or ""

        pet = m.get("petitioners") if isinstance(m.get("petitioners"), list) else []
        res = m.get("respondents") if isinstance(m.get("respondents"), list) else []
        party_strings = list(pet) + list(res)
        if m.get("party"):
            # also split a combined "A Vs B" string into its sides
            party_strings += re.split(r"\bv/?s\.?\b", m["party"], flags=re.IGNORECASE)
        parties_text = m.get("party") or " vs ".join(filter(None, [", ".join(pet), ", ".join(res)]))

        # collect best-scoring client match per matter
        candidates = {}
        for ps in party_strings:
            for cl in db.find_matching_clients(ps):
                cur = candidates.get(cl["id"])
                if cur is None or cl["_match_score"] > cur["_match_score"]:
                    cl["_party_text"] = (ps or "").strip()
                    candidates[cl["id"]] = cl

        for cl in candidates.values():
            key = (cl["id"], case_no, date)
            if key in seen:
                continue
            seen.add(key)
            msg = _build_reminder_message(
                client_name=cl["name"], case_number=case_no, parties=parties_text,
                hearing_date=date, court_name=court, lawyer_name=lawyer, language=lang,
            )
            phone = cl.get("phone") or ""
            out.append({
                "client_id": cl["id"],
                "client_name": cl["name"],
                "phone": phone,
                "has_phone": bool(phone),
                "matched_on": cl.get("_party_text", ""),
                "match_score": cl.get("_match_score", 0),
                "parties": parties_text,
                "case_number": case_no,
                "date": date,
                "court": court,
                "list_type": m.get("listType") or "",
                "message": msg,
                "link": f"https://wa.me/{phone}?text={urllib.parse.quote(msg)}" if phone else None,
            })

    out.sort(key=lambda r: (not r["has_phone"], -r["match_score"]))
    return _ok(out, matters_in=len(matters), contacts=len(db.list_clients()))


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
    # Bind to 0.0.0.0 when running in a deployed environment (Render injects PORT).
    # Locally, stay on localhost.
    is_deployed = bool(os.getenv("PORT") or os.getenv("RENDER"))
    host = "0.0.0.0" if is_deployed else "localhost"
    print(f"\n  Maharashtra Courts → http://{host}:{PORT}\n")
    app.run(host=host, port=PORT, debug=not is_deployed)
