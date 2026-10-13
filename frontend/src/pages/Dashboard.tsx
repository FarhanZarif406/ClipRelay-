import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { dashboard } from "@/api/endpoints";
import type { ActivityLog, Kpi, Summary } from "@/api/types";
import { Menu } from "@/components/Menu";
import { Icon, type IconName } from "@/components/Icon";
import { Avatar, Badge, Button, Card, Empty, MiniBars, PageHeader, VideoThumb } from "@/components/ui";
import { useAuth } from "@/hooks/useAuth";
import { duration, greeting, longAgo, relativeTime } from "@/lib/format";
import { PODCASTS } from "@/lib/mode";

function kpiMeta(k: Kpi) {
  if (k.meta) return k.meta;
  if (k.delta === null || k.delta === undefined) return "0%";
  return `${k.delta > 0 ? "+" : k.delta < 0 ? "−" : ""}${Math.abs(k.delta)}%`;
}

/** Where each KPI card's "⋯" menu leads. */
const KPI_LINKS: Record<string, [string, string][]> = {
  fetched: [["View channels", "/channels"], ["View skipped videos", "/skipped"]],
  published: [["View published videos", "/published?status=published"], ["Open daily report", "/report"]],
  pending: [["Open review queue", "/review"], ["View videos waiting to upload", "/published?status=waiting"]],
  failed: [["View failed videos", "/published?status=failed"], ["Open logs", "/logs"]],
  removed: [["Open compliance audit", "/audit"]],
};

