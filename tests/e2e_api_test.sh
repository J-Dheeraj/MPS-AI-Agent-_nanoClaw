#!/usr/bin/env bash
# End-to-end API test against the fixed mps_server.
set -u
B=http://127.0.0.1:8000
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "PASS: $1"; }
bad()  { FAIL=$((FAIL+1)); echo "FAIL: $1"; }

# 0. set known admin password for the test
python3 - << 'EOF'
import sqlite3
from passlib.context import CryptContext
ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
db = sqlite3.connect("/home/dheer/nanoclaw/mps_server/mps.db")
db.execute("UPDATE users SET hashed_pw=? WHERE username='admin'", (ctx.hash("TestAdmin#2026"),))
db.commit()
EOF

# 1. health
curl -sf $B/health > /dev/null && ok "health" || bad "health"

# 2. register WITHOUT auth must be rejected (401)
CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST $B/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"evil","password":"hackhack1","full_name":"x","role":"admin"}')
[ "$CODE" = "401" ] && ok "register unauthenticated -> 401" || bad "register unauth -> $CODE (want 401)"

# 3. admin login
TOKEN=$(curl -s -X POST $B/auth/login -d 'username=admin&password=TestAdmin#2026' | python3 -c 'import sys,json;print(json.load(sys.stdin).get("access_token",""))')
[ -n "$TOKEN" ] && ok "admin login" || { bad "admin login"; echo "ABORT"; exit 1; }
AH="Authorization: Bearer $TOKEN"

# 4. register volunteer + vetter as admin
curl -sf -X POST $B/auth/register -H "$AH" -H 'Content-Type: application/json' \
  -d '{"username":"vol1","password":"VolPass#2026","full_name":"Volunteer One","role":"volunteer"}' >/dev/null \
  && ok "register volunteer (as admin)" || bad "register volunteer"
curl -sf -X POST $B/auth/register -H "$AH" -H 'Content-Type: application/json' \
  -d '{"username":"vet1","password":"VetPass#2026","full_name":"Vetter One","role":"vetter"}' >/dev/null \
  && ok "register vetter (as admin)" || bad "register vetter"

# 5. register as VOLUNTEER must be 403
VTOKEN=$(curl -s -X POST $B/auth/login -d 'username=vol1&password=VolPass#2026' | python3 -c 'import sys,json;print(json.load(sys.stdin).get("access_token",""))')
VH="Authorization: Bearer $VTOKEN"
CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST $B/auth/register -H "$VH" -H 'Content-Type: application/json' \
  -d '{"username":"evil2","password":"hackhack1","full_name":"x","role":"admin"}')
[ "$CODE" = "403" ] && ok "register as volunteer -> 403" || bad "register as volunteer -> $CODE (want 403)"

# 6. open session
SID=$(curl -s -X POST $B/sessions/open -H "$AH" -H 'Content-Type: application/json' -d '{"date":"2026-06-10"}' | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("id") or d.get("session_id") or "")')
[ -n "$SID" ] && ok "session open ($SID)" || bad "session open"

# 7. GET /sessions/current
CUR=$(curl -s $B/sessions/current -H "$VH" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("id",""))')
[ "$CUR" = "$SID" ] && ok "GET /sessions/current" || bad "GET /sessions/current ($CUR != $SID)"

# 8. create resident (masked NRIC) as volunteer
RID=$(curl -s -X POST $B/residents/ -H "$VH" -H 'Content-Type: application/json' \
  -d '{"name":"Tan Ah Kow","nric_masked":"S****567A","contact":"91234567"}' | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("id",""))')
[ -n "$RID" ] && ok "create resident" || bad "create resident"

# 9. unmasked NRIC must be rejected
CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST $B/residents/ -H "$VH" -H 'Content-Type: application/json' \
  -d '{"name":"Bad","nric_masked":"S1234567A","contact":""}')
[ "$CODE" = "400" -o "$CODE" = "422" ] && ok "unmasked NRIC rejected ($CODE)" || bad "unmasked NRIC accepted! ($CODE)"

# 10. create case (client payload shape: no session_id, with notes + is_reappeal)
CID=$(curl -s -X POST $B/cases/ -H "$VH" -H 'Content-Type: application/json' \
  -d "{\"resident_id\":\"$RID\",\"agency\":\"CPF\",\"case_type\":\"appeal\",\"urgency\":\"normal\",\"is_reappeal\":false,\"notes\":\"Resident cannot meet BRS, asks for hardship withdrawal.\"}" \
  | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("id",""))')
[ -n "$CID" ] && ok "create case (client payload)" || bad "create case"

# 11. GET /cases list (volunteer)
N=$(curl -s "$B/cases/" -H "$VH" | python3 -c 'import sys,json;print(len(json.load(sys.stdin).get("cases",[])))')
[ "$N" = "1" ] && ok "GET /cases list (volunteer sees own)" || bad "GET /cases list ($N cases)"

