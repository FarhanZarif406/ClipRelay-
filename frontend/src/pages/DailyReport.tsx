import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { download } from "@/api/client";
import { dashboard } from "@/api/endpoints";
import { Icon } from "@/components/Icon";
import { useErrorToast } from "@/components/Toast";
import { Avatar, Badge, Button, Card, Empty, PageHeader } from "@/components/ui";
import { ACCOUNT_STATUS, languageName } from "@/lib/format";

const iso = (d: Date) => d.toISOString().slice(0, 10);

export default function DailyReport() {
  const [day, setDay] = useState(() => iso(new Date()));
  const onError = useErrorToast();
  const { data: report, dataUpdatedAt } = useQuery({ queryKey: ["report", day], queryFn: () => dashboard.daily(day), refetchInterval: 60_000 });
  const today = day === iso(new Date());
  const shift = (days: number) => { const d = new Date(`${day}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + days); setDay(iso(d)); };
  const accounts = report?.accounts ?? [];
  const total = report?.uploaded ?? 0;
  const maxHour = Math.max(1, ...(report?.hourly ?? []).map(h => h.published + h.failed));
  const attention = accounts.length - (report?.active_accounts ?? 0);
  const languages = Object.entries(report?.accepted_by_language ?? {}).map(([code, n]) => `${n} ${languageName(code === "n/a" ? null : code) === "—" ? "untagged" : languageName(code)}`).join(" · ");
  const label = new Date(`${day}T00:00:00Z`).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });

  return <><PageHeader title="Daily Report" description="A complete account-by-account summary of today’s publishing activity."><Button icon="download" onClick={() => download("/reports/daily.csv", `cliprelay-report-${day}.csv`, { day }).catch(onError)}>Export report</Button></PageHeader>
    <div className="report-date"><div><Icon name="clock" size={16}/><span>Reporting period</span><strong>{today ? "Today · " : ""}{label} · 00:00–23:59 UTC</strong></div><div><Button variant="ghost" onClick={() => shift(-1)} title="Previous day"><span style={{ display: "inline-flex", transform: "rotate(180deg)" }}><Icon name="chevron" size={14}/></span></Button>{!today && <Button variant="ghost" onClick={() => shift(1)} title="Next day"><Icon name="chevron" size={14}/></Button>}<Badge tone={today ? "success" : "neutral"}>{today ? "Live report" : "Archived"}</Badge></div></div>
    <div className="report-kpis">
      <Card><span>Videos uploaded {today ? "today" : "this day"}</span><strong>{total}</strong><small>Across {accounts.length} connected accounts</small></Card>
      <Card><span>Active destinations</span><strong>{report?.active_accounts ?? 0}</strong><small>{attention} account{attention === 1 ? " needs" : "s need"} attention</small></Card>
      <Card><span>Lifetime uploads</span><strong>{(report?.lifetime_uploads ?? 0).toLocaleString()}</strong><small>All currently connected accounts</small></Card>
      <Card><span>Videos accepted</span><strong>{report?.accepted ?? 0}</strong><small>{languages || "Passed all filters"}</small></Card>
      <Card><span>Filtered out {today ? "today" : ""}</span><strong>{report?.filtered_out ?? 0}</strong><small>Duration or language filter</small></Card>
    </div>
    <Card className="report-chart-card"><div className="card-header"><div><div className="card-title">{today ? "Today’s" : "Daily"} upload pace</div><div className="card-caption">Successful uploads across all connected accounts by hour</div></div><div className="report-legend"><i/>Published <b/>Failed</div></div><div className="hourly-chart">{(report?.hourly ?? Array.from({ length: 12 }, (_, i) => ({ hour: i * 2, published: 0, failed: 0 }))).map(h => <div key={h.hour} title={`${h.published} published · ${h.failed} failed`}><span><i style={{ height: `${(h.published / maxHour) * 100}%` }}/><b style={{ height: `${(h.failed / maxHour) * 100}%` }}/></span><small>{h.hour}:00</small></div>)}</div></Card>
    <Card className="daily-account-report"><div className="card-header"><div><div className="card-title">Uploads by account</div><div className="card-caption">Every connected account is included, even when no video was uploaded {today ? "today" : "that day"}.</div></div><span className="report-updated"><Icon name="refresh" size={13}/>Updated {dataUpdatedAt ? new Date(dataUpdatedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "just now"}</span></div>
      <div className="report-table-head"><span>Account</span><span>Status</span><span>Uploaded today</span><span>Share of today</span><span>Failed</span><span>Total uploaded</span></div>
      <div className="report-account-list">{accounts.length === 0 && <Empty icon="tiktok" title="No accounts connected"/>}{accounts.map(account => { const share = total ? Math.round((account.posts_today / total) * 100) : 0; const status = ACCOUNT_STATUS[account.status ?? "active"]; return <div className="report-account-row" key={account.id}><div><Avatar label={account.initials} color={account.color}/><div><strong>@{account.username}</strong><span>{account.lifetime_posts.toLocaleString()} lifetime uploads</span></div></div><Badge tone={status.tone}>{status.label}</Badge><strong className="today-count">{account.posts_today} videos</strong><div className="share-bar"><span className="share-track"><i style={{ width: `${share}%` }}/></span><span>{share}%</span></div><span className={account.failed_today ? "failed-count has-failures" : "failed-count"}>{account.failed_today}</span><strong>{account.lifetime_posts.toLocaleString()}</strong></div>; })}</div>
    </Card>
  </>;
}