/** Pages the Podcasts window does not have. */
const HIDDEN_IN_PODCASTS = ["/audit", "/logs", "/channels?"];

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
    <div className="card-header"><div><div className="card-title">{PODCASTS ? "Clips published" : "Publishing performance"}</div><div className="card-caption">Uploads across all TikTok accounts</div></div><div className="segmented"><button className={days === 7 ? "active" : ""} onClick={() => setDays(7)}>7 days</button><button className={days === 30 ? "active" : ""} onClick={() => setDays(30)}>30 days</button></div></div>
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
    <div className="card-header"><div><div className="card-title">{PODCASTS ? "Clip status" : "Video status"}</div><div className="card-caption">Today’s distribution</div></div></div>
    <div className="donut-wrap"><div className="donut" style={{ background }}><div><strong>{total}</strong><span>{PODCASTS ? "Total clips" : "Total videos"}</span></div></div></div>
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
    <PageHeader title={`${greeting()}${firstName ? `, ${firstName}` : ""}`} description={PODCASTS ? "Podcasts workspace: long videos are cut into short clips and published to its own TikTok accounts." : "Here’s what your content network is doing today."}/>
    {summary && summary.attention.length > 0 && !dismissed && <div className="alert-banner"><div className="alert-icon"><Icon name="alert"/></div><div><strong>{summary.attention.length} TikTok token{summary.attention.length === 1 ? " needs" : "s need"} attention</strong><span>{summary.attention.map(a => a.status === "expiring" ? `@${a.username} expires ${relativeTime(a.refresh_expires_at)}` : `@${a.username} has expired`).join(" · ")}</span></div><button onClick={() => navigate("/tiktok")}>Review accounts <Icon name="arrow" size={15}/></button><button className="icon-button" onClick={() => setDismissed(true)}><Icon name="close" size={16}/></button></div>}
    {summary && !PODCASTS && summary.unacknowledged_violations > 0 && <div className="violation-list"><div className="violation-alert"><div className="alert-icon"><Icon name="shield"/></div><div><strong>{summary.unacknowledged_violations} video{summary.unacknowledged_violations === 1 ? " was" : "s were"} flagged by TikTok</strong><span>Review the violations and confirm removal in the Compliance Audit.</span></div><Button variant="danger" onClick={() => navigate("/audit")}>Review</Button></div></div>}
    <div className="kpi-grid">
      {(summary?.kpis ?? []).map(k => <Card className="kpi" key={k.key}><div className="kpi-label">{k.label}<Menu items={(KPI_LINKS[k.key] ?? []).filter(([, to]) => !PODCASTS || !HIDDEN_IN_PODCASTS.some(p => to.startsWith(p))).map(([label, to]) => ({ label, icon: "arrow" as const, onSelect: () => navigate(to) }))} trigger={toggle => <button type="button" className="kpi-more" aria-label={`${k.label} options`} onClick={toggle}><Icon name="more" size={16}/></button>}/></div><div className="kpi-value">{k.value.toLocaleString()}</div><div className={`kpi-meta ${k.tone}`}><span>{kpiMeta(k)}</span> vs. yesterday <MiniBars series={k.series}/></div></Card>)}
    </div>
    <div className="analytics-grid">
      <PerformanceChart/>
      {summary && <JobStatusCard summary={summary}/>}
    </div>
    <div className="bottom-grid">
      <Card className="full-row">
        <div className="card-header"><div><div className="card-title">Recent activity</div><div className="card-caption">Live updates from your automations</div></div>{!PODCASTS && <Button variant="ghost" onClick={() => navigate("/logs")}>View all <Icon name="arrow" size={14}/></Button>}</div>
        <div className="activity-list">
          {summary?.recent_activity.length === 0 && <Empty icon="clock" title="No activity yet">Events appear here as videos are processed and published.</Empty>}
          {summary?.recent_activity.map(entry => { const [icon, tone] = activityVisual(entry); return <div className="activity" key={entry.id}><div className={`activity-icon ${tone}`}><Icon name={icon} size={16}/></div><div><strong>{EVENT_TITLES[entry.event] ?? entry.service}</strong><span>{entry.message}</span></div><time>{relativeTime(entry.created_at)}</time></div>; })}
        </div>
      </Card>
    </div>
    {summary && <Card className="language-removals">
      <div className="card-header"><div><div className="card-title">Skipped videos</div><div className="card-caption">{PODCASTS ? `A podcast is a video of at least ${summary.rejections.min_source_duration_seconds} seconds. Shorter uploads are received and held; nothing is discarded.` : `Short-form means up to ${summary.rejections.max_duration_seconds} seconds (or any YouTube Short). Longer videos are received and held as long-form; nothing is discarded.`}</div></div><div className="language-summary"><div><strong>{summary.rejections.removed_today}</strong><span>Skipped today</span></div><div><strong>{summary.rejections.acceptance_rate === null ? "—" : `${summary.rejections.acceptance_rate}%`}</strong><span>Acceptance rate</span></div><Badge tone="success">{PODCASTS ? `${summary.rejections.min_source_duration_seconds}s or longer` : `Up to ${summary.rejections.max_duration_seconds}s`}</Badge><Button variant="ghost" onClick={() => navigate("/skipped")}>View all <Icon name="arrow" size={14}/></Button></div></div>
      {summary.rejections.items.length === 0 && <Empty icon="check" title="Nothing skipped yet"/>}
      {summary.rejections.items.length > 0 && <div className="table-wrap"><table><thead><tr><th>Video</th><th>Channel</th><th>Duration</th><th>Skipped</th><th>Reason</th></tr></thead><tbody>
        {summary.rejections.items.map((video, index) => <tr key={video.id}><td><div className="channel-cell"><VideoThumb index={index + 1} image={video.thumbnail_url} size={12}/><strong>{video.original_title || video.youtube_video_id || `Video ${video.id}`}</strong></div></td><td>{video.channel?.display_name ?? "—"}</td><td>{duration(video.duration_sec)}</td><td>{longAgo(video.created_at)}</td><td style={{ whiteSpace: "normal" }}>{video.rejection_reason}</td></tr>)}
      </tbody></table></div>}
    </Card>}
    {summary && <Card className="account-totals-card">
      <div className="card-header"><div><div className="card-title">Total uploads by connected account</div><div className="card-caption">Lifetime published video count for every TikTok account currently linked to this workspace.</div></div><Button variant="ghost" onClick={() => navigate("/report")}>Open daily report <Icon name="arrow" size={14}/></Button></div>
      {summary.accounts.length === 0 && <Empty icon="tiktok" title="No TikTok accounts connected"><Button variant="primary" icon="plus" onClick={() => navigate("/tiktok")}>Connect account</Button></Empty>}
      <div className="account-totals-grid">{summary.accounts.map(account => <div className="account-total" key={account.id}><Avatar label={account.initials} color={account.color}/><div><strong>@{account.username}</strong><span>{account.posts_today} uploaded today</span></div><div><strong>{account.lifetime_posts.toLocaleString()}</strong><span>Total uploads</span></div></div>)}</div>
    </Card>}
  </>;
}
