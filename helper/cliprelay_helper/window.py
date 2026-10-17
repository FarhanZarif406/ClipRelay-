"""The helper's window: a small page on this computer only (127.0.0.1), opened in the browser from the tray icon.

It connects the PC with the code from the website and shows what the helper is doing. A random key in the link
keeps other web pages from using it.
"""

import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from cliprelay_helper import VERSION
from cliprelay_helper.client import Client, ServerError, clean_address
from cliprelay_helper.store import Settings, data_dir, platform_name
from cliprelay_helper.system import set_start_with_computer, starts_with_computer

PORT = 47613


def _key_file() -> str:
    return os.path.join(data_dir(), "window.key")


def running_link() -> str | None:
    """The window of a helper that already runs on this computer, if one does."""
    try:
        with open(_key_file(), encoding="utf-8") as fh:
            key = fh.read().strip()
    except OSError:
        return None
    return f"http://127.0.0.1:{PORT}/?k={key}" if key else None


class Window:
    def __init__(self, settings: Settings, worker):
        self.settings = settings
        self.worker = worker
        self.key = secrets.token_urlsafe(18)
        self.server: ThreadingHTTPServer | None = None

    @property
    def link(self) -> str:
        return f"http://127.0.0.1:{PORT}/?k={self.key}"

    def start(self) -> bool:
        """False when another helper already has the window's place (it is running)."""
        window = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def _ok(self) -> bool:
                query = parse_qs(urlparse(self.path).query)
                return secrets.compare_digest((query.get("k") or [""])[0], window.key)

            def _send(self, code: int, body: bytes, kind: str) -> None:
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Frame-Options", "DENY")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, value: dict, code: int = 200) -> None:
                self._send(code, json.dumps(value, default=str).encode(), "application/json")

            def do_GET(self):
                if not self._ok():
                    return self._send(403, b"Open this window from the ClipRelay Helper icon.", "text/plain")
                path = urlparse(self.path).path
                if path == "/":
                    return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
                if path == "/state":
                    return self._json(window.state())
                return self._send(404, b"", "text/plain")

            def do_POST(self):
                if not self._ok() or self.headers.get("X-Helper") != "1":  # a page elsewhere cannot set this header without asking
                    return self._json({"error": "Not allowed"}, 403)
                size = min(int(self.headers.get("Content-Length") or 0), 10_000)
                try:
                    body = json.loads(self.rfile.read(size) or b"{}")
                except ValueError:
                    body = {}
                try:
                    return self._json(window.act(urlparse(self.path).path, body))
                except ServerError as exc:
                    return self._json({"error": str(exc)}, 400)

        try:
            self.server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
        except OSError:
            return False
        with open(_key_file(), "w", encoding="utf-8") as fh:
            fh.write(self.key)
        if os.name == "posix":
            os.chmod(_key_file(), 0o600)
        threading.Thread(target=self.server.serve_forever, name="window", daemon=True).start()
        return True

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()

    def state(self) -> dict:
        s = self.settings
        return {
            **self.worker.snapshot(), "version": VERSION, "platform": platform_name(),
            "connected": s.connected, "server": s.get("server"), "name": s.get("name"), "account": s.get("account"),
            "paused": bool(s.get("paused")), "language": s.get("language") or "en", "starts_with_computer": starts_with_computer(),
        }

    def act(self, path: str, body: dict) -> dict:
        s = self.settings
        if path == "/connect":
            server = clean_address(body.get("server") or s.get("server"))
            if not server:
                raise ServerError("Type your ClipRelay address (it is shown on the website: PC Helper).")
            name = (body.get("name") or s.get("name")).strip()[:80]
            answer = Client.connect(server, (body.get("code") or "").strip(), name)
            s.update(server=server, token=answer["token"], name=name, account=answer.get("account", ""), paused=False)
            set_start_with_computer(True)  # a connected PC is ready again after a restart
            self.worker.wake.set()
        elif path == "/pause":
            s.update(paused=bool(body.get("paused")))
            self.worker.wake.set()
        elif path == "/autostart":
            set_start_with_computer(bool(body.get("on")))
        elif path == "/language":
            s.update(language="ur" if body.get("language") == "ur" else "en", language_chosen=True)
        elif path == "/disconnect":
            Client(s).disconnect()
            s.update(token="", account="")
            self.worker.wake.set()
        return self.state()


PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ClipRelay Helper</title>
<style>
:root{--bg:#f4f6fb;--card:#fff;--text:#162033;--muted:#5d6b82;--line:#e2e7f0;--primary:#4f46e5;--ok:#0f9d58;--warn:#c47f00;--bad:#d93025}
@media (prefers-color-scheme:dark){:root{--bg:#0f1420;--card:#171e2d;--text:#e8edf6;--muted:#9aa7bd;--line:#273149;--primary:#8b84ff;--ok:#3ccf8e;--warn:#f0b54a;--bad:#ff6b5e}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:620px;margin:0 auto;padding:28px 16px}
header{display:flex;align-items:center;gap:12px;margin-bottom:18px}
.logo{width:40px;height:40px;border-radius:12px;background:var(--primary);color:#fff;display:grid;place-items:center;font-weight:800;font-size:20px}
h1{font-size:20px;margin:0}small,.muted{color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px;margin-bottom:14px}
.status{display:flex;align-items:center;gap:12px}.dot{width:14px;height:14px;border-radius:50%;flex:none;background:var(--muted)}
.dot.ok{background:var(--ok)}.dot.work{background:var(--primary);animation:p 1.2s infinite}.dot.warn{background:var(--warn)}.dot.bad{background:var(--bad)}
@keyframes p{50%{opacity:.4}}
.bar{height:8px;background:var(--line);border-radius:8px;overflow:hidden;margin-top:12px}.bar i{display:block;height:100%;background:var(--primary)}
label{display:block;font-weight:600;margin:12px 0 4px}input{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--text);font:inherit}
button{font:inherit;border:0;border-radius:10px;padding:10px 16px;cursor:pointer;background:var(--primary);color:#fff;font-weight:600}
button.ghost{background:transparent;color:var(--text);border:1px solid var(--line)}button.danger{background:transparent;color:var(--bad);border:1px solid var(--line)}
.row{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}.err{color:var(--bad);margin-top:10px}
.lang{margin-left:auto;display:flex;border:1px solid var(--line);border-radius:10px;overflow:hidden}.lang button{border-radius:0;background:transparent;color:var(--muted);padding:6px 10px}.lang button.on{background:var(--primary);color:#fff}
dl{display:grid;grid-template-columns:auto 1fr;gap:6px 14px;margin:0}dt{color:var(--muted)}dd{margin:0;word-break:break-word}
.switch{display:flex;align-items:center;gap:10px;margin-top:12px}.switch input{width:auto}
</style></head><body><main>
<header><div class="logo">C</div><div><h1>ClipRelay Helper</h1><small id="ver"></small></div>
<div class="lang"><button data-l="en">EN</button><button data-l="ur">UR</button></div></header>
<div id="app"></div>
</main><script>
const K=new URLSearchParams(location.search).get("k");let S=null,err="";
const T={en:{
connect:"Connect this computer",connectHelp:"On the ClipRelay website open PC Helper and press Connect a PC. Type the address and the code it shows.",
address:"ClipRelay address",code:"Code",name:"Name of this computer",go:"Connect",
idle:"Ready: waiting for your next video",downloading:"Downloading",editing:"Editing",sending:"Sending the finished video",paused:"Paused: your videos go to the cloud meanwhile",
offline:"ClipRelay cannot be reached: check the internet",starting:"Starting…",not_connected:"Not connected",
pause:"Pause",resume:"Resume",disconnect:"Disconnect this computer",sure:"Disconnect this computer? Its videos go to the cloud until you connect it again.",
account:"Account",server:"ClipRelay",pc:"This computer",today:"Edited since start",auto:"Start with my computer",
update:"A new version is ready:",download:"Download it",lastErr:"Last problem",keepOpen:"You can close this window: the helper keeps working from the icon next to the clock."},
ur:{
connect:"Is computer ko jorein",connectHelp:"ClipRelay website par PC Helper kholein aur Connect a PC dabayein. Wahan dikhaya gaya address aur code yahan likhein.",
address:"ClipRelay ka address",code:"Code",name:"Is computer ka naam",go:"Jorein",
idle:"Tayyar: agli video ka intezar",downloading:"Download ho rahi hai",editing:"Edit ho rahi hai",sending:"Tayyar video bheji ja rahi hai",paused:"Ruka hua: is dauran aap ki videos cloud par jati hain",
offline:"ClipRelay tak rabta nahi: internet check karein",starting:"Shuru ho raha hai…",not_connected:"Jura hua nahi",
pause:"Rokein",resume:"Dobara chalayein",disconnect:"Is computer ko alag karein",sure:"Is computer ko alag karein? Jab tak dobara na jorein, iski videos cloud par jayengi.",
account:"Account",server:"ClipRelay",pc:"Ye computer",today:"Shuru se edit huin",auto:"Computer ke saath shuru ho",
update:"Naya version tayyar hai:",download:"Download karein",lastErr:"Aakhri masla",keepOpen:"Ye window band kar sakte hain: helper ghari ke paas icon se kaam karta rahega."}};
const t=k=>(T[(S&&S.language)||"en"]||T.en)[k]||k;
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
async function post(p,b){const r=await fetch(p+"?k="+K,{method:"POST",headers:{"Content-Type":"application/json","X-Helper":"1"},body:JSON.stringify(b||{})});const j=await r.json();if(!r.ok)throw new Error(j.error||"Error");S=j;return j}
async function load(){try{const r=await fetch("/state?k="+K);S=await r.json();render()}catch(e){}}
function dot(){if(!S.connected)return"bad";if(S.stage==="offline")return"warn";if(S.paused)return"warn";if(["downloading","editing","sending"].includes(S.stage))return"work";return"ok"}
function render(){
document.getElementById("ver").textContent="v"+S.version;
document.querySelectorAll(".lang button").forEach(b=>b.classList.toggle("on",b.dataset.l===(S.language||"en")));
const app=document.getElementById("app");
if(!S.connected){app.innerHTML=`<div class="card"><h2 style="margin:0 0 6px;font-size:17px">${t("connect")}</h2><div class="muted">${t("connectHelp")}</div>
<label>${t("address")}</label><input id="srv" placeholder="https://clips.example.com" value="${esc(S.server)}">
<label>${t("code")}</label><input id="code" placeholder="ABC-123" autocomplete="off" style="text-transform:uppercase;letter-spacing:2px">
<label>${t("name")}</label><input id="nm" value="${esc(S.name)}">
<div class="row"><button id="go">${t("go")}</button></div>${err?`<div class="err">${esc(err)}</div>`:""}</div>`;
document.getElementById("go").onclick=async()=>{err="";try{await post("/connect",{server:srv.value,code:code.value,name:nm.value})}catch(e){err=e.message}render()};return}
const busy=["downloading","editing","sending"].includes(S.stage);const label=t(S.paused?"paused":S.stage);
const outdated=S.latest_version&&S.latest_version!==S.version;const dl=S.platform==="mac"?S.download_mac:S.download_windows;
app.innerHTML=`<div class="card"><div class="status"><span class="dot ${dot()}"></span><div><strong>${esc(label)}${busy&&S.percent!=null?" · "+S.percent+"%":""}</strong>
${busy&&S.title?`<div class="muted">${esc(S.title)}</div>`:""}${S.message?`<div class="muted">${esc(S.message)}</div>`:""}</div></div>
${busy?`<div class="bar"><i style="width:${Math.max(2,S.percent||0)}%"></i></div>`:""}
<div class="row"><button class="ghost" id="pz">${S.paused?t("resume"):t("pause")}</button></div></div>
<div class="card"><dl><dt>${t("account")}</dt><dd>${esc(S.account)}</dd><dt>${t("server")}</dt><dd>${esc(S.server)}</dd><dt>${t("pc")}</dt><dd>${esc(S.name)}</dd><dt>${t("today")}</dt><dd>${S.done_today}</dd>
${S.last_error?`<dt>${t("lastErr")}</dt><dd>${esc(S.last_error)}</dd>`:""}</dl>
<label class="switch"><input type="checkbox" id="au" ${S.starts_with_computer?"checked":""}> ${t("auto")}</label>
${outdated?`<p>${t("update")} v${esc(S.latest_version)}${dl?` · <a href="${esc(dl)}" target="_blank" rel="noopener">${t("download")}</a>`:""}</p>`:""}
<div class="row"><button class="danger" id="dc">${t("disconnect")}</button></div></div><p class="muted">${t("keepOpen")}</p>`;
document.getElementById("pz").onclick=()=>post("/pause",{paused:!S.paused}).then(render);
document.getElementById("au").onchange=e=>post("/autostart",{on:e.target.checked}).then(render);
document.getElementById("dc").onclick=()=>{if(confirm(t("sure")))post("/disconnect").then(render)};}
document.querySelectorAll(".lang button").forEach(b=>b.onclick=()=>post("/language",{language:b.dataset.l}).then(render));
load();setInterval(()=>{if(S&&S.connected)load()},2000);
</script></body></html>"""
