import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { dashboard } from "@/api/endpoints";
import type { ActivityLog, Kpi, Summary } from "@/api/types";
import { Icon, type IconName } from "@/components/Icon";
import { Avatar, Badge, Button, Card, Empty, MiniBars, PageHeader, VideoThumb } from "@/components/ui";
import { useAuth } from "@/hooks/useAuth";
import { greeting, languageName, longAgo, relativeTime } from "@/lib/format";

function kpiMeta(k: Kpi) {
  if (k.meta) return k.meta;
  if (k.delta === null || k.delta === undefined) return "0%";
  return `${k.delta > 0 ? "+" : k.delta < 0 ? "−" : ""}${Math.abs(k.delta)}%`;
}

const EVENT_TITLES: Record<string, string> = {
  published: "Video published", rewritten: "Caption rewritten", video_skipped: "Video skipped", video_detected: "New upload detected", downloaded: "Video downloaded", rendered: "Video rendered", caption_fallback: "Caption fallback used", channel_added: "Channel added", job_failed: "Upload failed",
  violation: "Violation detected", token_expired: "Token expired",
  tiktok_connected: "TikTok account connected", rate_limited: "Rate limit reached",
};

function activityVisual(entry: ActivityLog): [IconName, string] {
  if (entry.level === "error") return ["alert", "danger"];
  if (entry.level === "warning") return ["shield", "warning"];
  if (entry.event === "published") return ["check", "success"];
  if (entry.service === "AI rewrite") return ["sparkles", "primary"];
  if (entry.service === "OAuth") return ["link", "primary"];
  return ["clock", "neutral"];
}

function PerformanceChart() {
  const [days, setDays] = useState(7);
  const { data } = useQuery({ queryKey: ["dashboard", "performance", days], queryFn: () => dashboard.performance(days) });
  const values = data?.values ?? Array(days).fill(0);
  const labels = data?.labels ?? [];
  const rawStep = Math.max(...values, 1) / 3;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const niceStep = Math.max(10, ([1, 2, 2.5, 4, 5, 10].map(m => m * magnitude).find(s => s >= rawStep) ?? 10 * magnitude));
  const max = niceStep * 3;
  const step = 700 / Math.max(1, values.length - 1);
  const points = values.map((v, i) => [i * step, 190 - (v / max) * 170 - 10] as const);
  const line = points.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const labelEvery = Math.ceil(labels.length / 7);
  return <Card className="chart-card">
    <div className="card-header"><div><div className="card-title">Publishing performance</div><div className="card-caption">Uploads across all TikTok accounts</div></div><div className="segmented"><button className={days === 7 ? "active" : ""} onClick={() => setDays(7)}>7 days</button><button className={days === 30 ? "active" : ""} onClick={() => setDays(30)}>30 days</button></div></div>
    <div className="chart">
      <div className="y-labels">{[max, (max * 2) / 3, max / 3, 0].map(v => <span key={v}>{Math.round(v)}</span>)}</div>
      <div className="plot">
        <div className="gridline g1"/><div className="gridline g2"/><div className="gridline g3"/>
        <svg viewBox="0 0 700 190" preserveAspectRatio="none"><defs><linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--primary)" stopOpacity=".28"/><stop offset="100%" stopColor="var(--primary)" stopOpacity="0"/></linearGradient></defs>{points.length > 0 && <><path className="chart-area" d={`${line} L700 190 L0 190Z`}/><path className="chart-line" d={line}/></>}{days <= 7 && points.map(([x, y], i) => <circle key={i} cx={x} cy={y} r="4"><title>{`${labels[i]}: ${values[i]}`}</title></circle>)}</svg>
        <div className="x-labels">{labels.filter((_, i) => i % labelEvery === 0 || i === labels.length - 1).map(x => <span key={x}>{x}</span>)}</div>
      </div>
    </div>
  </Card>;
}

function JobStatusCard({ summary }: { summary: Summary }) {
  const d = summary.distribution;
  const total = d.published + d.pending + d.failed + d.removed;
  const pct = (n: number) => (total ? (n / total) * 100 : 0);
  const a = pct(d.published), b = a + pct(d.pending), c = b + pct(d.failed);
  const background = total ? `conic-gradient(var(--success) 0 ${a}%,var(--primary) ${a}% ${b}%,var(--danger) ${b}% ${c}%,var(--warning) ${c}%)` : "var(--surface-3)";
  return <Card className="status-card">
    <div className="card-header"><div><div className="card-title">Job status</div><div className="card-caption">Today’s distribution</div></div></div>
    <div className="donut-wrap"><div className="donut" style={{ background }}><div><strong>{total}</strong><span>Total jobs</span></div></div></div>
    <div className="legend">{([["Published", d.published, "success"], ["Pending", d.pending, "primary"], ["Failed", d.failed, "danger"], ["Removed", d.removed, "warning"]] as const).map(([x, n, cl]) => <div key={x}><span><i className={cl}/>{x}</span><strong>{n}</strong></div>)}</div>
  </Card>;
}

