"""The helper's window (one page, English or Roman Urdu): live work, the member's plan, monthly figures, this computer."""

from urllib.parse import quote

from cliprelay_helper.logo import SVG

PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ClipRelay Helper</title><link rel="icon" href="data:image/svg+xml,__ICON__">
<style>
:root{--bg:#0b0d12;--surface:#11141b;--surface-2:#151924;--surface-3:#1b2030;--border:#232938;--border-2:#30384a;--text:#e6e8ee;--muted:#8a91a5;--muted-2:#666e83;
--primary:#6c5ce7;--primary-2:#8b7cf7;--primary-soft:rgba(108,92,231,.14);--ok:#22c55e;--warn:#f59e0b;--bad:#ef4444;--radius:16px}
*{box-sizing:border-box}html,body{margin:0}
body{min-height:100vh;color:var(--text);font:14px/1.5 Inter,"Segoe UI",system-ui,-apple-system,sans-serif;
background:radial-gradient(900px 420px at 12% -8%,rgba(108,92,231,.22),transparent 60%),radial-gradient(700px 380px at 100% 0,rgba(139,124,247,.10),transparent 60%),var(--bg)}
a{color:inherit}main{max-width:1120px;margin:0 auto;padding:26px 20px 40px}
.top{display:flex;align-items:center;gap:14px;margin-bottom:22px}
.brand{display:flex;align-items:center;gap:12px}.brand .mark{width:42px;height:42px;filter:drop-shadow(0 6px 18px rgba(108,92,231,.45))}
.brand b{display:block;font-size:18px;letter-spacing:-.3px}.brand small{color:var(--muted);font-size:12px}
.spacer{flex:1}
.pill{display:inline-flex;align-items:center;gap:8px;padding:7px 12px;border-radius:999px;background:var(--surface-2);border:1px solid var(--border);font-size:12px;font-weight:600;white-space:nowrap}
.dot{width:9px;height:9px;border-radius:50%;background:var(--muted)}.dot.ok{background:var(--ok);box-shadow:0 0 0 4px rgba(34,197,94,.15)}
.dot.work{background:var(--primary-2);box-shadow:0 0 0 4px rgba(139,124,247,.2);animation:pulse 1.4s infinite}.dot.warn{background:var(--warn)}.dot.bad{background:var(--bad)}
@keyframes pulse{50%{opacity:.35}}
.lang{display:flex;border:1px solid var(--border);border-radius:10px;overflow:hidden;background:var(--surface-2)}
.lang button{border:0;background:transparent;color:var(--muted);padding:7px 11px;font:600 12px Inter,sans-serif;cursor:pointer}.lang button.on{background:var(--primary);color:#fff}
.grid{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(0,1fr);gap:16px;align-items:start}.full{grid-column:1/-1}
.card{background:linear-gradient(180deg,rgba(255,255,255,.015),transparent),var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:20px}
.card h2{margin:0 0 14px;font-size:13px;letter-spacing:.6px;text-transform:uppercase;color:var(--muted);font-weight:700;display:flex;align-items:center;gap:8px}
.live{display:flex;gap:18px;align-items:stretch}
.thumb{position:relative;flex:0 0 240px;align-self:flex-start;aspect-ratio:16/9;border-radius:12px;overflow:hidden;background:var(--surface-3);border:1px solid var(--border);display:block}
.thumb img{width:100%;height:100%;object-fit:cover;display:block}.thumb .play{position:absolute;inset:0;display:grid;place-items:center;background:linear-gradient(0deg,rgba(0,0,0,.45),transparent)}
.thumb .play span{width:42px;height:42px;border-radius:50%;background:rgba(255,255,255,.92);display:grid;place-items:center}
.thumb .play span:after{content:"";border-left:13px solid #111;border-top:8px solid transparent;border-bottom:8px solid transparent;margin-left:3px}
.live-main{flex:1;min-width:0;display:flex;flex-direction:column;gap:8px}
.channel{color:var(--muted);font-size:12px}.title{font-size:17px;font-weight:700;letter-spacing:-.2px;text-decoration:none;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.title:hover{color:var(--primary-2)}.open{font-size:12px;color:var(--primary-2);text-decoration:none;font-weight:600}
.steps{display:flex;gap:6px;margin-top:4px}.step{flex:1;padding:8px 10px;border-radius:10px;background:var(--surface-2);border:1px solid var(--border);font-size:12px;color:var(--muted);font-weight:600;display:flex;align-items:center;gap:7px}
.step i{width:18px;height:18px;border-radius:50%;border:1.5px solid var(--border-2);display:grid;place-items:center;font-style:normal;font-size:10px}
.step.now{color:var(--text);border-color:rgba(139,124,247,.55);background:var(--primary-soft)}.step.now i{border-color:var(--primary-2);background:var(--primary)}
.step.done{color:var(--text)}.step.done i{background:var(--ok);border-color:var(--ok);color:#06130a}
.bar{height:10px;border-radius:99px;background:var(--surface-3);overflow:hidden;margin-top:6px}.bar i{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,var(--primary),var(--primary-2));transition:width .6s}
.pct{display:flex;justify-content:space-between;color:var(--muted);font-size:12px}.pct b{color:var(--text);font-size:20px}
.idle{display:flex;align-items:center;gap:18px;padding:8px 2px}.ring{width:64px;height:64px;border-radius:50%;flex:none;display:grid;place-items:center;background:var(--primary-soft);position:relative}
.ring:before{content:"";position:absolute;inset:-6px;border-radius:50%;border:2px solid rgba(139,124,247,.35);animation:ring 2.4s infinite}.ring img{width:30px}
@keyframes ring{0%{transform:scale(.9);opacity:1}100%{transform:scale(1.25);opacity:0}}
.idle b{font-size:17px}.idle p{margin:2px 0 0;color:var(--muted)}
.row{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}
button.btn{font:600 13px Inter,sans-serif;border-radius:10px;padding:10px 16px;cursor:pointer;border:1px solid var(--border);background:var(--surface-2);color:var(--text)}
button.btn:hover{border-color:var(--border-2)}button.primary{background:linear-gradient(145deg,var(--primary-2),var(--primary));border-color:transparent;color:#fff}
button.danger{color:#ff8a80}
.plan-badge{display:inline-flex;align-items:center;gap:8px;padding:8px 14px;border-radius:12px;font-weight:800;letter-spacing:1.4px;font-size:13px;color:#111}
.tier-free{background:linear-gradient(135deg,#9aa3b5,#6b7385);color:#fff}.tier-bronze{background:linear-gradient(135deg,#e2a46b,#a8642b)}.tier-silver{background:linear-gradient(135deg,#f1f3f7,#a9b0bd)}
.tier-gold{background:linear-gradient(135deg,#ffe08a,#e0a91b)}.tier-platinum{background:linear-gradient(135deg,#e9f6ff,#9fb8d6)}.tier-owner{background:linear-gradient(145deg,var(--primary-2),var(--primary));color:#fff}
.plan-line{margin-top:12px;font-size:14px}.plan-line b{font-size:15px}.muted{color:var(--muted)}.small{font-size:12px}
.days{height:8px;border-radius:99px;background:var(--surface-3);overflow:hidden;margin-top:10px}.days i{display:block;height:100%;background:linear-gradient(90deg,var(--ok),#7ee2a3)}
.days.low i{background:linear-gradient(90deg,var(--warn),#ffd27a)}
.alert{margin-top:12px;padding:10px 12px;border-radius:10px;font-size:13px;background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.35);color:#ffb4ae}
.months{display:flex;gap:6px;margin-left:auto}.months button{border:1px solid var(--border);background:var(--surface-2);color:var(--muted);border-radius:9px;padding:6px 11px;font:600 12px Inter,sans-serif;cursor:pointer}
.months button.on{color:#fff;background:var(--primary);border-color:var(--primary)}
.tiles{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.tile{background:var(--surface-2);border:1px solid var(--border);border-radius:14px;padding:16px}.tile span{color:var(--muted);font-size:12px;font-weight:600}
.tile b{display:block;font-size:30px;letter-spacing:-1px;margin-top:6px}.tile small{color:var(--muted-2);font-size:11px}.tile.hi{border-color:rgba(139,124,247,.45);background:linear-gradient(160deg,rgba(108,92,231,.18),var(--surface-2))}
.share{display:flex;height:8px;border-radius:99px;overflow:hidden;background:var(--surface-3);margin-top:14px}.share i{display:block;height:100%}
.legend{display:flex;gap:16px;margin-top:8px;font-size:12px;color:var(--muted)}.legend em{display:inline-block;width:9px;height:9px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.list{display:flex;flex-direction:column}.item{display:flex;align-items:center;gap:12px;padding:10px 0;border-top:1px solid var(--border)}.item:first-child{border-top:0}
.item img{width:72px;aspect-ratio:16/9;object-fit:cover;border-radius:8px;background:var(--surface-3);flex:none}.item a{text-decoration:none;font-weight:600}.item a:hover{color:var(--primary-2)}
.item .meta{color:var(--muted);font-size:12px}.item .grow{flex:1;min-width:0}.item .grow a{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tag{font-size:11px;font-weight:700;padding:4px 8px;border-radius:7px;background:var(--surface-3);color:var(--muted);white-space:nowrap}.tag.ok{color:var(--ok);background:rgba(34,197,94,.1)}.tag.p{color:var(--primary-2);background:var(--primary-soft)}
dl{display:grid;grid-template-columns:auto 1fr;gap:8px 16px;margin:0}dt{color:var(--muted)}dd{margin:0;word-break:break-word}
.switch{display:flex;align-items:center;gap:10px;margin-top:14px;cursor:pointer;font-weight:600}.switch input{width:18px;height:18px;accent-color:var(--primary)}
.note{color:var(--muted);font-size:12px;margin-top:14px}.update{margin-top:12px;padding:10px 12px;border-radius:10px;background:var(--primary-soft);border:1px solid rgba(139,124,247,.35);font-size:13px}
.update a{color:var(--primary-2);font-weight:700}
.connect{max-width:520px;margin:30px auto}.connect .card{padding:28px}.connect h1{margin:0 0 6px;font-size:22px;letter-spacing:-.4px}
.connect ol{color:var(--muted);padding-left:18px;margin:12px 0 4px}label{display:block;font-weight:600;font-size:13px;margin:14px 0 6px}
input.in{width:100%;padding:11px 13px;border:1px solid var(--border);border-radius:10px;background:var(--surface-2);color:var(--text);font:14px Inter,sans-serif;outline:0}input.in:focus{border-color:var(--primary)}
input.code{text-transform:uppercase;letter-spacing:4px;font-weight:700;font-size:18px}.err{color:#ff8a80;margin-top:12px;font-size:13px}
@media (max-width:860px){.grid{grid-template-columns:1fr}.tiles{grid-template-columns:repeat(2,minmax(0,1fr))}.live{flex-direction:column}.thumb{flex-basis:auto}}
</style></head><body><main>
<div class="top"><div class="brand"><img class="mark" alt="" src="data:image/svg+xml,__ICON__"><div><b>ClipRelay Helper</b><small id="ver"></small></div></div>
<div class="spacer"></div><span class="pill" id="pill"></span><div class="lang"><button data-l="en">EN</button><button data-l="ur">UR</button></div></div>
<div id="app"></div>
</main><script>
const K=new URLSearchParams(location.search).get("k");let S=null,err="",month=0,last="";
const T={en:{
connect:"Connect this computer",connectHelp:"Your computer will download and edit your ClipRelay videos itself.",s1:"On the ClipRelay website open PC Helper.",s2:"Press Connect a PC: it shows an address and a code.",s3:"Type both here and press Connect.",
address:"ClipRelay address",code:"Code",name:"Name of this computer",go:"Connect",
idle:"Ready",idleText:"Waiting for your next video. Your computer takes it as soon as it arrives.",downloading:"Downloading",editing:"Editing",sending:"Sending",paused:"Paused",pausedText:"Your videos go to the cloud while the helper is paused.",
offline:"Offline",offlineText:"ClipRelay cannot be reached. Check the internet.",starting:"Starting",not_connected:"Not connected",working:"Working",
live:"Now on this computer",openVideo:"Open the video on YouTube",dl:"Download",ed:"Edit",sd:"Send",elapsed:"Working for",
pause:"Pause",resume:"Resume",membership:"Your plan",owner:"Owner: no limits",activeUntil:"Active until",trialUntil:"Free trial until",daysLeft:"days left",noEnd:"No end date",
ended:"Your plan has ended. Nothing is downloaded or edited until your manager gives you a plan.",suspended:"Your account is suspended. Contact your manager.",perDay:"videos a day",unlimited:"no daily limit",
dashboard:"Dashboard",onPc:"Edited on this PC",inCloud:"Edited in the cloud",editedAll:"Edited in all",published:"Published",thisMonth:"this month",
pcShare:"This PC",cloudShare:"Cloud",serverShare:"Server",recent:"Recent on this PC",none:"No video edited on this computer yet.",
computer:"This computer",account:"Account",server:"ClipRelay",pc:"Computer",session:"Edited since start",auto:"Start with my computer",
disconnect:"Disconnect",sure:"Disconnect this computer? Its videos go to the cloud until you connect it again.",
update:"A new version is ready:",download:"Download it",lastErr:"Last problem",keepOpen:"You can close this window: the helper keeps working from the ClipRelay icon next to the clock.",
st_awaiting_approval:"In review",st_ready:"Ready",st_scheduled:"Scheduled",st_posted:"Published",st_monitoring:"Published",st_clean:"Published",st_rewriting:"Caption",st_cancelled:"Cancelled",st_failed:"Failed",st_uploading:"Uploading"},
ur:{
connect:"Is computer ko jorein",connectHelp:"Aap ka computer ClipRelay ki videos khud download aur edit karega.",s1:"ClipRelay website par PC Helper kholein.",s2:"Connect a PC dabayein: wahan address aur code aata hai.",s3:"Dono yahan likhein aur Jorein dabayein.",
address:"ClipRelay ka address",code:"Code",name:"Is computer ka naam",go:"Jorein",
idle:"Tayyar",idleText:"Agli video ka intezar. Video aate hi aap ka computer use le lega.",downloading:"Download ho rahi",editing:"Edit ho rahi",sending:"Bheji ja rahi",paused:"Ruka hua",pausedText:"Helper ruka ho to aap ki videos cloud par jati hain.",
offline:"Offline",offlineText:"ClipRelay tak rabta nahi. Internet check karein.",starting:"Shuru ho raha",not_connected:"Jura hua nahi",working:"Kaam jaari",
live:"Abhi is computer par",openVideo:"YouTube par video kholein",dl:"Download",ed:"Edit",sd:"Bhejna",elapsed:"Kaam ka waqt",
pause:"Rokein",resume:"Dobara chalayein",membership:"Aap ka plan",owner:"Owner: koi had nahi",activeUntil:"Chalu hai",trialUntil:"Free trial",daysLeft:"din baqi",noEnd:"Khatam hone ki tareekh nahi",
ended:"Aap ka plan khatam ho gaya. Jab tak manager plan na de, kuch download ya edit nahi hoga.",suspended:"Aap ka account suspend hai. Manager se rabta karein.",perDay:"videos roz",unlimited:"roz ki koi had nahi",
dashboard:"Dashboard",onPc:"Is PC par edit huin",inCloud:"Cloud mein edit huin",editedAll:"Kul edit huin",published:"Publish huin",thisMonth:"is mahine",
pcShare:"Ye PC",cloudShare:"Cloud",serverShare:"Server",recent:"Is PC par haal hi mein",none:"Is computer par abhi koi video edit nahi hui.",
computer:"Ye computer",account:"Account",server:"ClipRelay",pc:"Computer",session:"Shuru se edit huin",auto:"Computer ke saath shuru ho",
disconnect:"Alag karein",sure:"Is computer ko alag karein? Jab tak dobara na jorein, iski videos cloud par jayengi.",
update:"Naya version tayyar hai:",download:"Download karein",lastErr:"Aakhri masla",keepOpen:"Ye window band kar sakte hain: helper ghari ke paas ClipRelay icon se kaam karta rahega.",
st_awaiting_approval:"Review mein",st_ready:"Tayyar",st_scheduled:"Schedule",st_posted:"Publish",st_monitoring:"Publish",st_clean:"Publish",st_rewriting:"Caption",st_cancelled:"Cancel",st_failed:"Fail",st_uploading:"Upload"}};
const L=()=>(S&&S.language)||"en";const t=k=>(T[L()]||T.en)[k]||T.en[k]||k;
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const busy=()=>["downloading","editing","sending"].includes(S.stage);
const day=d=>new Date(d).toLocaleDateString("en-GB",{day:"numeric",month:"long",year:"numeric"});
async function post(p,b){const r=await fetch(p+"?k="+K,{method:"POST",headers:{"Content-Type":"application/json","X-Helper":"1"},body:JSON.stringify(b||{})});const j=await r.json();if(!r.ok)throw new Error(j.error||"Error");S=j;last="";render();return j}
async function load(){try{const r=await fetch("/state?k="+K);const j=await r.json();const key=JSON.stringify(j);if(key!==last){last=key;S=j;render()}}catch(e){}}
function mood(){if(!S.connected)return"bad";if(S.paused||S.stage==="offline")return"warn";return busy()?"work":"ok"}
function stageLabel(){if(!S.connected)return t("not_connected");if(S.paused)return t("paused");return t(S.stage)}
function pill(){document.getElementById("pill").innerHTML=`<span class="dot ${mood()}"></span>${esc(stageLabel())}${busy()&&S.percent!=null?" · "+S.percent+"%":""}`}
function liveCard(){
 if(busy()){const order=["downloading","editing","sending"],i=order.indexOf(S.stage);
  const step=(n,k)=>`<div class="step ${n<i?"done":n===i?"now":""}"><i>${n<i?"✓":n+1}</i>${t(k)}</div>`;
  const mins=S.started_at?Math.max(0,Math.round((Date.now()/1000-S.started_at)/60)):0;
  const thumb=S.thumbnail?`<a class="thumb" href="${esc(S.link)}" target="_blank" rel="noopener" title="${t("openVideo")}"><img src="${esc(S.thumbnail)}" alt=""><div class="play"><span></span></div></a>`:"";
  return `<div class="card"><h2><span class="dot work"></span>${t("live")}</h2><div class="live">${thumb}<div class="live-main">
   ${S.channel?`<div class="channel">${esc(S.channel)}</div>`:""}${S.link?`<a class="title" href="${esc(S.link)}" target="_blank" rel="noopener">${esc(S.title)}</a>`:`<div class="title">${esc(S.title)}</div>`}
   ${S.link?`<a class="open" href="${esc(S.link)}" target="_blank" rel="noopener">${t("openVideo")} ↗</a>`:""}
   <div class="steps">${step(0,"dl")}${step(1,"ed")}${step(2,"sd")}</div>
   <div class="pct"><span>${esc(t(S.stage))}${S.message?" · "+esc(S.message):""}</span><b>${S.percent??0}%</b></div><div class="bar"><i style="width:${Math.max(2,S.percent||0)}%"></i></div>
   <div class="muted small">${t("elapsed")}: ${mins} min</div></div></div>
   <div class="row"><button class="btn" id="pz">${t("pause")}</button></div></div>`}
 const [title,text]=S.paused?[t("paused"),t("pausedText")]:S.stage==="offline"?[t("offline"),t("offlineText")]:[t("idle"),t("idleText")];
 return `<div class="card"><h2><span class="dot ${mood()}"></span>${t("live")}</h2><div class="idle"><div class="ring"><img alt="" src="data:image/svg+xml,__ICON__"></div><div><b>${esc(title)}</b><p>${esc(text)}</p>${S.message&&!S.paused?`<p class="small">${esc(S.message)}</p>`:""}</div></div>
  <div class="row"><button class="btn ${S.paused?"primary":""}" id="pz">${S.paused?t("resume"):t("pause")}</button></div></div>`}
function planCard(){const o=S.overview;if(!o)return `<div class="card"><h2>${t("membership")}</h2><div class="muted">…</div></div>`;const p=o.plan;
 const tier=p.owner?"owner":({"free trial":"free",bronze:"bronze",silver:"silver",gold:"gold",platinum:"platinum"})[p.name.toLowerCase()]||"free";
 let line="",bar="";
 if(p.owner)line=`<b>${t("owner")}</b>`;
 else if(p.ends_at){line=`${t(p.trial?"trialUntil":"activeUntil")} <b>${day(p.ends_at)}</b> · ${p.days_left} ${t("daysLeft")}`;const pct=Math.max(3,Math.min(100,(p.days_left/30)*100));bar=`<div class="days ${p.days_left<=5?"low":""}"><i style="width:${pct}%"></i></div>`}
 else line=`<span class="muted">${t("noEnd")}</span>`;
 const alert=p.blocked==="expired"?`<div class="alert">${t("ended")}</div>`:p.blocked==="suspended"?`<div class="alert">${t("suspended")}</div>`:"";
 return `<div class="card"><h2>${t("membership")}</h2><span class="plan-badge tier-${tier}">${esc(p.owner?"OWNER":p.name.toUpperCase())}</span>
  <div class="plan-line">${line}</div>${bar}${!p.owner?`<div class="muted small" style="margin-top:8px">${p.videos_per_day?p.videos_per_day+" "+t("perDay"):t("unlimited")}</div>`:""}
  <div class="muted small" style="margin-top:6px">${esc(o.account)}</div>${alert}</div>`}
function dashCard(){const o=S.overview;if(!o)return"";const ms=o.months||[];const m=ms[month]||ms[0];if(!m)return"";
 const name=v=>new Date(v+"-01T00:00:00").toLocaleDateString("en-GB",{month:"long",year:"numeric"});
 const server=Math.max(0,m.edited-m.edited_on_pc-m.edited_in_cloud),all=Math.max(1,m.edited);
 const tabs=ms.map((x,i)=>`<button data-m="${i}" class="${i===month?"on":""}">${esc(name(x.month))}</button>`).join("");
 return `<div class="card full"><h2>${t("dashboard")}<span class="months">${tabs}</span></h2><div class="tiles">
  <div class="tile hi"><span>${t("onPc")}</span><b>${m.edited_on_pc}</b><small>${month===0?t("thisMonth"):esc(name(m.month))}</small></div>
  <div class="tile"><span>${t("inCloud")}</span><b>${m.edited_in_cloud}</b><small>${month===0?t("thisMonth"):esc(name(m.month))}</small></div>
  <div class="tile"><span>${t("editedAll")}</span><b>${m.edited}</b><small>${month===0?t("thisMonth"):esc(name(m.month))}</small></div>
  <div class="tile"><span>${t("published")}</span><b>${m.published}</b><small>${month===0?t("thisMonth"):esc(name(m.month))}</small></div></div>
  <div class="share"><i style="width:${m.edited_on_pc/all*100}%;background:linear-gradient(90deg,#6c5ce7,#8b7cf7)"></i><i style="width:${m.edited_in_cloud/all*100}%;background:#38bdf8"></i><i style="width:${server/all*100}%;background:#64748b"></i></div>
  <div class="legend"><span><em style="background:#8b7cf7"></em>${t("pcShare")} ${m.edited_on_pc}</span><span><em style="background:#38bdf8"></em>${t("cloudShare")} ${m.edited_in_cloud}</span><span><em style="background:#64748b"></em>${t("serverShare")} ${server}</span></div></div>`}
function recentCard(){const o=S.overview;if(!o)return"";const r=o.recent||[];
 const rows=r.map(v=>{const st=v.status;const cls=["posted","monitoring","clean"].includes(st)?"ok":["awaiting_approval","ready","scheduled"].includes(st)?"p":"";
  return `<div class="item">${v.thumbnail?`<img src="${esc(v.thumbnail)}" alt="">`:""}<div class="grow">${v.url?`<a href="${esc(v.url)}" target="_blank" rel="noopener">${esc(v.title)}</a>`:`<b>${esc(v.title)}</b>`}<div class="meta">${v.edited_at?day(v.edited_at):""}</div></div><span class="tag ${cls}">${esc(t("st_"+st))}</span></div>`}).join("");
 return `<div class="card"><h2>${t("recent")}</h2><div class="list">${rows||`<div class="muted">${t("none")}</div>`}</div></div>`}
function pcCard(){const outdated=S.latest_version&&S.latest_version!==S.version;const dl=S.platform==="mac"?S.download_mac:S.download_windows;
 const link=dl&&dl.startsWith("/")?(S.server+dl):dl;
 return `<div class="card"><h2>${t("computer")}</h2><dl><dt>${t("account")}</dt><dd>${esc(S.account)}</dd><dt>${t("server")}</dt><dd>${esc(S.server)}</dd><dt>${t("pc")}</dt><dd>${esc(S.name)}</dd><dt>${t("session")}</dt><dd>${S.done_today}</dd>
  ${S.last_error?`<dt>${t("lastErr")}</dt><dd class="small">${esc(S.last_error)}</dd>`:""}</dl>
  <label class="switch"><input type="checkbox" id="au" ${S.starts_with_computer?"checked":""}> ${t("auto")}</label>
  ${outdated?`<div class="update">${t("update")} v${esc(S.latest_version)}${link?` · <a href="${esc(link)}" target="_blank" rel="noopener">${t("download")}</a>`:""}</div>`:""}
  <div class="row"><button class="btn danger" id="dc">${t("disconnect")}</button></div></div>`}
function render(){
 document.getElementById("ver").textContent="v"+S.version;pill();
 document.querySelectorAll(".lang button").forEach(b=>b.classList.toggle("on",b.dataset.l===L()));
 const app=document.getElementById("app");
 if(!S.connected){const keep={srv:document.getElementById("srv")?.value,code:document.getElementById("code")?.value,nm:document.getElementById("nm")?.value};
  app.innerHTML=`<div class="connect"><div class="card"><h1>${t("connect")}</h1><div class="muted">${t("connectHelp")}</div><ol><li>${t("s1")}</li><li>${t("s2")}</li><li>${t("s3")}</li></ol>
  <label>${t("address")}</label><input class="in" id="srv" placeholder="https://clips.example.com" value="${esc(keep.srv??S.server)}">
  <label>${t("code")}</label><input class="in code" id="code" placeholder="ABC-123" autocomplete="off" value="${esc(keep.code??"")}">
  <label>${t("name")}</label><input class="in" id="nm" value="${esc(keep.nm??S.name)}">
  <div class="row"><button class="btn primary" id="go">${t("go")}</button></div>${err?`<div class="err">${esc(err)}</div>`:""}</div></div>`;
  document.getElementById("go").onclick=async()=>{err="";try{await post("/connect",{server:srv.value,code:code.value,name:nm.value})}catch(e){err=e.message;render()}};return}
 app.innerHTML=`<div class="grid">${liveCard()}${planCard()}${dashCard()}${recentCard()}${pcCard()}</div><p class="note">${t("keepOpen")}</p>`;
 document.getElementById("pz").onclick=()=>post("/pause",{paused:!S.paused});
 document.getElementById("au").onchange=e=>post("/autostart",{on:e.target.checked});
 document.getElementById("dc").onclick=()=>{if(confirm(t("sure")))post("/disconnect")};
 document.querySelectorAll(".months button").forEach(b=>b.onclick=()=>{month=+b.dataset.m;render()});}
document.querySelectorAll(".lang button").forEach(b=>b.onclick=()=>post("/language",{language:b.dataset.l}));
load();setInterval(()=>{if(!S||S.connected)load()},2000);
</script></body></html>""".replace("__ICON__", quote(SVG))
