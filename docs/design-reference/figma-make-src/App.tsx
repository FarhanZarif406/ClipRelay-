import { useEffect, useMemo, useState, type ReactNode } from "react";

type Screen =
  | "Dashboard"
  | "Daily Report"
  | "Instagram Sources"
  | "TikTok Accounts"
  | "Automation Rules"
  | "Prompt Studio"
  | "Jobs Queue"
  | "Compliance Audit"
  | "Logs"
  | "Settings";

type TikTokAccount = {
  initials: string;
  handle: string;
  status: "Active" | "Expiring" | "Expired";
  posts: string;
  sources: string;
  color: string;
};

type IconName =
  | "grid"
  | "instagram"
  | "tiktok"
  | "rules"
  | "sparkles"
  | "queue"
  | "shield"
  | "logs"
  | "settings"
  | "search"
  | "play"
  | "bell"
  | "chevron"
  | "arrow"
  | "more"
  | "plus"
  | "clock"
  | "check"
  | "alert"
  | "close"
  | "filter"
  | "download"
  | "sun"
  | "moon"
  | "menu"
  | "link"
  | "code"
  | "refresh";

const iconPaths: Record<IconName, ReactNode> = {
  grid: <><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></>,
  instagram: <><rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="1"/></>,
  tiktok: <><path d="M14 4v11.2a4.2 4.2 0 1 1-3-4"/><path d="M14 4c1 3 2.8 4.2 5 4.4"/></>,
  rules: <><path d="M4 6h16M7 12h10M10 18h4"/><circle cx="8" cy="6" r="2"/><circle cx="15" cy="12" r="2"/><circle cx="12" cy="18" r="2"/></>,
  sparkles: <><path d="m12 3 1.2 3.8L17 8l-3.8 1.2L12 13l-1.2-3.8L7 8l3.8-1.2L12 3Z"/><path d="m5 14 .8 2.2L8 17l-2.2.8L5 20l-.8-2.2L2 17l2.2-.8L5 14Zm13-1 1 2.5 2.5 1-2.5 1-1 2.5-1-2.5-2.5-1 2.5-1 1-2.5Z"/></>,
  queue: <><path d="M6 5h15M6 12h15M6 19h15"/><circle cx="3" cy="5" r=".5"/><circle cx="3" cy="12" r=".5"/><circle cx="3" cy="19" r=".5"/></>,
  shield: <path d="M12 3 4.5 6v5.5c0 4.6 3.1 7.8 7.5 9.5 4.4-1.7 7.5-4.9 7.5-9.5V6L12 3Zm-3 9 2 2 4-4"/>,
  logs: <><path d="M5 4h14v16H5z"/><path d="M8 8h8M8 12h8M8 16h5"/></>,
  settings: <><circle cx="12" cy="12" r="3"/><path d="M19 13.5v-3l-2-.7-.5-1.2.9-1.9-2.1-2.1-1.9.9-1.2-.5-.7-2h-3l-.7 2-1.2.5-1.9-.9-2.1 2.1.9 1.9-.5 1.2-2 .7v3l2 .7.5 1.2-.9 1.9 2.1 2.1 1.9-.9 1.2.5.7 2h3l.7-2 1.2-.5 1.9.9 2.1-2.1-.9-1.9.5-1.2 2-.7Z"/></>,
  search: <><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></>,
  play: <path d="m9 7 8 5-8 5V7Z"/>,
  bell: <><path d="M18 9a6 6 0 0 0-12 0c0 7-3 7-3 7h18s-3 0-3-7"/><path d="M10 20h4"/></>,
  chevron: <path d="m9 7 5 5-5 5"/>,
  arrow: <path d="M5 12h14m-5-5 5 5-5 5"/>,
  more: <><circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/></>,
  plus: <path d="M12 5v14M5 12h14"/>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  check: <path d="m5 12 4 4L19 6"/>,
  alert: <><path d="M12 3 2.5 20h19L12 3Z"/><path d="M12 9v4m0 3v.2"/></>,
  close: <path d="m6 6 12 12M18 6 6 18"/>,
  filter: <path d="M4 6h16M7 12h10M10 18h4"/>,
  download: <path d="M12 3v13m-5-5 5 5 5-5M5 21h14"/>,
  sun: <><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></>,
  moon: <path d="M20 15.5A8.5 8.5 0 0 1 8.5 4 8.5 8.5 0 1 0 20 15.5Z"/>,
  menu: <path d="M4 7h16M4 12h16M4 17h16"/>,
  link: <path d="M10 13a5 5 0 0 0 7.5.5l2-2a5 5 0 0 0-7-7l-1.2 1.2M14 11a5 5 0 0 0-7.5-.5l-2 2a5 5 0 0 0 7 7l1.2-1.2"/>,
  code: <path d="m8 9-3 3 3 3m8-6 3 3-3 3m-5 3 2-12"/>,
  refresh: <><path d="M20 7v5h-5"/><path d="M19 12a7 7 0 1 0-2 5"/></>,
};

function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return <svg className="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{iconPaths[name]}</svg>;
}

function Button({ children, variant = "secondary", icon, onClick, className = "" }: { children?: ReactNode; variant?: "primary" | "secondary" | "ghost" | "danger"; icon?: IconName; onClick?: () => void; className?: string }) {
  return <button className={`button ${variant} ${className}`} onClick={onClick}>{icon && <Icon name={icon} size={16}/>} {children}</button>;
}

function Badge({ children, tone = "neutral", dot = true }: { children: ReactNode; tone?: "success" | "warning" | "danger" | "primary" | "neutral"; dot?: boolean }) {
  return <span className={`badge ${tone}`}>{dot && <i/>}{children}</span>;
}

function Toggle({ checked = true, onChange }: { checked?: boolean; onChange?: () => void }) {
  return <button aria-label="Toggle" className={`toggle ${checked ? "on" : ""}`} onClick={onChange}><span/></button>;
}

function Avatar({ label, color = "violet", image }: { label: string; color?: string; image?: boolean }) {
  return <div className={`avatar ${color} ${image ? "photo" : ""}`}>{label}</div>;
}

const navigation: { label: Screen; icon: IconName }[] = [
  { label: "Dashboard", icon: "grid" },
  { label: "Daily Report", icon: "logs" },
  { label: "Instagram Sources", icon: "instagram" },
  { label: "TikTok Accounts", icon: "tiktok" },
  { label: "Automation Rules", icon: "rules" },
  { label: "Prompt Studio", icon: "sparkles" },
  { label: "Jobs Queue", icon: "queue" },
  { label: "Compliance Audit", icon: "shield" },
  { label: "Logs", icon: "logs" },
  { label: "Settings", icon: "settings" },
];

