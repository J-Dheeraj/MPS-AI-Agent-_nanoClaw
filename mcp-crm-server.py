#!/usr/bin/env python3
"""
MPS CRM Bridge — MCP Server
============================
Connects NanoClaw to your MPS case management system via the
Model Context Protocol (MCP). Supports five backends:

  CRM_BACKEND=sqlite        Local SQLite file (default — no infrastructure needed)
  CRM_BACKEND=google_sheets Google Sheets spreadsheet
  CRM_BACKEND=rest_api      Any REST API (generic JSON)
  CRM_BACKEND=sharepoint    Microsoft SharePoint / SharePoint Online lists
  CRM_BACKEND=csv           Plain CSV files (read-only, for legacy exports)

Set the backend and its credentials in .env (see bottom of this file
for the full .env reference). Then wire this server into NanoClaw's
mcp_servers list in nanoclaw.yaml.

Install:
  pip install fastmcp python-dotenv requests gspread oauth2client \
              Office365-REST-Python-Client

Run:
  python mcp-crm-server.py            # stdio mode (default)
  python mcp-crm-server.py --http     # HTTP mode on MCP_PORT (default 8000)
"""

import os
import sys
import json
import logging
import sqlite3
import datetime
import csv
import io
from pathlib import Path
from typing import Any, Optional
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MPS-CRM] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("mps-crm")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BACKEND = os.getenv("CRM_BACKEND", "sqlite").lower().strip()
DATA_DIR = Path(os.getenv("CRM_DATA_DIR", "~/nanoclaw/crm-data")).expanduser()
DATA_DIR.mkdir(parents=True, exist_ok=True)

# SQLite
SQLITE_PATH = DATA_DIR / os.getenv("CRM_SQLITE_FILE", "mps-cases.db")

# Google Sheets
GSHEET_SPREADSHEET_ID   = os.getenv("CRM_GSHEET_ID", "")
GSHEET_CREDENTIALS_JSON = os.getenv("CRM_GSHEET_CREDENTIALS", str(DATA_DIR / "gsheet-credentials.json"))

# REST API
REST_BASE_URL   = os.getenv("CRM_REST_BASE_URL", "")
REST_API_KEY    = os.getenv("CRM_REST_API_KEY", "")
REST_API_HEADER = os.getenv("CRM_REST_API_HEADER", "X-API-Key")

# SharePoint
SP_SITE_URL      = os.getenv("CRM_SP_SITE_URL", "")
SP_CLIENT_ID     = os.getenv("CRM_SP_CLIENT_ID", "")
SP_CLIENT_SECRET = os.getenv("CRM_SP_CLIENT_SECRET", "")
SP_LIST_NAME     = os.getenv("CRM_SP_LIST_NAME", "MPS Cases")

# CSV
CSV_CASES_PATH   = Path(os.getenv("CRM_CSV_CASES",   str(DATA_DIR / "cases.csv")))
CSV_LETTERS_PATH = Path(os.getenv("CRM_CSV_LETTERS", str(DATA_DIR / "letters.csv")))

# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

try:
    from fastmcp import FastMCP
except ImportError:
    print(
        "ERROR: fastmcp not installed. Run:  pip install fastmcp",
        file=sys.stderr,
    )
    sys.exit(1)

mcp = FastMCP("mps-crm-bridge")

# ---------------------------------------------------------------------------
# Backend: SQLite (default)
# ---------------------------------------------------------------------------