export default function Dashboard() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [dismissed, setDismissed] = useState(false);
  const { data: summary } = useQuery({ queryKey: ["dashboard", "summary"], queryFn: dashboard.summary, refetchInterval: 30_000 });
  const firstName = (user?.name || "").split(" ")[0];

  return <>
    <PageHeader title={`${greeting()}${firstName ? `, ${firstName}` : ""}`} description="Here’s what your content network is doing today."/>
    {summary && summary.attention.length > 0 && !dismissed && <div className="alert-banner"><div className="alert-icon"><Icon name="alert"/></div><div><strong>{summary.attention.length} TikTok token{summary.attention.length === 1 ? " needs" : "s need"} attention</strong><span>{summary.attention.map(a => a.status === "expiring" ? `@${a.username} expires ${relativeTime(a.refresh_expires_at)}` : `@${a.username} has expired`).join(" · ")}</span></div><button onClick={() => navigate("/tiktok")}>Review accounts <Icon name="arrow" size={15}/></button><button className="icon-button" onClick={() => setDismissed(true)}><Icon name="close" size={16}/></button></div>}
    {summary && summary.unacknowledged_violations > 0 && <div className="violation-list"><div className="violation-alert"><div className="alert-icon"><Icon name="shield"/></div><div><strong>{summary.unacknowledged_violations} video{summary.unacknowledged_violations === 1 ? " was" : "s were"} flagged by TikTok</strong><span>Review the violations and confirm removal in the Compliance Audit.</span></div><Button variant="danger" onClick={() => navigate("/audit")}>Review</Button></div></div>}
    <div className="kpi-grid">
      {(summary?.kpis ?? []).map(k => <Card className="kpi" key={k.key}><div className="kpi-label">{k.label}<Icon name="more" size={16}/></div><div className="kpi-value">{k.value.toLocaleString()}</div><div className={`kpi-meta ${k.tone}`}><span>{kpiMeta(k)}</span> vs. yesterday <MiniBars series={k.series}/></div></Card>)}
    </div>
    <div className="analytics-grid">
      <PerformanceChart/>
      {summary && <JobStatusCard summary={summary}/>}
    </div>
    <div className="bottom-grid">
      <Card className="full-row">
        <div className="card-header"><div><div className="card-title">Recent activity</div><div className="card-caption">Live updates from your automations</div></div><Button variant="ghost" onClick={() => navigate("/logs")}>View all <Icon name="arrow" size={14}/></Button></div>
        <div className="activity-list">
          {summary?.recent_activity.length === 0 && <Empty icon="clock" title="No activity yet">Events appear here as videos are processed and published.</Empty>}
          {summary?.recent_activity.map(entry => { const [icon, tone] = activityVisual(entry); return <div className="activity" key={entry.id}><div className={`activity-icon ${tone}`}><Icon name={icon} size={16}/></div><div><strong>{EVENT_TITLES[entry.event] ?? entry.service}</strong><span>{entry.message}</span></div><time>{relativeTime(entry.created_at)}</time></div>; })}
        </div>
      </Card>
    </div>
    {summary && <Card className="language-removals">
      <div className="card-header"><div><div className="card-title">{summary.rejections.language_gate_enabled ? "Removed by language filter" : "Removed by filters"}</div><div className="card-caption">{summary.rejections.language_gate_enabled ? `Each incoming video's title and caption are checked first. Only ${summary.rejections.allowed_languages.map(languageName).join(" and ")} content continues to rewriting and publishing.` : "Every incoming video is checked with ffprobe. Only videos under 60 seconds continue to rewriting and publishing."}</div></div><div className="language-summary"><div><strong>{summary.rejections.removed_today}</strong><span>Removed today</span></div><div><strong>{summary.rejections.acceptance_rate === null ? "—" : `${summary.rejections.acceptance_rate}%`}</strong><span>Acceptance rate</span></div><Badge tone="success">{summary.rejections.language_gate_enabled ? `${summary.rejections.allowed_languages.map(languageName).join(" + ")} only` : "Under 60s only"}</Badge></div></div>
      <div className="language-table">
        <div className="language-table-head"><span>Video</span><span>Detected language</span><span>Language confidence</span><span>Removed</span><span>Reason</span></div>
        {summary.rejections.items.length === 0 && <Empty icon="check" title="Nothing removed yet"/>}
        {summary.rejections.items.map((video, index) => { const conf = video.language_confidence != null ? `${(video.language_confidence * 100).toFixed(1)}%` : "—"; return <div className="language-row" key={video.id}><div><VideoThumb index={index + 1} image={video.thumbnail_url} label={String(video.id).padStart(2, "0").slice(-2)} size={12}/><strong>{video.original_title || video.original_caption || video.youtube_video_id || `Video ${video.id}`}</strong></div><Badge tone="warning">{video.detected_language ? languageName(video.detected_language) : video.duration_sec ? `${video.duration_sec.toFixed(0)}s` : "—"}</Badge><span className="confidence"><i style={{ width: conf }}/>{conf}</span><span>{longAgo(video.created_at)}</span><span className="reason"><Icon name="close" size={13}/>{video.rejection_reason}</span></div>; })}
      </div>
    </Card>}
    {summary && <Card className="account-totals-card">
      <div className="card-header"><div><div className="card-title">Total uploads by connected account</div><div className="card-caption">Lifetime published video count for every TikTok account currently linked to this workspace.</div></div><Button variant="ghost" onClick={() => navigate("/report")}>Open daily report <Icon name="arrow" size={14}/></Button></div>
      {summary.accounts.length === 0 && <Empty icon="tiktok" title="No TikTok accounts connected"><Button variant="primary" icon="plus" onClick={() => navigate("/tiktok")}>Connect account</Button></Empty>}
      <div className="account-totals-grid">{summary.accounts.map(account => <div className="account-total" key={account.id}><Avatar label={account.initials} color={account.color}/><div><strong>@{account.username}</strong><span>{account.posts_today} uploaded today</span></div><div><strong>{account.lifetime_posts.toLocaleString()}</strong><span>Total uploads</span></div></div>)}</div>
    </Card>}
  </>;
}