const chartData = [34, 48, 40, 72, 63, 90, 82];

function lifetimeUploads(account: TikTokAccount) {
  return 420 + [...account.handle].reduce((total, character) => total + character.charCodeAt(0), 0) % 4200;
}

function uploadsToday(account: TikTokAccount) {
  return Number.parseInt(account.posts, 10) || 0;
}

const initialTikTokAccounts: TikTokAccount[] = [
  { initials: "NB", handle: "@northbound", status: "Active", posts: "18 / 30", sources: "4 sources", color: "blue" },
  { initials: "WC", handle: "@wildcuts", status: "Expiring", posts: "9 / 20", sources: "2 sources", color: "orange" },
  { initials: "MF", handle: "@moodframes", status: "Expired", posts: "0 / 15", sources: "1 source", color: "pink" },
  { initials: "CS", handle: "@cityscope", status: "Active", posts: "12 / 25", sources: "3 sources", color: "violet" },
];

const MAX_TIKTOK_ACCOUNTS = 20;
const MAX_INSTAGRAM_SOURCES = 7000;

const availableTikTokAccounts: TikTokAccount[] = [
  { initials: "TF", handle: "@trailfinder", status: "Active", posts: "0 / 20", sources: "0 sources", color: "green" },
  { initials: "FD", handle: "@fooddetours", status: "Active", posts: "0 / 25", sources: "0 sources", color: "orange" },
  { initials: "SO", handle: "@studiooutside", status: "Active", posts: "0 / 20", sources: "0 sources", color: "blue" },
  { initials: "WK", handle: "@weekendkit", status: "Active", posts: "0 / 15", sources: "0 sources", color: "pink" },
  { initials: "FF", handle: "@framefinder", status: "Active", posts: "0 / 20", sources: "0 sources", color: "violet" },
  { initials: "RO", handle: "@roamoffice", status: "Active", posts: "0 / 30", sources: "0 sources", color: "green" },
  { initials: "GT", handle: "@getawaytoday", status: "Active", posts: "0 / 20", sources: "0 sources", color: "blue" },
  { initials: "SD", handle: "@small.detours", status: "Active", posts: "0 / 20", sources: "0 sources", color: "orange" },
  { initials: "LM", handle: "@localmotion", status: "Active", posts: "0 / 25", sources: "0 sources", color: "pink" },
  { initials: "OH", handle: "@openhorizons", status: "Active", posts: "0 / 30", sources: "0 sources", color: "green" },
  { initials: "RR", handle: "@roadready", status: "Active", posts: "0 / 20", sources: "0 sources", color: "violet" },
  { initials: "ND", handle: "@nextdetour", status: "Active", posts: "0 / 25", sources: "0 sources", color: "blue" },
  { initials: "TS", handle: "@tiny.stories", status: "Active", posts: "0 / 15", sources: "0 sources", color: "orange" },
  { initials: "OG", handle: "@offgridguide", status: "Active", posts: "0 / 20", sources: "0 sources", color: "green" },
  { initials: "VP", handle: "@viewpoint", status: "Active", posts: "0 / 20", sources: "0 sources", color: "pink" },
  { initials: "MW", handle: "@motionweekend", status: "Active", posts: "0 / 25", sources: "0 sources", color: "violet" },
];

function PageHeader({ title, description, children }: { title: string; description: string; children?: ReactNode }) {
  return <div className="page-heading"><div><div className="eyebrow">CLIPRELAY</div><div className="page-title">{title}</div><div className="page-subtitle">{description}</div></div><div className="header-actions">{children}</div></div>;
}

function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`card ${className}`}>{children}</section>;
}

function MiniBars() {
  return <div className="mini-bars">{[4,8,5,10,7,12,9,13,8,11].map((n, i) => <i key={i} style={{ height: `${n * 2}px` }}/>)}</div>;
}

