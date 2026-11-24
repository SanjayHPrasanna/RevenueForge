"""MCP server end to end: OAuth (DCR + PKCE + consent + refresh rotation), API keys, every tool, and the refusals.
Run: python tests/qa_mcp.py [knowledge-folder] [rfp-file]"""
import base64, glob, hashlib, json, os, secrets, sys, tempfile, time, uuid
from urllib.parse import parse_qs, urlparse

os.environ["RF_DATA_DIR"] = tempfile.mkdtemp(); os.environ["RADAR_REFRESH_HOURS"] = "0"; os.environ["DEMO_VENDORS"] = "false"
os.environ.pop("GEMINI_API_KEY", None); os.environ["LLM_PROVIDER"] = "none"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import logging; logging.disable(logging.WARNING)
from fastapi.testclient import TestClient
from app.main import app

FOLDER = sys.argv[1] if len(sys.argv) > 1 else ""
RFP = sys.argv[2] if len(sys.argv) > 2 else ""
fails = 0


def ok(name, cond, extra=""):
    global fails
    fails += not cond
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


def rpc(c, token, method, params=None, mid=1):
    r = c.post("/mcp", json={"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}},
               headers={"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"})
    return r


def call(c, token, name, args=None):
    r = rpc(c, token, "tools/call", {"name": name, "arguments": args or {}})
    res = r.json()["result"]
    txt = res["content"][0]["text"]
    try:
        return res["isError"], json.loads(txt)
    except ValueError:
        return res["isError"], txt


with TestClient(app) as c:
    reg = c.post("/api/auth/register", json={"company_name": "iSteer Technologies", "name": "Admin", "email": "admin@isteer.example",
                                             "password": uuid.uuid4().hex}).json()
    h = {"Authorization": "Bearer " + reg["token"]}
    if FOLDER:
        files = [f for f in sorted(glob.glob(os.path.join(FOLDER, "*"))) if not f.endswith(".docx")]
        r = c.post("/api/library/folder", files=[("files", (os.path.basename(f), open(f, "rb").read())) for f in files],
                   data={"paths": ["lib/" + os.path.basename(f) for f in files], "batch": uuid.uuid4().hex[:12]}, headers=h)
        batch = r.json()["batch"]
        for _ in range(120):
            if not c.get(f"/api/library/folder/{batch}", headers=h).json().get("pending"):
                break
            time.sleep(0.5)
        print("library import", c.post(f"/api/library/folder/{batch}/import", json={}, headers=h).json().get("counts"))

    # ---- discovery
    r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    ok("no token -> 401", r.status_code == 401)
    ok("401 points at resource metadata", 'resource_metadata="https://testserver/.well-known/oauth-protected-resource/mcp"' in r.headers.get("www-authenticate", ""), r.headers.get("www-authenticate"))
    prm = c.get("/.well-known/oauth-protected-resource/mcp").json()
    ok("protected resource = /mcp", prm["resource"] == "https://testserver/mcp" and prm["authorization_servers"] == ["https://testserver"], prm)
    asm = c.get("/.well-known/oauth-authorization-server").json()
    ok("AS metadata: S256 + DCR", asm["code_challenge_methods_supported"] == ["S256"] and asm["registration_endpoint"].endswith("/oauth/register"))
    ok("GET /mcp -> 405, not the web app", c.get("/mcp").status_code == 405)

    # ---- DCR
    bad = c.post("/oauth/register", json={"client_name": "x", "redirect_uris": ["http://evil.example/cb"]})
    ok("DCR refuses plain-http non-loopback redirect", bad.status_code == 400)
    cl = c.post("/oauth/register", json={"client_name": "Claude", "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
                                         "token_endpoint_auth_method": "none"}).json()
    ok("DCR public client", cl["client_id"].startswith("rfc_") and "client_secret" not in cl)

    # ---- authorize -> consent -> code
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    q = {"response_type": "code", "client_id": cl["client_id"], "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
         "code_challenge": challenge, "code_challenge_method": "S256", "state": "xyz", "scope": "revenueforge", "resource": "https://testserver/mcp"}
    r = c.get("/oauth/authorize", params={**q, "redirect_uri": "https://evil.example/cb"}, follow_redirects=False)
    ok("authorize refuses unregistered redirect (no redirect)", r.status_code == 400)
    r = c.get("/oauth/authorize", params={**q, "code_challenge_method": "plain"}, follow_redirects=False)
    ok("authorize requires S256", r.status_code == 302 and "error=invalid_request" in r.headers["location"])
    r = c.get("/oauth/authorize", params=q, follow_redirects=False)
    ok("authorize -> /connect", r.status_code == 302 and urlparse(r.headers["location"]).path == "/connect")
    creq = parse_qs(urlparse(r.headers["location"]).query)["request"][0]
    ok("consent needs sign-in", c.get("/api/mcp/consent", params={"request": creq}).status_code == 401)
    info = c.get("/api/mcp/consent", params={"request": creq}, headers=h).json()
    ok("consent info", info["client_name"] == "Claude" and info["redirect_host"] == "claude.ai" and info["company"] == "iSteer Technologies", info)
    deny = c.post("/api/mcp/consent", json={"request": creq, "allow": False}, headers=h).json()
    ok("deny -> access_denied", "error=access_denied" in deny["redirect"] and "state=xyz" in deny["redirect"])
    allow = c.post("/api/mcp/consent", json={"request": creq, "allow": True}, headers=h).json()
    cq = parse_qs(urlparse(allow["redirect"]).query)
    ok("allow -> code + state", "code" in cq and cq["state"] == ["xyz"])
    code = cq["code"][0]

    tok = lambda data: c.post("/oauth/token", data=data)
    r = tok({"grant_type": "authorization_code", "code": code, "client_id": cl["client_id"], "redirect_uri": q["redirect_uri"],
             "code_verifier": "wrong" * 10})
    ok("bad PKCE verifier -> invalid_grant", r.status_code == 400 and r.json()["error"] == "invalid_grant")
    ok("code is single use (burnt by the failed try)", tok({"grant_type": "authorization_code", "code": code, "client_id": cl["client_id"],
                                                             "code_verifier": verifier}).json().get("error") == "invalid_grant")
    allow = c.post("/api/mcp/consent", json={"request": creq, "allow": True}, headers=h).json()
    code = parse_qs(urlparse(allow["redirect"]).query)["code"][0]
    t = tok({"grant_type": "authorization_code", "code": code, "client_id": cl["client_id"], "redirect_uri": q["redirect_uri"],
             "code_verifier": verifier}).json()
    ok("token exchange", t.get("access_token", "").startswith("rfa_") and t.get("refresh_token", "").startswith("rfr_"), t)
    at = t["access_token"]

    # ---- MCP protocol
    init = rpc(c, at, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}).json()
    ok("initialize", init["result"]["protocolVersion"] == "2025-06-18" and "tools" in init["result"]["capabilities"], init)
    r = c.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers={"Authorization": f"Bearer {at}"})
    ok("notification -> 202", r.status_code == 202)
    tools = rpc(c, at, "tools/list").json()["result"]["tools"]
    names = {x["name"] for x in tools}
    ok("tools listed", {"list_deals", "get_deal", "get_requirements", "search_knowledge", "company_overview", "pipeline_summary",
                        "find_opportunities", "ask_workspace", "create_deal"} <= names, names)
    ok("create_deal marked not read-only", next(x for x in tools if x["name"] == "create_deal")["annotations"]["readOnlyHint"] is False)
    ok("unknown method -> -32601", rpc(c, at, "foo/bar").json()["error"]["code"] == -32601)

    err, ov = call(c, at, "company_overview")
    ok("company_overview", not err and ov["company"] == "iSteer Technologies", ov)
    print("   library counts:", ov.get("library_counts"))
    if FOLDER:
        err, kn = call(c, at, "search_knowledge", {"query": "Microsoft Fabric DP-600", "limit": 3})
        ok("search_knowledge finds Fabric", not err and "people" in kn, kn)
        ok("people shown by code, no names, no day cost", not err and all("name" not in p and "day_cost" not in p for p in kn["people"]["top"]))
        err, kn = call(c, at, "search_knowledge", {"query": "TIBCO EBX", "section": "case_studies"})
        ok("search_knowledge by section", not err and list(kn) == ["case studies"], kn)
        err, kn = call(c, at, "search_knowledge", {"query": "zzqqxx"})
        ok("no match is said plainly", not err and kn.get("matches") == 0)
    err, pl = call(c, at, "pipeline_summary")
    ok("pipeline_summary", not err and "kpis" in pl, pl)
    err, ld = call(c, at, "list_deals")
    ok("list_deals empty", not err and ld["total"] == 0, ld)
    err, msg = call(c, at, "get_deal", {"deal_id": "../../etc"})
    ok("get_deal rejects odd ids", err)
    err, msg = call(c, at, "get_deal", {"deal_id": "nope"})
    ok("get_deal unknown -> tool error", err, msg)

    if RFP:
        data = base64.b64encode(open(RFP, "rb").read()).decode()
        err, cd = call(c, at, "create_deal", {"name": "Fabric data platform", "client_name": "Harbourline Insurance", "file_base64": data,
                                              "file_name": os.path.basename(RFP), "engagement_type": "build_run"})
        ok("create_deal", not err and cd.get("deal_id"), cd)
        if not err:
            for _ in range(240):
                e2, dd = call(c, at, "get_deal", {"deal_id": cd["deal_id"]})
                if dd.get("status") != "processing":
                    break
                time.sleep(1)
            ok("deal analysed", dd.get("status") in ("in_review", "submitted"), dd.get("status"))
            ok("client masked by default", dd.get("client") != "Harbourline Insurance", dd.get("client"))
            print("   verdict:", dd.get("verdict"), "| today", dd.get("readiness_today"), "| with plan", dd.get("readiness_with_plan"))
            print("   reason:", dd.get("verdict_reason"))
            print("   top missing:", [m["technology"] + "→" + str(m["recommendation"]) for m in dd.get("top_missing") or []][:8])
            print("   team:", {k: v for k, v in (dd.get("team") or {}).items() if k != "roles"}, "| price:", dd.get("price_scenarios"), dd.get("price_currency"))
            e3, rq = call(c, at, "get_requirements", {"deal_id": cd["deal_id"], "show": "gaps", "limit": 5})
            ok("get_requirements gaps", not e3 and rq["total"] >= 0, rq)
            print("   gaps:", rq["total"], [r["code"] for r in rq["requirements"]])
            e4, ld = call(c, at, "list_deals")
            ok("list_deals shows it", not e4 and ld["total"] == 1)
    err, msg = call(c, at, "create_deal", {"name": "x", "rfp_text": "too short"})
    ok("create_deal refuses a scrap of text", err)

    # ---- refresh rotation
    t2 = tok({"grant_type": "refresh_token", "refresh_token": t["refresh_token"], "client_id": cl["client_id"]}).json()
    ok("refresh issues new pair", t2.get("access_token") and t2["refresh_token"] != t["refresh_token"], t2)
    ok("old refresh token no longer works", tok({"grant_type": "refresh_token", "refresh_token": t["refresh_token"],
                                                  "client_id": cl["client_id"]}).json().get("error") == "invalid_grant")
    ok("new access token works", rpc(c, t2["access_token"], "ping").status_code == 200)

    # ---- connections list + disconnect
    con = c.get("/api/mcp/connections", headers=h).json()
    ok("connections list", con["url"] == "https://testserver/mcp" and len(con["connections"]) == 1 and con["connections"][0]["client"] == "Claude", con)
    c.delete(f"/api/mcp/connections/{con['connections'][0]['id']}", headers=h)
    ok("disconnect kills access token", rpc(c, t2["access_token"], "ping").status_code == 401)
    ok("disconnect kills refresh token", tok({"grant_type": "refresh_token", "refresh_token": t2["refresh_token"],
                                               "client_id": cl["client_id"]}).json().get("error") == "invalid_grant")

    # ---- API key (Glean "API key" / request headers)
    key = c.post("/api/mcp/keys", json={"label": "Glean"}, headers=h).json()["key"]
    ok("api key issued", key.startswith("rfk_"))
    ok("api key works", rpc(c, key, "tools/list").status_code == 200)
    r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}, headers={"X-API-Key": key})
    ok("api key in X-API-Key works", r.status_code == 200)
    keys = c.get("/api/mcp/connections", headers=h).json()["keys"]
    ok("key listed with hint only", len(keys) == 1 and keys[0]["hint"] == key[-4:] and "key" not in keys[0])
    c.delete(f"/api/mcp/connections/{keys[0]['id']}", headers=h)
    ok("revoked key refused", rpc(c, key, "ping").status_code == 401)

    # ---- another company can't use or revoke
    other = c.post("/api/auth/register", json={"company_name": "Other Co", "name": "Other Admin", "email": "o@other.example", "password": uuid.uuid4().hex}).json()
    if "token" not in other:
        print("   register other:", other)
    ho = {"Authorization": "Bearer " + other["token"]}
    k2 = c.post("/api/mcp/keys", json={"label": "mine"}, headers=h).json()["key"]
    kid = c.get("/api/mcp/connections", headers=h).json()["keys"][0]["id"]
    ok("other company can't revoke my key", c.delete(f"/api/mcp/connections/{kid}", headers=ho).status_code == 404)
    err, ov2 = call(c, c.post("/api/mcp/keys", json={"label": "o"}, headers=ho).json()["key"], "list_deals")
    ok("other company's key sees only its own deals", not err and ov2["total"] == 0, ov2)
    err, ov = call(c, k2, "company_overview")
    ok("my key still mine", ov["company"] == "iSteer Technologies")

print("\nALL PASS" if not fails else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
