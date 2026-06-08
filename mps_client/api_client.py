"""
Thin async HTTP + WebSocket client for mps_server.
All calls go to http://localhost:8000 (LAN only -- never internet).
"""
import json
import asyncio
from typing import AsyncIterator, Optional, Callable

import httpx
import websockets

SERVER    = "http://127.0.0.1:8000"
WS_SERVER = "ws://127.0.0.1:8000"


class AuthState:
    def __init__(self):
        self.token     = ""
        self.role      = ""
        self.full_name = ""
        self.user_id   = ""

    @property
    def is_authenticated(self):
        return bool(self.token)

    def clear(self):
        self.token = self.role = self.full_name = self.user_id = ""


auth = AuthState()   # module-level singleton


class APIError(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail
        super().__init__(f"HTTP {status}: {detail}")


def _headers():
    h = {"Content-Type": "application/json"}
    if auth.token:
        h["Authorization"] = f"Bearer {auth.token}"
    return h


# Auth
async def login(username, password):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(
            f"{SERVER}/auth/login",
            data={"username": username, "password": password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if r.status_code != 200:
        raise APIError(r.status_code, r.json().get("detail", r.text))
    data = r.json()
    auth.token     = data["access_token"]
    auth.role      = data["role"]
    auth.full_name = data["full_name"]
    auth.user_id   = data["user_id"]


async def logout():
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(f"{SERVER}/auth/logout", headers=_headers())
    except Exception:
        pass
    auth.clear()


# Sessions
async def get_current_session():
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.get(f"{SERVER}/sessions/current", headers=_headers())
    if r.status_code != 200:
        return None
    return r.json().get("session")


# Residents
async def search_residents(query):
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.get(f"{SERVER}/residents/search", params={"q": query}, headers=_headers())
    return r.json() if r.status_code == 200 else []


async def create_resident(name, nric_masked, contact):
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.post(
            f"{SERVER}/residents/",
            json={"name": name, "nric_masked": nric_masked, "contact": contact},
            headers=_headers(),
        )
    if r.status_code not in (200, 201):
        raise APIError(r.status_code, r.json().get("detail", r.text))
    return r.json()


async def get_resident_history(resident_id):
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.get(f"{SERVER}/residents/{resident_id}/history", headers=_headers())
    return r.json() if r.status_code == 200 else []


# Cases
async def get_my_cases():
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.get(f"{SERVER}/cases/mine", headers=_headers())
    return r.json().get("cases", []) if r.status_code == 200 else []


async def create_case(session_id, resident_id, case_type, agency,
                      urgency="normal", parent_case_id=None, is_new_issue=True):
    payload = {
        "session_id": session_id,
        "resident_id": resident_id,
        "case_type": case_type,
        "agency": agency,
        "urgency": urgency,
        "parent_case_id": parent_case_id,
        "is_new_issue": is_new_issue,
    }
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.post(f"{SERVER}/cases/", json=payload, headers=_headers())
    if r.status_code not in (200, 201):
        raise APIError(r.status_code, r.json().get("detail", r.text))
    return r.json()


async def submit_case(case_id):
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.post(f"{SERVER}/cases/{case_id}/submit", headers=_headers())
    if r.status_code != 200:
        raise APIError(r.status_code, r.json().get("detail", r.text))
    return r.json()


# Letters
async def get_letter(letter_id):
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.get(f"{SERVER}/letters/{letter_id}", headers=_headers())
    if r.status_code != 200:
        raise APIError(r.status_code, r.json().get("detail", r.text))
    return r.json()


async def update_letter(letter_id, content):
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.put(
            f"{SERVER}/letters/{letter_id}",
            json={"draft_content": content},
            headers=_headers(),
        )
    if r.status_code != 200:
        raise APIError(r.status_code, r.json().get("detail", r.text))
    return r.json()


async def stream_draft(case_id, notes, is_reappeal, rejection_reason,
                       previous_letter_id, on_chunk, on_queue, on_done, on_error):
    uri = f"{WS_SERVER}/letters/ws/draft?token={auth.token}"
    try:
        async with websockets.connect(uri, ping_interval=20) as ws:
            await ws.send(json.dumps({
                "case_id": case_id,
                "notes": notes,
                "is_reappeal": is_reappeal,
                "rejection_reason": rejection_reason,
                "previous_letter_id": previous_letter_id,
            }))
            async for raw in ws:
                msg = json.loads(raw)
                t = msg.get("type")
                if t == "queue_status":
                    on_queue(msg.get("position", 0))
                elif t == "chunk":
                    on_chunk(msg.get("text", ""))
                elif t == "done":
                    on_done(msg.get("letter_id", 0))
                    break
                elif t == "error":
                    on_error(msg.get("message", "Unknown error"))
                    break
    except Exception as exc:
        on_error(str(exc))


async def stream_qa(question, on_chunk, on_done, on_error):
    uri = f"{WS_SERVER}/letters/ws/qa?token={auth.token}"
    try:
        async with websockets.connect(uri, ping_interval=20) as ws:
            await ws.send(json.dumps({"question": question}))
            async for raw in ws:
                msg = json.loads(raw)
                t = msg.get("type")
                if t == "chunk":
                    on_chunk(msg.get("text", ""))
                elif t == "done":
                    on_done()
                    break
                elif t == "error":
                    on_error(msg.get("message", "Unknown error"))
                    break
    except Exception as exc:
        on_error(str(exc))


# Vetter actions
async def get_vetter_queue():
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.get(f"{SERVER}/cases/queue", headers=_headers())
    return r.json().get("cases", []) if r.status_code == 200 else []


async def vetter_submit(case_id, final_content):
    """Vetter has edited the final text and submits it for MP's final check."""
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.post(
            f"{SERVER}/cases/{case_id}/vetter-submit",
            json={"final_content": final_content},
            headers=_headers(),
        )
    if r.status_code != 200:
        raise APIError(r.status_code, r.json().get("detail", r.text))
    return r.json()


async def vetter_return(case_id, comment):
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.post(
            f"{SERVER}/cases/{case_id}/vetter-return",
            json={"comment": comment},
            headers=_headers(),
        )
    if r.status_code != 200:
        raise APIError(r.status_code, r.json().get("detail", r.text))
    return r.json()

async def signup(username: str, password: str, full_name: str) -> dict:
    """Public registration — creates a volunteer account."""
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.post(
            f"{SERVER}/auth/signup",
            json={"username": username, "password": password, "full_name": full_name},
        )
        if r.status_code not in (200, 201):
            detail = r.json().get("detail", r.text)
            raise Exception(detail)
        return r.json()


async def change_password(current_password: str, new_password: str) -> dict:
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.put(
            f"{SERVER}/auth/change-password",
            json={"current_password": current_password, "new_password": new_password},
            headers=_headers(),
        )
        if r.status_code != 200:
            raise Exception(r.json().get("detail", r.text))
        return r.json()


async def change_username(current_password: str, new_username: str) -> dict:
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.put(
            f"{SERVER}/auth/change-username",
            json={"current_password": current_password, "new_username": new_username},
            headers=_headers(),
        )
        if r.status_code != 200:
            raise Exception(r.json().get("detail", r.text))
        return r.json()