function Dashboard({ go, accounts }: { go: (s: Screen) => void; accounts: TikTokAccount[] }) {
  return <>
    <PageHeader title="Good morning, Alex" description="Here’s what your content network is doing today.">
      <Button icon="play" variant="primary">Run now</Button>
    </PageHeader>
    <div className="alert-banner"><div className="alert-icon"><Icon name="alert"/></div><div><strong>2 TikTok tokens need attention</strong><span>@northbound expires in 2 days · @moodframes has expired</span></div><button onClick={() => go("TikTok Accounts")}>Review accounts <Icon name="arrow" size={15}/></button><button className="icon-button"><Icon name="close" size={16}/></button></div>
    <div className="kpi-grid">
      {[
        ["Videos fetched", "128", "+18%", "primary"],
        ["Published", "84", "+12%", "success"],
        ["Pending", "16", "4 processing", "warning"],
        ["Failed", "3", "−40%", "danger"],
        ["Removed by audit", "2", "1.6% rate", "neutral"],
      ].map(([label, value, meta, tone]) => <Card className="kpi" key={label}><div className="kpi-label">{label}<Icon name="more" size={16}/></div><div className="kpi-value">{value}</div><div className={`kpi-meta ${tone}`}><span>{meta}</span> vs. yesterday <MiniBars/></div></Card>)}
    </div>
    <div className="analytics-grid">
      <Card className="chart-card">
        <div className="card-header"><div><div className="card-title">Publishing performance</div><div className="card-caption">Uploads across all TikTok accounts</div></div><div className="segmented"><button className="active">7 days</button><button>30 days</button></div></div>
        <div className="chart">
          <div className="y-labels"><span>120</span><span>80</span><span>40</span><span>0</span></div>
          <div className="plot">
            <div className="gridline g1"/><div className="gridline g2"/><div className="gridline g3"/>
            <svg viewBox="0 0 700 190" preserveAspectRatio="none"><defs><linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--primary)" stopOpacity=".28"/><stop offset="100%" stopColor="var(--primary)" stopOpacity="0"/></linearGradient></defs><path className="chart-area" d="M0 144 L116 119 L233 132 L350 76 L466 93 L583 35 L700 50 L700 190 L0 190Z"/><path className="chart-line" d="M0 144 L116 119 L233 132 L350 76 L466 93 L583 35 L700 50"/>{chartData.map((_,i)=><circle key={i} cx={i*116.66} cy={[144,119,132,76,93,35,50][i]} r="4"/>)}</svg>
            <div className="x-labels">{["Mon 12","Tue 13","Wed 14","Thu 15","Fri 16","Sat 17","Sun 18"].map(x=><span key={x}>{x}</span>)}</div>
          </div>
        </div>
      </Card>
      <Card className="status-card">
        <div className="card-header"><div><div className="card-title">Job status</div><div className="card-caption">Today’s distribution</div></div><button className="icon-button"><Icon name="more"/></button></div>
        <div className="donut-wrap"><div className="donut"><div><strong>105</strong><span>Total jobs</span></div></div></div>
        <div className="legend">{[["Published","84","success"],["Pending","16","primary"],["Failed","3","danger"],["Removed","2","warning"]].map(([x,n,c])=><div key={x}><span><i className={c}/>{x}</span><strong>{n}</strong></div>)}</div>
      </Card>
    </div>
    <div className="bottom-grid">
      <Card>
        <div className="card-header"><div><div className="card-title">Recent activity</div><div className="card-caption">Live updates from your automations</div></div><Button variant="ghost" onClick={()=>go("Logs")}>View all <Icon name="arrow" size={14}/></Button></div>
        <div className="activity-list">
          {[
            ["check","success","Video published","“3 hidden beaches in Crete…” to @northbound","2m"],
            ["sparkles","primary","Caption rewritten","Prompt “Travel short-form v3” applied","4m"],
            ["shield","warning","Video removed by language filter","Spanish detected in @urbanroamer video","11m"],
            ["alert","danger","Upload failed","Token expired for @moodframes","18m"],
          ].map(([icon,tone,title,desc,time])=><div className="activity" key={title}><div className={`activity-icon ${tone}`}><Icon name={icon as IconName} size={16}/></div><div><strong>{title}</strong><span>{desc}</span></div><time>{time}</time></div>)}
        </div>
      </Card>
      <Card className="schedule-card">
        <div className="card-title">Next scheduled run</div><div className="countdown"><div><strong>00</strong><span>HRS</span></div><i>:</i><div><strong>12</strong><span>MIN</span></div><i>:</i><div><strong>48</strong><span>SEC</span></div></div>
        <div className="schedule-detail"><span><Icon name="clock" size={16}/> Every 30 minutes</span><Badge tone="success">Active</Badge></div>
        <div className="source-stack"><span>Scanning</span><div><Avatar label="ST" color="blue"/><Avatar label="NW" color="orange"/><Avatar label="MF" color="pink"/></div><strong>6 sources</strong></div>
        <Button className="full" onClick={()=>go("Automation Rules")}>View automation rule</Button>
      </Card>
    </div>
    <Card className="language-removals">
      <div className="card-header"><div><div className="card-title">Removed by language filter</div><div className="card-caption">Fetched videos are transcribed first. Only Hindi and Urdu content continues to rewriting and publishing.</div></div><div className="language-summary"><div><strong>44</strong><span>Removed today</span></div><div><strong>65.6%</strong><span>Acceptance rate</span></div><Badge tone="success">Hindi + Urdu only</Badge></div></div>
      <div className="language-table">
        <div className="language-table-head"><span>Video</span><span>Source</span><span>Detected language</span><span>Transcript confidence</span><span>Removed</span><span>Reason</span></div>
        {[
          ["05","Morning market walk through Madrid","@urbanroamer","Spanish","98.4%","11 min ago"],
          ["02","A quiet café hidden in old Lisbon","@foundoutside","Portuguese","96.8%","24 min ago"],
          ["04","Three phrases to know before Tokyo","@slowtravel","Japanese","94.2%","38 min ago"],
        ].map((video,index)=><div className="language-row" key={video[1]}><div><div className={`video-thumb v${index+1}`}><Icon name="play" size={12}/><span>{video[0]}</span></div><strong>{video[1]}</strong></div><span>{video[2]}</span><Badge tone="warning">{video[3]}</Badge><span className="confidence"><i style={{width:video[4]}}/>{video[4]}</span><span>{video[5]}</span><span className="reason"><Icon name="close" size={13}/>Not Hindi or Urdu</span></div>)}
      </div>
    </Card>
    <Card className="account-totals-card">
      <div className="card-header"><div><div className="card-title">Total uploads by connected account</div><div className="card-caption">Lifetime published video count for every TikTok account currently linked to this workspace.</div></div><Button variant="ghost" onClick={()=>go("Daily Report")}>Open daily report <Icon name="arrow" size={14}/></Button></div>
      <div className="account-totals-grid">{accounts.map(account=><div className="account-total" key={account.handle}><Avatar label={account.initials} color={account.color}/><div><strong>{account.handle}</strong><span>{uploadsToday(account)} uploaded today</span></div><div><strong>{lifetimeUploads(account).toLocaleString()}</strong><span>Total uploads</span></div></div>)}</div>
    </Card>
  </>;
}

function DailyReport({ accounts }: { accounts: TikTokAccount[] }) {
  const totalToday = accounts.reduce((total, account) => total + uploadsToday(account), 0);
  const totalLifetime = accounts.reduce((total, account) => total + lifetimeUploads(account), 0);
  const activeAccounts = accounts.filter(account => account.status !== "Expired").length;
  return <><PageHeader title="Daily Report" description="A complete account-by-account summary of today’s publishing activity."><Button icon="download">Export report</Button></PageHeader>
    <div className="report-date"><div><Icon name="clock" size={16}/><span>Reporting period</span><strong>Today · May 18, 2025 · 00:00–23:59</strong></div><Badge tone="success">Live report</Badge></div>
    <div className="report-kpis">
      <Card><span>Videos uploaded today</span><strong>{totalToday}</strong><small>Across {accounts.length} connected accounts</small></Card>
      <Card><span>Active destinations</span><strong>{activeAccounts}</strong><small>{accounts.length - activeAccounts} account needs attention</small></Card>
      <Card><span>Lifetime uploads</span><strong>{totalLifetime.toLocaleString()}</strong><small>All currently connected accounts</small></Card>
      <Card><span>Language accepted</span><strong>84</strong><small>61 Hindi · 23 Urdu</small></Card>
      <Card><span>Filtered out today</span><strong>44</strong><small>Not Hindi or Urdu</small></Card>
    </div>
    <Card className="report-chart-card"><div className="card-header"><div><div className="card-title">Today’s upload pace</div><div className="card-caption">Successful uploads across all connected accounts by hour</div></div><div className="report-legend"><i/>Published <b/>Failed</div></div><div className="hourly-chart">{[18,26,16,34,42,31,55,48,69,62,78,52].map((height,index)=><div key={index}><span><i style={{height:`${height}%`}}/><b style={{height:`${index%4===0?8:3}%`}}/></span><small>{index*2}:00</small></div>)}</div></Card>
    <Card className="daily-account-report"><div className="card-header"><div><div className="card-title">Uploads by account</div><div className="card-caption">Every connected account is included, even when no video was uploaded today.</div></div><span className="report-updated"><Icon name="refresh" size={13}/>Updated just now</span></div>
      <div className="report-table-head"><span>Account</span><span>Status</span><span>Uploaded today</span><span>Share of today</span><span>Failed</span><span>Total uploaded</span></div>
      <div className="report-account-list">{accounts.map((account,index)=>{const today=uploadsToday(account);const share=totalToday?Math.round(today/totalToday*100):0;return <div className="report-account-row" key={account.handle}><div><Avatar label={account.initials} color={account.color}/><div><strong>{account.handle}</strong><span>{account.sources}</span></div></div><Badge tone={account.status==="Active"?"success":account.status==="Expiring"?"warning":"danger"}>{account.status}</Badge><strong className="today-count">{today} videos</strong><div className="share-bar"><span className="share-track"><i style={{width:`${share}%`}}/></span><span>{share}%</span></div><span className={index%5===1?"failed-count has-failures":"failed-count"}>{index%5===1?"1":"0"}</span><strong>{lifetimeUploads(account).toLocaleString()}</strong></div>})}</div>
    </Card>
  </>;
}

