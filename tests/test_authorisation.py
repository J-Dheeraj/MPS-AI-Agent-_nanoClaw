from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mps_server.auth import create_token
from mps_server.database import Base, Case, Letter, Resident, RevokedToken, Session, User, get_db
from mps_server.routers.letters_router import router


def build_test_app():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    db = session_factory()

    volunteer_a = User(
        id="volunteer-a",
        username="volunteer-a",
        hashed_pw="unused",
        role="volunteer",
        full_name="Volunteer A",
        is_active=True,
    )
    volunteer_b = User(
        id="volunteer-b",
        username="volunteer-b",
        hashed_pw="unused",
        role="volunteer",
        full_name="Volunteer B",
        is_active=True,
    )
    session = Session(id="session-1", date="2026-06-10", status="open")
    resident = Resident(id="resident-1", name="Resident", nric_masked="S****567A")
    case = Case(
        id="case-a",
        session_id=session.id,
        resident_id=resident.id,
        case_type="appeal",
        agency="HDB",
        status="assigned",
        volunteer_id=volunteer_a.id,
        notes="A housing appeal.",
    )
    letter = Letter(id="letter-a", case_id=case.id, draft_content="Draft")
    db.add_all([volunteer_a, volunteer_b, session, resident, case, letter])
    db.commit()

    app = FastAPI()
    app.include_router(router)

    def override_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    return TestClient(app), db


def token_for(user_id: str, role: str) -> str:
    return create_token({"sub": user_id, "role": role})


def test_rest_letter_read_is_scoped_to_assigned_volunteer():
    client, _ = build_test_app()
    response = client.get(
        "/letters/letter-a",
        headers={"Authorization": f"Bearer {token_for('volunteer-b', 'volunteer')}"},
    )
    assert response.status_code == 404


def test_websocket_rejects_cross_case_drafting():
    client, _ = build_test_app()
    with client.websocket_connect("/letters/ws/draft") as websocket:
        websocket.send_json(
            {"type": "auth", "token": token_for("volunteer-b", "volunteer")}
        )
        assert websocket.receive_json()["type"] == "authenticated"
        websocket.send_json({"case_id": "case-a", "is_reappeal": False})
        assert websocket.receive_json() == {"type": "error", "text": "Case not found"}


def test_websocket_rejects_revoked_token():
    client, db = build_test_app()
    token = token_for("volunteer-a", "volunteer")
    from mps_server.auth import decode_token

    db.add(RevokedToken(jti=decode_token(token)["jti"], user_id="volunteer-a"))
    db.commit()
    with client.websocket_connect("/letters/ws/draft") as websocket:
        websocket.send_json({"type": "auth", "token": token})
        assert websocket.receive_json() == {"type": "error", "text": "Unauthorised"}