def _sqlite_init():
    """Create tables if they do not exist."""
    con = sqlite3.connect(SQLITE_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS constituents (
            nric        TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            address     TEXT,
            phone       TEXT,
            email       TEXT,
            notes       TEXT,
            created_at  TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS cases (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            constituent_nric TEXT NOT NULL,
            issue_type       TEXT NOT NULL,
            agency           TEXT NOT NULL,
            summary          TEXT NOT NULL,
            urgency          TEXT DEFAULT 'normal',
            status           TEXT DEFAULT 'open',
            volunteer_name   TEXT,
            created_at       TEXT DEFAULT (datetime('now','localtime')),
            updated_at       TEXT DEFAULT (datetime('now','localtime')),
            reply_received   INTEGER DEFAULT 0,
            reply_date       TEXT,
            reply_notes      TEXT,
            FOREIGN KEY(constituent_nric) REFERENCES constituents(nric)
        );

        CREATE TABLE IF NOT EXISTS letters (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id      INTEGER NOT NULL,
            letter_text  TEXT NOT NULL,
            addressed_to TEXT NOT NULL,
            letter_date  TEXT NOT NULL,
            created_at   TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(case_id) REFERENCES cases(id)
        );
    """)
    con.commit()
    return con


def _sqlite_lookup_constituent(nric: str = "", name: str = "") -> dict:
    con = _sqlite_init()
    cur = con.cursor()
    if nric:
        cur.execute("SELECT * FROM constituents WHERE nric = ?", (nric.upper(),))
    elif name:
        cur.execute("SELECT * FROM constituents WHERE name LIKE ?", (f"%{name}%",))
    else:
        return {"error": "Provide nric or name."}
    row = cur.fetchone()
    if not row:
        return {"found": False, "message": "Constituent not found in database."}
    constituent = dict(row)
    cur.execute(
        "SELECT * FROM cases WHERE constituent_nric = ? ORDER BY created_at DESC",
        (constituent["nric"],),
    )
    constituent["cases"] = [dict(r) for r in cur.fetchall()]
    for case in constituent["cases"]:
        cur.execute(
            "SELECT * FROM letters WHERE case_id = ? ORDER BY created_at DESC",
            (case["id"],),
        )
        case["letters"] = [dict(r) for r in cur.fetchall()]
    constituent["found"] = True
    con.close()
    return constituent


def _sqlite_create_case(
    constituent_nric: str,
    issue_type: str,
    agency: str,
    summary: str,
    urgency: str,
    volunteer_name: str,
) -> dict:
    con = _sqlite_init()
    cur = con.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO constituents (nric, name) VALUES (?, ?)",
        (constituent_nric.upper(), constituent_nric.upper()),
    )
    cur.execute(
        """INSERT INTO cases
           (constituent_nric, issue_type, agency, summary, urgency, volunteer_name)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (constituent_nric.upper(), issue_type, agency, summary, urgency, volunteer_name),
    )
    case_id = cur.lastrowid
    con.commit()
    con.close()
    return {"success": True, "case_id": case_id, "message": f"Case #{case_id} created."}


def _sqlite_attach_letter(
    case_id: int,
    letter_text: str,
    addressed_to: str,
    letter_date: str,
) -> dict:
    con = _sqlite_init()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO letters (case_id, letter_text, addressed_to, letter_date) VALUES (?, ?, ?, ?)",
        (case_id, letter_text, addressed_to, letter_date),
    )
    letter_id = cur.lastrowid
    cur.execute(
        "UPDATE cases SET updated_at = datetime('now','localtime') WHERE id = ?",
        (case_id,),
    )
    con.commit()
    con.close()
    return {"success": True, "letter_id": letter_id}


def _sqlite_update_case_status(
    case_id: int,
    status: str,
    notes: str,
    reply_received: bool,
) -> dict:
    con = _sqlite_init()
    cur = con.cursor()
    cur.execute(
        """UPDATE cases SET
           status = ?,
           reply_notes = ?,
           reply_received = ?,
           reply_date = CASE WHEN ? THEN datetime('now','localtime') ELSE reply_date END,
           updated_at = datetime('now','localtime')
           WHERE id = ?""",
        (status, notes, int(reply_received), int(reply_received), case_id),
    )
    con.commit()
    con.close()
    return {"success": True, "case_id": case_id, "new_status": status}