const sources = [
  ["ST","@slowtravel","2 min ago","34","Active","30 min","@northbound","blue"],
  ["FO","@foundoutside","14 min ago","18","Active","1 hour","@northbound, @wildcuts","orange"],
  ["MF","@moodframes","1 hour ago","7","Paused","30 min","@moodframes","pink"],
  ["DN","@daily.nature","2 hours ago","42","Active","15 min","@wildcuts","green"],
  ["UR","@urbanroamer","Yesterday","11","Active","1 hour","@cityscope","violet"],
];

function Sources({ openModal, totalSources }: { openModal: () => void; totalSources: number }) {
  const [selected, setSelected] = useState<number[]>([0,1]);
  return <><PageHeader title="Instagram Sources" description="Monitor up to 7,000 Instagram accounts by username or profile link."><div className="source-capacity-label"><strong>{totalSources.toLocaleString()}</strong><span>/ 7,000 connected</span></div><Button icon="plus" variant="primary" onClick={openModal}>Add accounts</Button></PageHeader>
    <Card className="source-capacity-card"><div className="source-capacity-icon"><Icon name="instagram" size={19}/></div><div><div className="card-title">Instagram source capacity</div><div className="card-caption">Username is the primary connection method. Use a profile link when an account has no available username.</div></div><div className="source-capacity-meter"><i style={{width:`${totalSources/MAX_INSTAGRAM_SOURCES*100}%`}}/></div><strong>{(MAX_INSTAGRAM_SOURCES-totalSources).toLocaleString()} slots available</strong><Button icon="plus" onClick={openModal}>Bulk add up to 30</Button></Card>
    <div className="toolbar"><div className="search-field"><Icon name="search" size={16}/><input placeholder="Search sources…"/></div><Button icon="filter">Filters</Button><div className="spacer"/><span className="muted">{selected.length} selected</span>{selected.length>0&&<><Button>Pause</Button><Button>Assign account</Button><Button variant="danger">Delete</Button></>}</div>
    <Card className="table-card"><div className="table-wrap"><table><thead><tr><th><input type="checkbox" checked={selected.length===sources.length} readOnly/></th><th>Instagram page</th><th>Last checked</th><th>Videos found</th><th>Status</th><th>Check interval</th><th>Linked TikTok</th><th/></tr></thead><tbody>
      {sources.map((s,i)=><tr key={s[1]}><td><input type="checkbox" checked={selected.includes(i)} onChange={()=>setSelected(x=>x.includes(i)?x.filter(n=>n!==i):[...x,i])}/></td><td><div className="identity"><Avatar label={s[0]} color={s[7]}/><div><strong>{s[1]}</strong><span>Instagram page</span></div></div></td><td>{s[2]}</td><td><strong>{s[3]}</strong></td><td><div className="toggle-label"><Toggle checked={s[4]==="Active"}/>{s[4]}</div></td><td>{s[5]}</td><td><div className="account-pill"><Avatar label="T" color="dark"/>{s[6]}</div></td><td><Button variant="ghost" icon="more"/></td></tr>)}
    </tbody></table></div></Card>
    <div className="mobile-cards">{sources.map((s,i)=><Card key={s[1]}><div className="mobile-source"><input type="checkbox" checked={selected.includes(i)} onChange={()=>setSelected(x=>x.includes(i)?x.filter(n=>n!==i):[...x,i])}/><Avatar label={s[0]} color={s[7]}/><div><strong>{s[1]}</strong><span>{s[2]} · {s[3]} videos</span></div><Toggle checked={s[4]==="Active"}/></div><div className="mobile-card-foot"><span>{s[5]}</span><span>{s[6]}</span></div></Card>)}</div>
  </>;
}

function Accounts({ accounts, connect, disconnect }: { accounts: TikTokAccount[]; connect: () => void; disconnect: (handle: string) => void }) {
  const routes = accounts.filter(account => account.status !== "Expired").slice(0, 3);
  const videos = [
    ["@slowtravel", "Hidden beaches in Crete", "VID-8294"],
    ["@foundoutside", "Cabin above the clouds", "VID-8295"],
    ["@daily.nature", "Waterfall trail reveal", "VID-8296"],
  ];
  return <><PageHeader title="TikTok Accounts" description="Connect up to 20 publishing destinations and manage them at any time."><div className="account-capacity"><strong>{accounts.length}</strong><span>/ 20 linked</span></div><Button icon="plus" variant="primary" onClick={connect}>{accounts.length >= MAX_TIKTOK_ACCOUNTS ? "Limit reached" : "Connect account"}</Button></PageHeader>
    <Card className="capacity-card"><div><div className="card-title">Account capacity</div><div className="card-caption">Each connected account receives its own unique video during every parallel publishing run.</div></div><div className="capacity-meter"><i style={{width:`${accounts.length * 5}%`}}/></div><strong>{MAX_TIKTOK_ACCOUNTS - accounts.length} slots available</strong></Card>
    <div className="account-grid">{accounts.map(a=><Card className="account-card" key={a.handle}><div className="account-top"><Avatar label={a.initials} color={a.color}/><Button variant="ghost" icon="more"/></div><strong className="account-name">{a.handle}</strong><Badge tone={a.status==="Active"?"success":a.status==="Expiring"?"warning":"danger"}>{a.status}</Badge><div className="meter-row"><span>Posts today</span><strong>{a.posts}</strong></div><div className="meter"><i style={{width:`${parseInt(a.posts)*3}%`}}/></div><div className="account-footer"><span><Icon name="link" size={15}/>{a.sources}</span>{a.status==="Expired"?<Button variant="primary" icon="refresh">Reconnect</Button>:<Button variant="danger" onClick={()=>disconnect(a.handle)}>Disconnect</Button>}</div></Card>)}
      {accounts.length < MAX_TIKTOK_ACCOUNTS && <button className="add-account-card" onClick={connect}><span><Icon name="plus" size={20}/></span><strong>Connect another account</strong><small>{MAX_TIKTOK_ACCOUNTS - accounts.length} of 20 slots available</small></button>}
    </div>
    <Card className="parallel-card"><div className="parallel-head"><div><div className="card-title">Unique parallel publishing</div><div className="card-caption">One run selects a different eligible Instagram video for every destination, then uploads them simultaneously.</div></div><Badge tone="success">Duplicate guard on</Badge></div>
      <div className="route-grid">{routes.map((account, index)=><div className="route-row" key={account.handle}><div className="route-source"><div className={`video-thumb v${index}`}><Icon name="play" size={13}/></div><div><span>UNIQUE VIDEO {index + 1}</span><strong>{videos[index][1]}</strong><small>{videos[index][0]} · {videos[index][2]}</small></div></div><div className="route-line"><i/><Icon name="arrow" size={15}/></div><div className="route-target"><Avatar label={account.initials} color={account.color}/><div><span>TIKTOK DESTINATION</span><strong>{account.handle}</strong><small>Uploads in parallel</small></div></div></div>)}</div>
      <div className="duplicate-note"><Icon name="shield" size={17}/><div><strong>Same-video protection</strong><span>ClipRelay reserves each selected video to one account before publishing begins. A video can never be assigned to multiple accounts in the same run.</span></div></div>
    </Card>
    <Card className="oauth-card"><div className="oauth-icon"><Icon name="tiktok" size={24}/></div><div><div className="card-title">Connect securely with TikTok</div><div className="card-caption">Add, disconnect, or replace accounts whenever you choose. ClipRelay only requests permissions to publish and inspect your videos.</div></div><div className="oauth-steps"><span className="done"><i>1</i>Permissions</span><b/><span><i>2</i>Connect</span><b/><span><i>3</i>Success</span></div></Card>
  </>;
}