# 12. GET /cases/{id} detail with notes
NOTES=$(curl -s "$B/cases/$CID" -H "$VH" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("notes") or "")')
echo "$NOTES" | grep -q "BRS" && ok "GET /cases/{id} returns notes" || bad "case detail notes missing"

# 13. volunteer submit -> drafted
curl -sf -X POST "$B/cases/$CID/submit" -H "$VH" >/dev/null && ok "volunteer submit" || bad "volunteer submit"

# 14. vetter queue shows it
TTOKEN=$(curl -s -X POST $B/auth/login -d 'username=vet1&password=VetPass#2026' | python3 -c 'import sys,json;print(json.load(sys.stdin).get("access_token",""))')
TH="Authorization: Bearer $TTOKEN"
QN=$(curl -s "$B/cases/queue" -H "$TH" | python3 -c 'import sys,json;print(len(json.load(sys.stdin).get("cases",[])))')
[ "$QN" = "1" ] && ok "vetter queue" || bad "vetter queue ($QN)"

# 15. vetter-submit freezes (no letter exists -> expect 400 here, since no draft was generated without Ollama)
CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$B/cases/$CID/vetter-submit" -H "$TH" -H 'Content-Type: application/json' -d '{"final_content":"Final text"}')
[ "$CODE" = "400" ] && ok "vetter-submit without draft -> 400 (no letter yet, correct)" || bad "vetter-submit -> $CODE"

# 16. vetter-return path
CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$B/cases/$CID/vetter-return" -H "$TH" -H 'Content-Type: application/json' -d '{"comment":"Need household income figures"}')
[ "$CODE" = "200" ] && ok "vetter-return" || bad "vetter-return -> $CODE"

# 17. feedback: log (volunteer, anonymised payload), validate (vetter), approved list
FID=$(curl -s -X POST $B/feedback/ -H "$VH" -H 'Content-Type: application/json' \
  -d '{"agency_code":"CPF","incorrect_claim":"BRS is $99,400","correct_answer":"BRS for 2026 is $102,900"}' \
  | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("id",""))')
[ -n "$FID" ] && ok "feedback logged (no case_id, anonymised)" || bad "feedback log"
CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$B/feedback/$FID/validate" -H "$TH" -H 'Content-Type: application/json' -d '{"action":"approve"}')
[ "$CODE" = "200" ] && ok "feedback approve" || bad "feedback approve -> $CODE"
AN=$(curl -s "$B/feedback/approved" -H "$TH" | python3 -c 'import sys,json;print(len(json.load(sys.stdin)))')
[ "$AN" = "1" ] && ok "GET /feedback/approved (Hermes feed)" || bad "approved feed ($AN)"

# 18. reject without reason -> 422
F2=$(curl -s -X POST $B/feedback/ -H "$VH" -H 'Content-Type: application/json' \
  -d '{"agency_code":"HDB","incorrect_claim":"x","correct_answer":"y"}' | python3 -c 'import sys,json;print(json.load(sys.stdin).get("id",""))')
CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$B/feedback/$F2/validate" -H "$TH" -H 'Content-Type: application/json' -d '{"action":"reject"}')
[ "$CODE" = "422" ] && ok "reject without reason -> 422" || bad "reject no-reason -> $CODE"

echo "=============================="
echo "PASS=$PASS FAIL=$FAIL"

# ── Iteration-3 additions: signup gate, logout revocation, priority queue ────
echo '--- extended checks ---'

# 19. /auth/signup disabled by default -> 403
CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST $B/auth/signup -H 'Content-Type: application/json'   -d '{"username":"selfreg","password":"SelfPass#2026","full_name":"Self Reg"}')
[ "$CODE" = "403" ] && ok "signup disabled -> 403" || bad "signup -> $CODE (want 403)"

# 20. logout revokes the token: a call after logout -> 401
VT2=$(curl -s -X POST $B/auth/login -d 'username=vol1&password=VolPass#2026' | python3 -c 'import sys,json;print(json.load(sys.stdin).get("access_token",""))')
H2="Authorization: Bearer $VT2"
curl -s -o /dev/null -X POST $B/auth/logout -H "$H2"
CODE=$(curl -s -o /dev/null -w '%{http_code}' $B/cases/ -H "$H2")
[ "$CODE" = "401" ] && ok "token revoked after logout -> 401" || bad "revoked token -> $CODE (want 401)"

# 21. /health reports ollama + queue depth
HJSON=$(curl -s $B/health)
echo "$HJSON" | grep -q 'llm_queue_waiting' && ok "health reports queue depth" || bad "health missing queue depth"

echo '=============================='
echo "FINAL PASS=$PASS FAIL=$FAIL"