def _sqlite_get_pending_cases(days_overdue: int = 21) -> list:
    con = _sqlite_init()
    cur = con.cursor()
    cur.execute(
        """SELECT c.id, c.constituent_nric, c.issue_type, c.agency, c.summary,
                  c.urgency, c.volunteer_name, c.created_at,
                  julianday('now') - julianday(c.created_at) AS days_open
           FROM cases c
           WHERE c.status = 'open'
             AND c.reply_received = 0
             AND julianday('now') - julianday(c.created_at) >= ?
           ORDER BY days_open DESC""",
        (days_overdue,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows


def _sqlite_get_todays_queue() -> list:
    today = datetime.date.today().isoformat()
    con = _sqlite_init()
    cur = con.cursor()
    cur.execute(
        """SELECT c.*, co.name AS constituent_name, co.phone, co.address
           FROM cases c
           LEFT JOIN constituents co ON c.constituent_nric = co.nric
           WHERE date(c.created_at) = ?
           ORDER BY
             CASE c.urgency WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 ELSE 3 END,
             c.id""",
        (today,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows


# ---------------------------------------------------------------------------
# Backend: Google Sheets
# ---------------------------------------------------------------------------

def _gsheets_client():
    try:
        import gspread
        from oauth2client.service_account import ServiceAccountCredentials
    except ImportError:
        raise RuntimeError("Install gspread and oauth2client: pip install gspread oauth2client")
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(GSHEET_CREDENTIALS_JSON, scope)
    return gspread.authorize(creds)


def _gsheets_ensure_sheets(client):
    """Create worksheets if they don't exist."""
    ss = client.open_by_key(GSHEET_SPREADSHEET_ID)
    existing = [ws.title for ws in ss.worksheets()]
    if "Cases" not in existing:
        ws = ss.add_worksheet("Cases", rows=1000, cols=20)
        ws.append_row([
            "Case ID", "Constituent NRIC", "Issue Type", "Agency", "Summary",
            "Urgency", "Status", "Volunteer", "Created At", "Updated At",
            "Reply Received", "Reply Date", "Reply Notes",
        ])
    if "Constituents" not in existing:
        ws = ss.add_worksheet("Constituents", rows=1000, cols=10)
        ws.append_row(["NRIC", "Name", "Address", "Phone", "Email", "Notes", "Created At"])
    if "Letters" not in existing:
        ws = ss.add_worksheet("Letters", rows=1000, cols=8)
        ws.append_row(["Letter ID", "Case ID", "Addressed To", "Letter Date", "Created At", "Letter Text"])
    return ss


def _gsheets_lookup_constituent(nric: str = "", name: str = "") -> dict:
    client = _gsheets_client()
    ss = _gsheets_ensure_sheets(client)
    ws = ss.worksheet("Constituents")
    records = ws.get_all_records()
    match = None
    for r in records:
        if nric and str(r.get("NRIC", "")).upper() == nric.upper():
            match = r; break
        if name and name.lower() in str(r.get("Name", "")).lower():
            match = r; break
    if not match:
        return {"found": False, "message": "Constituent not found."}
    cases_ws = ss.worksheet("Cases")
    cases = [
        c for c in cases_ws.get_all_records()
        if str(c.get("Constituent NRIC", "")).upper() == str(match["NRIC"]).upper()
    ]
    match["cases"] = cases
    match["found"] = True
    return match


def _gsheets_create_case(constituent_nric, issue_type, agency, summary, urgency, volunteer_name) -> dict:
    client = _gsheets_client()
    ss = _gsheets_ensure_sheets(client)
    ws = ss.worksheet("Cases")
    all_rows = ws.get_all_values()
    case_id = len(all_rows)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    ws.append_row([
        case_id, constituent_nric.upper(), issue_type, agency, summary,
        urgency, "open", volunteer_name, now, now, "No", "", "",
    ])
    c_ws = ss.worksheet("Constituents")
    existing_nrics = [str(r.get("NRIC", "")).upper() for r in c_ws.get_all_records()]
    if constituent_nric.upper() not in existing_nrics:
        c_ws.append_row([constituent_nric.upper(), "", "", "", "", "", now])
    return {"success": True, "case_id": case_id}


def _gsheets_attach_letter(case_id, letter_text, addressed_to, letter_date) -> dict:
    client = _gsheets_client()
    ss = _gsheets_ensure_sheets(client)
    ws = ss.worksheet("Letters")
    letter_id = len(ws.get_all_values())
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    ws.append_row([letter_id, case_id, addressed_to, letter_date, now, letter_text])
    return {"success": True, "letter_id": letter_id}


def _gsheets_update_case_status(case_id, status, notes, reply_received) -> dict:
    client = _gsheets_client()
    ss = _gsheets_ensure_sheets(client)
    ws = ss.worksheet("Cases")
    records = ws.get_all_records()
    header = ws.row_values(1)
    for i, r in enumerate(records, start=2):
        if str(r.get("Case ID")) == str(case_id):
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            ws.update_cell(i, header.index("Status") + 1, status)
            ws.update_cell(i, header.index("Reply Notes") + 1, notes)
            ws.update_cell(i, header.index("Updated At") + 1, now)
            ws.update_cell(i, header.index("Reply Received") + 1, "Yes" if reply_received else "No")
            if reply_received:
                ws.update_cell(i, header.index("Reply Date") + 1, now)
            return {"success": True, "case_id": case_id, "new_status": status}
    return {"error": f"Case {case_id} not found."}


def _gsheets_get_pending_cases(days_overdue=21) -> list:
    client = _gsheets_client()
    ss = _gsheets_ensure_sheets(client)
    ws = ss.worksheet("Cases")
    records = ws.get_all_records()
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days_overdue)
    result = []
    for r in records:
        if r.get("Status") != "open" or r.get("Reply Received") == "Yes":
            continue
        try:
            created = datetime.datetime.strptime(str(r["Created At"])[:16], "%Y-%m-%d %H:%M")
            if created <= cutoff:
                r["days_open"] = (datetime.datetime.now() - created).days
                result.append(r)
        except Exception:
            pass
    return sorted(result, key=lambda x: x.get("days_open", 0), reverse=True)


def _gsheets_get_todays_queue() -> list:
    client = _gsheets_client()
    ss = _gsheets_ensure_sheets(client)
    ws = ss.worksheet("Cases")
    today = datetime.date.today().strftime("%Y-%m-%d")
    records = ws.get_all_records()
    result = [r for r in records if str(r.get("Created At", "")).startswith(today)]
    urgency_order = {"urgent": 0, "high": 1, "normal": 2}
    return sorted(result, key=lambda r: urgency_order.get(str(r.get("Urgency", "normal")).lower(), 2))


# ---------------------------------------------------------------------------
# Backend: REST API
# ---------------------------------------------------------------------------

def _rest_get(path: str, params: dict = None) -> Any:
    import requests
    url = REST_BASE_URL.rstrip("/") + "/" + path.lstrip("/")
    headers = {REST_API_HEADER: REST_API_KEY, "Content-Type": "application/json"}
    r = requests.get(url, headers=headers, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def _rest_post(path: str, data: dict) -> Any:
    import requests
    url = REST_BASE_URL.rstrip("/") + "/" + path.lstrip("/")
    headers = {REST_API_HEADER: REST_API_KEY, "Content-Type": "application/json"}
    r = requests.post(url, headers=headers, json=data, timeout=15)
    r.raise_for_status()
    return r.json()


def _rest_patch(path: str, data: dict) -> Any:
    import requests
    url = REST_BASE_URL.rstrip("/") + "/" + path.lstrip("/")
    headers = {REST_API_HEADER: REST_API_KEY, "Content-Type": "application/json"}
    r = requests.patch(url, headers=headers, json=data, timeout=15)
    r.raise_for_status()
    return r.json()


def _rest_lookup_constituent(nric="", name="") -> dict:
    try:
        if nric:
            result = _rest_get(f"constituents/{nric.upper()}")
        else:
            results = _rest_get("constituents", {"name": name})
            result = results[0] if results else None
        if not result:
            return {"found": False, "message": "Not found."}
        result["cases"] = _rest_get(f"constituents/{result.get('nric', nric)}/cases")
        result["found"] = True
        return result
    except Exception as e:
        return {"error": str(e)}


def _rest_create_case(constituent_nric, issue_type, agency, summary, urgency, volunteer_name) -> dict:
    try:
        return _rest_post("cases", {
            "constituent_nric": constituent_nric.upper(),
            "issue_type": issue_type, "agency": agency, "summary": summary,
            "urgency": urgency, "volunteer_name": volunteer_name,
        })
    except Exception as e:
        return {"error": str(e)}


def _rest_attach_letter(case_id, letter_text, addressed_to, letter_date) -> dict:
    try:
        return _rest_post(f"cases/{case_id}/letters", {
            "letter_text": letter_text,
            "addressed_to": addressed_to,
            "letter_date": letter_date,
        })
    except Exception as e:
        return {"error": str(e)}


def _rest_update_case_status(case_id, status, notes, reply_received) -> dict:
    try:
        return _rest_patch(f"cases/{case_id}", {
            "status": status, "reply_notes": notes,
            "reply_received": reply_received,
            "reply_date": datetime.date.today().isoformat() if reply_received else None,
        })
    except Exception as e:
        return {"error": str(e)}


def _rest_get_pending_cases(days_overdue=21) -> list:
    try:
        return _rest_get("cases", {"status": "open", "days_overdue": days_overdue})
    except Exception as e:
        return [{"error": str(e)}]


def _rest_get_todays_queue() -> list:
    try:
        return _rest_get("cases", {"date": datetime.date.today().isoformat()})
    except Exception as e:
        return [{"error": str(e)}]


# ---------------------------------------------------------------------------
# Backend: SharePoint
# ---------------------------------------------------------------------------

def _sp_client():
    try:
        from office365.runtime.auth.client_credential import ClientCredential
        from office365.sharepoint.client_context import ClientContext
    except ImportError:
        raise RuntimeError("Install Office365-REST-Python-Client: pip install Office365-REST-Python-Client")
    ctx = ClientContext(SP_SITE_URL).with_credentials(
        ClientCredential(SP_CLIENT_ID, SP_CLIENT_SECRET)
    )
    return ctx


def _sp_list_items(ctx, list_name: str, filter_str: str = None) -> list:
    lst = ctx.web.lists.get_by_title(list_name)
    items = lst.items.filter(filter_str) if filter_str else lst.items
    ctx.load(items)
    ctx.execute_query()
    return [item.properties for item in items]


def _sp_lookup_constituent(nric="", name="") -> dict:
    try:
        ctx = _sp_client()
        if nric:
            rows = _sp_list_items(ctx, "Constituents", f"NRIC eq '{nric.upper()}'")
        else:
            rows = _sp_list_items(ctx, "Constituents", f"substringof('{name}', Name)")
        if not rows:
            return {"found": False, "message": "Not found."}
        constituent = rows[0]
        constituent["cases"] = _sp_list_items(
            ctx, SP_LIST_NAME, f"ConstituentNRIC eq '{constituent.get('NRIC', '')}'"
        )
        constituent["found"] = True
        return constituent
    except Exception as e:
        return {"error": str(e)}


def _sp_create_case(constituent_nric, issue_type, agency, summary, urgency, volunteer_name) -> dict:
    try:
        ctx = _sp_client()
        lst = ctx.web.lists.get_by_title(SP_LIST_NAME)
        item = lst.add_item({
            "ConstituentNRIC": constituent_nric.upper(),
            "IssueType": issue_type, "Agency": agency, "Summary": summary,
            "Urgency": urgency, "Status": "open", "VolunteerName": volunteer_name,
            "CreatedAt": datetime.datetime.now().isoformat(),
        })
        ctx.execute_query()
        return {"success": True, "case_id": item.properties.get("Id")}
    except Exception as e:
        return {"error": str(e)}


def _sp_attach_letter(case_id, letter_text, addressed_to, letter_date) -> dict:
    try:
        ctx = _sp_client()
        lst = ctx.web.lists.get_by_title("Letters")
        item = lst.add_item({
            "CaseID": case_id, "LetterText": letter_text,
            "AddressedTo": addressed_to, "LetterDate": letter_date,
        })
        ctx.execute_query()
        return {"success": True, "letter_id": item.properties.get("Id")}
    except Exception as e:
        return {"error": str(e)}


def _sp_update_case_status(case_id, status, notes, reply_received) -> dict:
    try:
        ctx = _sp_client()
        lst = ctx.web.lists.get_by_title(SP_LIST_NAME)
        item = lst.get_item_by_id(case_id)
        item.set_property("Status", status)
        item.set_property("ReplyNotes", notes)
        item.set_property("ReplyReceived", reply_received)
        if reply_received:
            item.set_property("ReplyDate", datetime.date.today().isoformat())
        item.update()
        ctx.execute_query()
        return {"success": True, "case_id": case_id, "new_status": status}
    except Exception as e:
        return {"error": str(e)}


def _sp_get_pending_cases(days_overdue=21) -> list:
    try:
        ctx = _sp_client()
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=days_overdue)).isoformat()
        return _sp_list_items(ctx, SP_LIST_NAME, f"Status eq 'open' and CreatedAt le '{cutoff}'")
    except Exception as e:
        return [{"error": str(e)}]


def _sp_get_todays_queue() -> list:
    try:
        ctx = _sp_client()
        today = datetime.date.today().isoformat()
        return _sp_list_items(ctx, SP_LIST_NAME, f"startswith(CreatedAt, '{today}')")
    except Exception as e:
        return [{"error": str(e)}]


# ---------------------------------------------------------------------------
# Backend: CSV (read-only — for legacy exports)
# ---------------------------------------------------------------------------

def _csv_read(path: Path) -> list:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _csv_lookup_constituent(nric="", name="") -> dict:
    rows = _csv_read(CSV_CASES_PATH)
    match = None
    for r in rows:
        if nric and str(r.get("nric", r.get("NRIC", ""))).upper() == nric.upper():
            match = r; break
        if name and name.lower() in str(r.get("name", r.get("Name", ""))).lower():
            match = r; break
    if not match:
        return {"found": False, "message": "Not found in CSV export."}
    match["found"] = True
    match["_note"] = "CSV backend is read-only. Updates not persisted."
    return match


def _csv_get_pending_cases(days_overdue=21) -> list:
    rows = _csv_read(CSV_CASES_PATH)
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days_overdue)
    result = []
    for r in rows:
        if str(r.get("status", r.get("Status", ""))).lower() != "open":
            continue
        created_str = r.get("created_at", r.get("Created At", ""))
        try:
            created = datetime.datetime.fromisoformat(created_str[:16])
            if created <= cutoff:
                r["days_open"] = (datetime.datetime.now() - created).days
                result.append(r)
        except Exception:
            pass
    return sorted(result, key=lambda x: x.get("days_open", 0), reverse=True)


def _csv_get_todays_queue() -> list:
    rows = _csv_read(CSV_CASES_PATH)
    today = datetime.date.today().isoformat()
    return [r for r in rows if str(r.get("created_at", r.get("Created At", ""))).startswith(today)]


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_BACKENDS = {
    "sqlite": {
        "lookup_constituent": _sqlite_lookup_constituent,
        "create_case":        _sqlite_create_case,
        "attach_letter":      _sqlite_attach_letter,
        "update_case_status": _sqlite_update_case_status,
        "get_pending_cases":  _sqlite_get_pending_cases,
        "get_todays_queue":   _sqlite_get_todays_queue,
    },
    "google_sheets": {
        "lookup_constituent": _gsheets_lookup_constituent,
        "create_case":        _gsheets_create_case,
        "attach_letter":      _gsheets_attach_letter,
        "update_case_status": _gsheets_update_case_status,
        "get_pending_cases":  _gsheets_get_pending_cases,
        "get_todays_queue":   _gsheets_get_todays_queue,
    },
    "rest_api": {
        "lookup_constituent": _rest_lookup_constituent,
        "create_case":        _rest_create_case,
        "attach_letter":      _rest_attach_letter,
        "update_case_status": _rest_update_case_status,
        "get_pending_cases":  _rest_get_pending_cases,
        "get_todays_queue":   _rest_get_todays_queue,
    },
    "sharepoint": {
        "lookup_constituent": _sp_lookup_constituent,
        "create_case":        _sp_create_case,
        "attach_letter":      _sp_attach_letter,
        "update_case_status": _sp_update_case_status,
        "get_pending_cases":  _sp_get_pending_cases,
        "get_todays_queue":   _sp_get_todays_queue,
    },
    "csv": {
        "lookup_constituent": _csv_lookup_constituent,
        "create_case":        lambda *a, **kw: {"error": "CSV backend is read-only."},
        "attach_letter":      lambda *a, **kw: {"error": "CSV backend is read-only."},
        "update_case_status": lambda *a, **kw: {"error": "CSV backend is read-only."},
        "get_pending_cases":  _csv_get_pending_cases,
        "get_todays_queue":   _csv_get_todays_queue,
    },
}

if BACKEND not in _BACKENDS:
    log.error("Unknown CRM_BACKEND: %s. Choose from: %s", BACKEND, ", ".join(_BACKENDS))
    sys.exit(1)

_fn = _BACKENDS[BACKEND]
log.info("MPS CRM Bridge starting — backend: %s", BACKEND.upper())

# ---------------------------------------------------------------------------
# MCP Tool definitions
# ---------------------------------------------------------------------------

@mcp.tool()
def lookup_constituent(
    nric: str = "",
    name: str = "",
) -> dict:
    """
    Look up a constituent by NRIC or name. Returns their profile and all
    previous MPS cases with letters attached. Use this BEFORE the MP meets
    a constituent — it gives the full case history for context.

    Parameters:
      nric  — Singapore NRIC (e.g. S1234567A). Preferred over name.
      name  — Full or partial name. Used if NRIC not available.

    Returns a dict with constituent fields + 'cases' list. Each case contains
    a 'letters' list. Returns {"found": false} if not in the system.
    """
    log.info("lookup_constituent nric=%s name=%s", nric or "-", name or "-")
    if not nric and not name:
        return {"error": "Provide nric or name."}
    return _fn["lookup_constituent"](nric=nric, name=name)


@mcp.tool()
def create_case(
    constituent_nric: str,
    issue_type: str,
    agency: str,
    summary: str,
    urgency: str = "normal",
    volunteer_name: str = "",
) -> dict:
    """
    Create a new MPS case for a constituent. Call this once the MP has
    heard the constituent's problem and decided on a course of action.

    Parameters:
      constituent_nric — NRIC of the constituent (required)
      issue_type       — Short category. Examples:
                           "HDB appeal", "ComCare SMTA", "CPF withdrawal",
                           "CHAS card", "MediFund", "PR appeal",
                           "Salary dispute", "GST Voucher", "School transfer"
      agency           — Target agency. Examples: "HDB", "MSF", "CPF",
                           "MOH", "MOM", "ICA", "IRAS", "MOE", "LTA"
      summary          — One paragraph describing the issue and what action
                           the MP is taking
      urgency          — "urgent" | "high" | "normal" (default "normal")
      volunteer_name   — Name of the volunteer who handled the intake

    Returns {"success": true, "case_id": <id>}
    """
    log.info("create_case nric=%s type=%s agency=%s urgency=%s", constituent_nric, issue_type, agency, urgency)
    return _fn["create_case"](constituent_nric, issue_type, agency, summary, urgency, volunteer_name)


@mcp.tool()
def attach_letter(
    case_id: int,
    letter_text: str,
    addressed_to: str,
    letter_date: str = "",
) -> dict:
    """
    Attach a completed MP appeal letter to an existing case. Call this
    immediately after the letter has been drafted and approved.

    Parameters:
      case_id       — Case ID returned by create_case
      letter_text   — Full text of the letter (header, body, sign-off)
      addressed_to  — Addressee. Examples: "Director, HDB Branch",
                        "Chief Executive, CPF Board"
      letter_date   — Date on the letter in YYYY-MM-DD format.
                        Defaults to today if not provided.

    Returns {"success": true, "letter_id": <id>}
    """
    if not letter_date:
        letter_date = datetime.date.today().isoformat()
    log.info("attach_letter case_id=%s to=%s date=%s", case_id, addressed_to, letter_date)
    return _fn["attach_letter"](case_id, letter_text, addressed_to, letter_date)


@mcp.tool()
def update_case_status(
    case_id: int,
    status: str,
    notes: str = "",
    reply_received: bool = False,
) -> dict:
    """
    Update the status of a case — typically when an agency reply arrives
    or when a case is resolved.

    Parameters:
      case_id        — Case ID to update
      status         — New status:
                         "open"      — still waiting for agency reply
                         "replied"   — agency has replied
                         "resolved"  — constituent issue resolved
                         "closed"    — closed without resolution
                         "escalated" — referred to higher authority
      notes          — Summary of the reply or reason for status change
      reply_received — Set True when an agency reply has been received

    Returns {"success": true, "case_id": <id>, "new_status": <status>}
    """
    log.info("update_case_status case_id=%s status=%s reply=%s", case_id, status, reply_received)
    return _fn["update_case_status"](case_id, status, notes, reply_received)


@mcp.tool()
def get_pending_cases(days_overdue: int = 21) -> list:
    """
    Return all open cases that have had no agency reply for N or more days.
    Used for the weekly follow-up digest and pre-MPS briefing.

    Parameters:
      days_overdue — Flag cases open for at least this many days (default 21)

    Returns a list of case dicts sorted by days open (longest first).
    """
    log.info("get_pending_cases days_overdue=%s", days_overdue)
    return _fn["get_pending_cases"](days_overdue)


@mcp.tool()
def get_todays_queue() -> list:
    """
    Return all cases created today, sorted by urgency (urgent first).
    Use this at the start of each MPS session to see tonight's queue.

    Returns a list of case dicts for today's session including constituent
    details, issue type, agency, urgency, and volunteer name.
    """
    log.info("get_todays_queue")
    return _fn["get_todays_queue"]()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--http" in sys.argv:
        port = int(os.getenv("MCP_PORT", "8000"))
        log.info("Starting HTTP mode on port %s", port)
        mcp.run(transport="http", host="0.0.0.0", port=port)
    else:
        log.info("Starting stdio mode")
        mcp.run(transport="stdio")


# ---------------------------------------------------------------------------
# .env reference — copy to ~/nanoclaw/.env and fill in your values
# ---------------------------------------------------------------------------
#
# # --- Which backend to use ---
# CRM_BACKEND=sqlite         # sqlite | google_sheets | rest_api | sharepoint | csv
#
# # --- Where CRM data files live ---
# CRM_DATA_DIR=~/nanoclaw/crm-data
#
# # --- SQLite (default, no extra setup) ---
# CRM_SQLITE_FILE=mps-cases.db
#
# # --- Google Sheets ---
# CRM_GSHEET_ID=<your-spreadsheet-id-from-the-URL>
# CRM_GSHEET_CREDENTIALS=~/nanoclaw/crm-data/gsheet-credentials.json
#   (Download from Google Cloud Console → Service Accounts → Keys → JSON)
#   Share the spreadsheet with the service account email address.
#
# # --- REST API ---
# CRM_REST_BASE_URL=https://your-crm-system.example.com/api/v1
# CRM_REST_API_KEY=your-api-key-here
# CRM_REST_API_HEADER=X-API-Key   # or Authorization, Bearer, etc.
#
# # --- SharePoint ---
# CRM_SP_SITE_URL=https://yourorg.sharepoint.com/sites/MPS
# CRM_SP_CLIENT_ID=<app-registration-client-id>
# CRM_SP_CLIENT_SECRET=<app-registration-client-secret>
# CRM_SP_LIST_NAME=MPS Cases
#
# # --- CSV (read-only — for importing legacy data) ---
# CRM_CSV_CASES=~/nanoclaw/crm-data/cases.csv
# CRM_CSV_LETTERS=~/nanoclaw/crm-data/letters.csv
#
# # --- HTTP transport port (optional) ---
# MCP_PORT=8000