function Rules() {
  const [paused,setPaused]=useState(false);
  return <><PageHeader title="Automation Rules" description="Define when, what, and where ClipRelay publishes."><div className="pause-control"><span>{paused?"All paused":"Automations live"}</span><Toggle checked={!paused} onChange={()=>setPaused(!paused)}/></div><Button icon="plus" variant="primary">New rule</Button></PageHeader>
    <div className="rules-layout"><Card className="rule-card"><div className="rule-head"><div className="rule-number">01</div><div><div className="card-title">Travel discovery pipeline</div><div className="card-caption">Last ran 12 minutes ago · 18 jobs created</div></div><Badge tone={paused?"neutral":"success"}>{paused?"Paused":"Active"}</Badge><Button variant="ghost" icon="more"/></div>
      <div className="builder"><div className="builder-label">WHEN</div><div className="builder-row"><div className="select-box"><Icon name="clock" size={16}/><span>Every 30 minutes</span><Icon name="chevron" size={14}/></div><div className="select-box"><span>09:00 — 22:00</span><Icon name="chevron" size={14}/></div><div className="days">{["M","T","W","T","F","S","S"].map((x,i)=><button className={i<5?"on":""} key={i}>{x}</button>)}</div></div>
      <div className="builder-label">IF</div><div className="condition"><span>Source page</span><b>is</b><div className="chip"><Avatar label="ST" color="blue"/>@slowtravel</div><strong>AND</strong><span>Duration</span><b>is under</b><div className="value-box">60 sec</div><Button variant="ghost" icon="plus"/></div>
      <div className="builder-label">TRANSCRIBE &amp; LANGUAGE GATE</div><div className="language-gate"><div className="gate-step"><span><Icon name="logs" size={15}/></span><div><strong>Transcribe video audio</strong><small>Runs immediately after fetch</small></div></div><Icon name="arrow" size={15}/><div className="gate-step"><span><Icon name="sparkles" size={15}/></span><div><strong>Detect transcript language</strong><small>Automatic language identification</small></div></div><Icon name="arrow" size={15}/><div className="gate-result"><span>CONTINUE ONLY IF</span><div><Badge tone="success">Hindi</Badge><b>OR</b><Badge tone="success">Urdu</Badge></div></div><div className="gate-reject"><Icon name="close" size={14}/><div><strong>All other languages</strong><small>Remove from processing</small></div></div></div>
      <div className="builder-label">THEN</div><div className="condition"><span>Use prompt</span><div className="chip"><Icon name="sparkles" size={14}/>Travel short-form v3</div><strong>AND</strong><span>Post to</span><div className="chip"><Avatar label="NB" color="dark"/>@northbound</div></div>
      <div className="rule-settings"><div><span>Daily cap</span><strong>30 posts</strong></div><div><span>Hourly cap</span><strong>4 posts</strong></div><div><span>Random delay</span><strong>2–8 minutes</strong></div><div><span>Timezone</span><strong>Europe/London</strong></div></div></div>
    </Card><Card className="rule-summary"><div className="card-title">Schedule summary</div><div className="clock-face"><div><strong>30</strong><span>minutes</span></div></div><div className="summary-row"><span>Active window</span><strong>09:00–22:00</strong></div><div className="summary-row"><span>Next run</span><strong>in 12 minutes</strong></div><div className="summary-row"><span>Estimated posts</span><strong>18–24 / day</strong></div><Button className="full">Edit schedule</Button></Card></div>
  </>;
}

function PromptStudio() {
  const [tab,setTab]=useState("Caption");
  return <><PageHeader title="Prompt Studio" description="Shape how AI rewrites your content for each channel."><Button>Version history</Button><Button variant="primary">Save prompt</Button></PageHeader>
    <div className="studio"><Card className="prompt-list"><div className="list-title">Your prompts <Button variant="ghost" icon="plus"/></div>{["Travel short-form v3","Punchy titles","Clean hashtags","Food discovery","Default rewrite"].map((p,i)=><button key={p} className={i===0?"active":""}><span><Icon name="sparkles" size={15}/></span><div><strong>{p}</strong><small>{i===0?"Default · edited 2h ago":"Edited last week"}</small></div>{i===0&&<Badge tone="primary" dot={false}>Default</Badge>}</button>)}</Card>
    <Card className="editor-card"><div className="editor-top"><div><div className="card-title">Travel short-form v3</div><div className="card-caption">Rewrite travel content for short-form discovery</div></div><Toggle/></div><div className="tabs">{["Title","Caption","Hashtags"].map(t=><button key={t} onClick={()=>setTab(t)} className={tab===t?"active":""}>{t}</button>)}</div><div className="variable-row"><span>Insert variable</span>{["{original_title}","{original_caption}","{original_tags}","{niche}"].map(v=><button key={v}>{v}</button>)}</div><textarea className="prompt-editor" value={`Rewrite the {original_caption} into a concise, engaging TikTok caption.\n\nKeep the tone curious and authentic. Lead with a strong hook, avoid clickbait, and make it feel native to the travel niche. Maximum 160 characters.`} readOnly/><div className="editor-foot"><span><Icon name="code" size={15}/> 38 words · GPT-4o mini</span><Button variant="primary" icon="play">Test prompt</Button></div></Card>
    <Card className="preview-card"><div className="card-title">Live preview</div><div className="preview-label">ORIGINAL</div><div className="preview-text">We found this amazing hidden beach on our trip around Crete. It took 40 minutes to hike down but was so worth it!</div><Icon name="arrow"/><div className="preview-label purple">REWRITTEN</div><div className="preview-text output">40 minutes off the trail, and Crete gave us this. Would you make the hike?</div><div className="hashtags">#crete #hiddengems #slowtravel #greece</div></Card></div>
  </>;
}

const jobs = [
  ["01","@slowtravel","3 hidden beaches in Crete that…","Crete’s best-kept secret is…","0:42","@northbound","Published","2m"],
  ["02","@foundoutside","A cabin in the middle of nowhere…","POV: your weekend looks like this…","0:18","@wildcuts","Checking","14m"],
  ["03","@daily.nature","Wait for the waterfall reveal…","Nature saved the best for last.","0:36","@northbound","Processing","18m"],
  ["04","@urbanroamer","This corner of Tokyo at night…","Tokyo after dark hits different.","0:28","@cityscope","Queued","22m"],
  ["05","@moodframes","A quiet morning by the sea…","Your reminder to slow down.","0:51","@moodframes","Failed","1h"],
];

function Jobs({ openDrawer }: { openDrawer: () => void }) {
  return <><PageHeader title="Jobs Queue" description="Track every video from discovery to publication."><Button icon="play" variant="primary">Process next</Button></PageHeader><div className="toolbar"><div className="search-field"><Icon name="search" size={16}/><input placeholder="Search jobs…"/></div>{["All statuses","All pages","All accounts","Today"].map(x=><button className="filter-select" key={x}>{x}<Icon name="chevron" size={13}/></button>)}</div>
    <Card className="table-card jobs-table"><div className="table-wrap"><table><thead><tr><th>Video</th><th>Source page</th><th>Original caption</th><th>Rewritten caption</th><th>Duration</th><th>Target</th><th>Status</th><th>Time</th><th/></tr></thead><tbody>{jobs.map((j,i)=><tr key={j[0]} onClick={openDrawer}><td><div className={`video-thumb v${i}`}><Icon name="play" size={14}/><span>{j[0]}</span></div></td><td><strong>{j[1]}</strong></td><td className="truncate">{j[2]}</td><td className="truncate">{j[3]}</td><td>{j[4]}</td><td>{j[5]}</td><td><Badge tone={j[6]==="Published"?"success":j[6]==="Failed"?"danger":j[6]==="Queued"?"neutral":"primary"}>{j[6]}</Badge></td><td>{j[7]}</td><td><Button variant="ghost" icon="more"/></td></tr>)}</tbody></table></div></Card>
    <div className="mobile-cards job-mobile">{jobs.map((j,i)=><Card key={j[0]}><div className="job-card-top"><div className={`video-thumb v${i}`}><Icon name="play" size={14}/></div><div><strong>{j[3]}</strong><span>{j[1]} → {j[5]}</span></div><Badge tone={j[6]==="Published"?"success":j[6]==="Failed"?"danger":"primary"}>{j[6]}</Badge></div><div className="mobile-card-foot"><span>{j[4]}</span><span>{j[7]} ago</span><Button onClick={openDrawer}>Details</Button></div></Card>)}</div>
  </>;
}

function Audit() {
  const audits=[["Hidden beaches in Crete","@northbound","18:42:16","Checking","blue",72],["Cabin in the middle of nowhere","@wildcuts","06:18:09","Warning","orange",28],["Wait for the waterfall reveal","@northbound","Complete","Clear","green",100],["Quiet morning by the sea","@moodframes","Removed","Violation","pink",100]];
  return <><PageHeader title="Compliance Audit" description="24-hour post-publication monitoring and automatic enforcement."><Button>Audit settings</Button></PageHeader><div className="audit-layout"><div className="audit-list">{audits.map((a,i)=><Card className="audit-item" key={a[0]}><div className={`audit-thumb ${a[4]}`}><Icon name="play"/></div><div className="audit-main"><div className="audit-title"><strong>{a[0]}</strong><Badge tone={a[3]==="Clear"?"success":a[3]==="Violation"?"danger":a[3]==="Warning"?"warning":"primary"}>{a[3]}</Badge></div><span>Published to {a[1]} · {i+2} hours ago</span><div className="checkpoint"><div className="progress" style={{width:`${a[5]}%`}}/>{["Published","1h","6h","12h","24h"].map((x,n)=><div className={n*25<=Number(a[5])?"done":""} key={x}><i><Icon name="check" size={10}/></i><span>{x}</span></div>)}</div></div><div className={`count-ring ${a[3].toLowerCase()}`}><strong>{a[2].split(":")[0]}</strong><span>{a[2].includes(":")?"hours left":a[2]}</span></div><Button variant="ghost" icon="chevron"/></Card>)}</div>
    <Card className="audit-settings"><div className="card-title">Audit settings</div><div className="setting-row"><div><strong>Auto-remove violations</strong><span>Immediately remove confirmed violations</span></div><Toggle/></div><div className="setting-row"><div><strong>Check frequency</strong><span>At 1h, 6h, 12h, and 24h</span></div><Button>Edit</Button></div><div className="setting-row"><div><strong>Notifications</strong><span>Telegram and email</span></div><Toggle/></div><div className="audit-stat"><Icon name="shield"/><div><strong>98.4%</strong><span>Compliance rate this month</span></div></div></Card></div></>;
}

function Logs() {
  return <><PageHeader title="Logs" description="Inspect system events and API activity."><Button icon="download">Export CSV</Button></PageHeader><div className="toolbar"><div className="search-field grow"><Icon name="search" size={16}/><input placeholder="Search messages or payloads…"/></div><button className="filter-select">All levels<Icon name="chevron" size={13}/></button><button className="filter-select">All services<Icon name="chevron" size={13}/></button></div><Card className="table-card"><div className="table-wrap"><table><thead><tr><th>Timestamp</th><th>Level</th><th>Service</th><th>Message</th><th>Request ID</th><th/></tr></thead><tbody>{[
    ["10:42:18.402","Info","Publisher","Video published successfully to @northbound","req_8f2a"],
    ["10:40:02.114","Info","AI rewrite","Caption generated in 842ms","req_7d1c"],
    ["10:31:44.922","Warning","TikTok API","Rate limit at 82% for @wildcuts","req_6b3e"],
    ["10:24:09.306","Error","OAuth","Access token expired for @moodframes","req_5a8f"],
    ["10:12:33.184","Info","Scraper","12 new videos found from @slowtravel","req_4e2d"],
  ].map(r=><tr key={r[4]}><td className="mono">{r[0]}</td><td><Badge tone={r[1]==="Info"?"neutral":r[1]==="Warning"?"warning":"danger"}>{r[1]}</Badge></td><td><strong>{r[2]}</strong></td><td>{r[3]}</td><td className="mono">{r[4]}</td><td><Icon name="chevron" size={15}/></td></tr>)}</tbody></table></div></Card></>;
}

function Settings({ theme, setTheme }: { theme: string; setTheme: (x:string)=>void }) {
  return <><PageHeader title="Settings" description="Manage integrations, notifications, team access, and appearance."/><div className="settings-layout"><div className="settings-nav">{["API keys","Notifications","Team members","Appearance"].map((x,i)=><button className={i===0?"active":""} key={x}>{x}</button>)}</div><div className="settings-content">
    <Card><div className="card-title">API keys</div><div className="card-caption">Connect the services that power your automation.</div>{[["Claude API","sk-ant-••••••••••••R42K","Connected"],["Scraping provider","scr_••••••••••••91QX","Connected"],["Cloud storage","s3_••••••••••••73LM","Needs test"]].map(x=><div className="api-row" key={x[0]}><div><strong>{x[0]}</strong><span>{x[1]}</span></div><Badge tone={x[2]==="Connected"?"success":"warning"}>{x[2]}</Badge><Button>Test connection</Button></div>)}</Card>
    <Card><div className="card-title">Appearance</div><div className="card-caption">Choose how ClipRelay looks on this device.</div><div className="theme-options"><button className={theme==="dark"?"active":""} onClick={()=>setTheme("dark")}><div className="theme-preview dark-preview"><i/><i/><i/></div><span><Icon name="moon" size={16}/>Dark</span></button><button className={theme==="light"?"active":""} onClick={()=>setTheme("light")}><div className="theme-preview light-preview"><i/><i/><i/></div><span><Icon name="sun" size={16}/>Light</span></button></div></Card>
  </div></div></>;
}

function AddModal({ close, addAccounts, availableSlots }: { close: () => void; addAccounts: (count: number) => void; availableSlots: number }) {
  const [method,setMethod]=useState<"username"|"link">("username");
  const [value,setValue]=useState("");
  const entries=value.split(/[\n,]+/).map(entry=>entry.trim()).filter(Boolean);
  const count=Math.min(entries.length,30,availableSlots);
  const overLimit=entries.length>30;
  const connect=()=>{if(count>0)addAccounts(count)};
  return <div className="overlay" onMouseDown={close}><div className="modal source-modal" onMouseDown={e=>e.stopPropagation()}><div className="modal-head"><div><div className="card-title">Add Instagram accounts</div><div className="card-caption">Connect up to 30 accounts at once. ClipRelay supports 7,000 sources in total.</div></div><Button variant="ghost" icon="close" onClick={close}/></div>
    <div className="connect-methods"><button className={method==="username"?"active":""} onClick={()=>{setMethod("username");setValue("")}}><span><Icon name="instagram" size={16}/></span><div><strong>By username</strong><small>Primary method · Recommended</small></div><Icon name="check" size={14}/></button><button className={method==="link"?"active":""} onClick={()=>{setMethod("link");setValue("")}}><span><Icon name="link" size={16}/></span><div><strong>By profile link</strong><small>For accounts without a username</small></div>{method==="link"&&<Icon name="check" size={14}/>}</button></div>
    <div className="bulk-label"><label>{method==="username"?"Instagram usernames":"Instagram profile links"}</label><span className={overLimit?"over":""}>{entries.length} / 30</span></div>
    <textarea value={value} onChange={event=>setValue(event.target.value)} placeholder={method==="username"?"@slowtravel\n@foundoutside\n@daily.nature\n…up to 30 usernames":"https://instagram.com/profile/123456\nhttps://instagram.com/profile/789012\n…up to 30 profile links"} autoFocus/>
    <div className={`validation-row ${overLimit?"invalid":""}`}><Icon name={overLimit?"alert":"check"} size={15}/>{overLimit?"Only the first 30 accounts can be connected in one batch":method==="username"?"Usernames will be validated and duplicates skipped":"Links will be resolved, validated, and duplicates skipped"}</div>
    <div className="bulk-summary"><div><strong>{count}</strong><span>Ready to connect</span></div><div><strong>{availableSlots.toLocaleString()}</strong><span>Workspace slots available</span></div><Badge tone="primary" dot={false}>Bulk connection</Badge></div>
    <div className="modal-foot"><Button onClick={close}>Cancel</Button><Button variant="primary" onClick={connect}>Connect {count || 0} account{count===1?"":"s"}</Button></div></div></div>;
}

function JobDrawer({ close }: { close: () => void }) {
  return <div className="drawer-overlay" onMouseDown={close}><aside className="drawer" onMouseDown={e=>e.stopPropagation()}><div className="drawer-head"><div><Badge tone="success">Published</Badge><div className="card-title">Job #CR-89042</div></div><Button variant="ghost" icon="close" onClick={close}/></div><div className="video-preview"><div className="play-big"><Icon name="play" size={24}/></div><span>0:42</span></div><div className="drawer-section"><div className="section-label">CONTENT TRANSFORMATION</div><div className="before-after"><div><span>ORIGINAL</span><p>3 hidden beaches in Crete that you need to visit this summer.</p></div><Icon name="arrow"/><div><span>REWRITTEN</span><p>Crete’s best-kept secret is 40 minutes off the trail. Would you make the hike?</p></div></div></div><div className="drawer-section"><div className="section-label">PROCESS TIMELINE</div><div className="timeline">{["Fetched from @slowtravel","Audio transcribed · 128 words","Language detected · Hindi · 98.7%","Passed filters · 42s · 84K views","Caption rewritten","Video downloaded","Uploaded to @northbound","Published successfully"].map((x,i)=><div className="timeline-item" key={x}><i><Icon name="check" size={11}/></i><div><strong>{x}</strong><span>Today, 10:{30+i*2}</span></div></div>)}</div></div><div className="drawer-actions"><Button>Cancel job</Button><Button variant="primary" icon="refresh">Retry job</Button></div></aside></div>;
}

function Onboarding({ close }: { close: () => void }) {
  const [step,setStep]=useState(1);
  const content=[["Add your first source","Connect an Instagram page for ClipRelay to monitor.","@","Instagram handle","@slowtravel"],["Connect TikTok","Choose where your rewritten videos should be published.","T","TikTok account","Connect with TikTok"],["Set your AI prompt","Choose how titles, captions, and tags should be rewritten.","✦","Prompt","Travel short-form v3"],["Choose a schedule","Decide how often ClipRelay should look for new videos.","◷","Frequency","Every 30 minutes"]];
  const c=content[step-1];
  return <div className="overlay onboarding-overlay"><div className="onboarding"><div className="onboarding-brand"><div className="brand-mark"><Icon name="play" size={16}/></div><span>ClipRelay</span></div><div className="stepper">{content.map((x,i)=><div className={i+1<=step?"active":""} key={x[0]}><i>{i+1<step?<Icon name="check" size={12}/>:i+1}</i><span>{x[0].split(" ").slice(0,2).join(" ")}</span></div>)}</div><div className="onboarding-body"><div className="onboarding-icon">{c[2]}</div><div className="onboarding-count">STEP {step} OF 4</div><div className="onboarding-title">{c[0]}</div><p>{c[1]}</p><label>{c[3]}</label><div className="onboarding-input">{c[4]}<Icon name="chevron" size={15}/></div></div><div className="onboarding-foot"><Button variant="ghost" onClick={close}>Skip setup</Button><span/><Button onClick={()=>setStep(Math.max(1,step-1))}>Back</Button><Button variant="primary" onClick={()=>step===4?close():setStep(step+1)}>{step===4?"Finish setup":"Continue"} <Icon name="arrow" size={15}/></Button></div></div></div>;
}

export default function App() {
  const [screen,setScreen]=useState<Screen>("Dashboard");
  const [theme,setTheme]=useState("dark");
  const [menu,setMenu]=useState(false);
  const [modal,setModal]=useState<"add"|"job"|"onboarding"|null>(null);
  const [toast,setToast]=useState(false);
  const [tiktokAccounts,setTikTokAccounts]=useState<TikTokAccount[]>(initialTikTokAccounts);
  const [instagramSourceCount,setInstagramSourceCount]=useState(684);
  useEffect(()=>{document.documentElement.dataset.theme=theme},[theme]);
  const connectTikTokAccount=()=>{
    if(tiktokAccounts.length>=MAX_TIKTOK_ACCOUNTS) return;
    const next=[...availableTikTokAccounts,...initialTikTokAccounts].find(candidate=>!tiktokAccounts.some(account=>account.handle===candidate.handle));
    if(next) setTikTokAccounts(accounts=>[...accounts,next]);
  };
  const disconnectTikTokAccount=(handle:string)=>setTikTokAccounts(accounts=>accounts.filter(account=>account.handle!==handle));
  const content=useMemo(()=>{
    if(screen==="Dashboard") return <Dashboard go={setScreen} accounts={tiktokAccounts}/>;
    if(screen==="Daily Report") return <DailyReport accounts={tiktokAccounts}/>;
    if(screen==="Instagram Sources") return <Sources openModal={()=>setModal("add")} totalSources={instagramSourceCount}/>;
    if(screen==="TikTok Accounts") return <Accounts accounts={tiktokAccounts} connect={connectTikTokAccount} disconnect={disconnectTikTokAccount}/>;
    if(screen==="Automation Rules") return <Rules/>;
    if(screen==="Prompt Studio") return <PromptStudio/>;
    if(screen==="Jobs Queue") return <Jobs openDrawer={()=>setModal("job")}/>;
    if(screen==="Compliance Audit") return <Audit/>;
    if(screen==="Logs") return <Logs/>;
    return <Settings theme={theme} setTheme={setTheme}/>;
  },[screen,theme,tiktokAccounts,instagramSourceCount]);
  const navigate=(s:Screen)=>{setScreen(s);setMenu(false);window.scrollTo(0,0)};
  const run=()=>{setToast(true);setTimeout(()=>setToast(false),2800)};
  return <div className="app-shell">
    <aside className={`sidebar ${menu?"open":""}`}><div className="brand"><div className="brand-mark"><Icon name="play" size={15}/></div><span>ClipRelay</span><Badge tone="primary" dot={false}>BETA</Badge><button className="mobile-close" onClick={()=>setMenu(false)}><Icon name="close"/></button></div><nav>{navigation.map(n=><button key={n.label} className={screen===n.label?"active":""} onClick={()=>navigate(n.label)}><Icon name={n.icon}/><span>{n.label}</span>{n.label==="Jobs Queue"&&<b>16</b>}{n.label==="Compliance Audit"&&<i/>}</button>)}</nav><div className="sidebar-bottom"><button className="usage" onClick={()=>setModal("onboarding")}><span><Icon name="sparkles" size={15}/>Monthly usage</span><strong>684 / 1,000 jobs</strong><div><i/></div><small>Reset in 12 days</small></button><div className="help"><Icon name="alert" size={16}/><div><strong>Need help?</strong><span>View documentation</span></div><Icon name="chevron" size={14}/></div></div></aside>
    <div className="workspace"><header className="topbar"><button className="menu-button" onClick={()=>setMenu(true)}><Icon name="menu"/></button><div className="mobile-brand"><div className="brand-mark"><Icon name="play" size={13}/></div>ClipRelay</div><div className="global-search"><Icon name="search" size={17}/><input placeholder="Search jobs, pages, accounts…"/><kbd>⌘ K</kbd></div><div className="top-actions"><Button variant="primary" icon="play" onClick={run}>Run now</Button><button className="icon-button notification"><Icon name="bell"/><i/></button><button className="theme-button" onClick={()=>setTheme(theme==="dark"?"light":"dark")}><Icon name={theme==="dark"?"sun":"moon"} size={17}/></button><button className="profile"><Avatar label="AS" color="violet"/><div><strong>Alex Smith</strong><span>Northstar Studio</span></div><Icon name="chevron" size={14}/></button></div></header><main>{content}</main></div>
    {menu&&<div className="sidebar-scrim" onClick={()=>setMenu(false)}/>}
    {modal==="add"&&<AddModal close={()=>setModal(null)} availableSlots={MAX_INSTAGRAM_SOURCES-instagramSourceCount} addAccounts={(count)=>{setInstagramSourceCount(current=>Math.min(MAX_INSTAGRAM_SOURCES,current+count));setModal(null)}}/>}
    {modal==="job"&&<JobDrawer close={()=>setModal(null)}/>}
    {modal==="onboarding"&&<Onboarding close={()=>setModal(null)}/>}
    {toast&&<div className="toast"><div><Icon name="check" size={16}/></div><span><strong>Automation started</strong>Scanning 6 Instagram sources now.</span><Button variant="ghost" icon="close" onClick={()=>setToast(false)}/></div>}
  </div>;
}
