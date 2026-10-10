import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { dashboard, prompts, settings, sources, tiktok } from "@/api/endpoints";
import type { Policy, Source } from "@/api/types";
import { Icon } from "@/components/Icon";
import { Menu } from "@/components/Menu";
import { INTERVAL_PRESETS } from "@/components/SourceEditModal";
import { useErrorToast, useToast } from "@/components/Toast";
import { Avatar, Badge, Button, Card, Empty, PageHeader, Toggle } from "@/components/ui";
import { DAYS, LANGUAGES, intervalLabel, languageName, relativeTime } from "@/lib/format";

const TIMEZONES = ["UTC", "Europe/London", "Europe/Berlin", "America/New_York", "America/Chicago", "America/Los_Angeles", "Asia/Karachi", "Asia/Kolkata", "Asia/Dubai", "Asia/Dhaka", "Asia/Singapore", "Asia/Tokyo", "Australia/Sydney"];

function SourceSchedules({ items }: { items: Source[] }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const update = useMutation({ mutationFn: ({ id, body }: { id: number; body: Parameters<typeof sources.update>[1] }) => sources.update(id, body), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["sources"] }), onError });
  const run = useMutation({ mutationFn: (s: Source) => sources.run(s.id), onSuccess: (_, s) => { toast({ title: "Run started", message: `Checking @${s.username} now.` }); queryClient.invalidateQueries({ queryKey: ["sources"] }); }, onError });
  const custom = (s: Source) => { const v = window.prompt(`Check @${s.username} every how many minutes? (5–10080)`, String(s.refresh_interval_minutes)); const n = Number(v); if (v && n >= 5 && n <= 10080) update.mutate({ id: s.id, body: { refresh_interval_minutes: n } }); };
  return <Card className="table-card source-schedules"><div className="card-header"><div><div className="card-title">Source schedules</div><div className="card-caption">Every source has its own refresh trigger. Changes apply on the next scheduler tick — no restart needed.</div></div></div>
    <div className="table-wrap"><table><thead><tr><th>Source</th><th>Refresh every</th><th>Next run</th><th>Last checked</th><th>Mode</th><th>Status</th><th/></tr></thead><tbody>
      {items.map(s => <tr key={s.id}><td><div className="identity"><Avatar label={s.initials} color={s.color}/><div><strong>@{s.username}</strong><span>{s.tiktok_accounts.map(a => `@${a.username}`).join(", ") || "No TikTok linked"}</span></div></div></td>
        <td><Menu align="left" items={[...INTERVAL_PRESETS.map(m => ({ label: intervalLabel(m), active: m === s.refresh_interval_minutes, onSelect: () => update.mutate({ id: s.id, body: { refresh_interval_minutes: m } }) })), { label: "Custom…", active: !INTERVAL_PRESETS.includes(s.refresh_interval_minutes), onSelect: () => custom(s) }]} trigger={t => <button type="button" className="interval-select" onClick={t}>{intervalLabel(s.refresh_interval_minutes)}<Icon name="chevron" size={12}/></button>}/></td>
        <td>{s.is_active ? relativeTime(s.next_run_at) : "Paused"}</td><td>{relativeTime(s.last_checked_at, { suffix: true })}</td><td>{s.approval_mode === "manual" ? "Manual approval" : "Auto-post"}</td>
        <td><div className="toggle-label"><Toggle checked={s.is_active} onChange={() => update.mutate({ id: s.id, body: { is_active: !s.is_active } })}/>{s.is_active ? "Active" : "Paused"}</div></td>
        <td><Button icon="play" onClick={() => run.mutate(s)}>Run now</Button></td></tr>)}
    </tbody></table></div>
    {items.length === 0 && <Empty icon="instagram" title="No sources yet">Connect Instagram accounts on the Instagram Sources page.</Empty>}
  </Card>;
}

export default function AutomationRules() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const schedulesRef = useRef<HTMLDivElement>(null);
  const policyQuery = useQuery({ queryKey: ["policy"], queryFn: settings.policy });
  const sourceList = useQuery({ queryKey: ["sources", "all"], queryFn: () => sources.list({ page_size: 500 }) });
  const accounts = useQuery({ queryKey: ["tiktok"], queryFn: tiktok.list });
  const promptList = useQuery({ queryKey: ["prompts"], queryFn: prompts.list });
  const summary = useQuery({ queryKey: ["dashboard", "summary"], queryFn: dashboard.summary });
  const [draft, setDraft] = useState<Policy | null>(null);
  useEffect(() => { if (policyQuery.data) setDraft(policyQuery.data); }, [policyQuery.data]);

  const save = useMutation({
    mutationFn: (body: Partial<Policy>) => settings.savePolicy(body),
    onSuccess: p => { queryClient.setQueryData(["policy"], p); queryClient.invalidateQueries({ queryKey: ["dashboard"] }); toast({ title: "Rule saved", message: "The scheduler picks up changes on its next tick." }); },
    onError,
  });
  const setDefaultPrompt = useMutation({ mutationFn: prompts.makeDefault, onSuccess: () => queryClient.invalidateQueries({ queryKey: ["prompts"] }), onError });

  if (!draft) return <PageHeader title="Automation Rules" description="Define when, what, and where ClipRelay publishes."/>;
  const set = <K extends keyof Policy>(k: K, v: Policy[K]) => setDraft(d => d && { ...d, [k]: v });
  const dirty = JSON.stringify(draft) !== JSON.stringify(policyQuery.data);
  const paused = draft.automations_paused;
  const allSources = sourceList.data?.items ?? [];
  const active = allSources.filter(s => s.is_active);
  const accountList = accounts.data?.items.filter(a => a.status === "active" || a.status === "expiring") ?? [];
  const defaultPrompt = promptList.data?.find(p => p.is_default);
  const [sh, sm] = draft.active_window_start.split(":").map(Number);
  const [eh, em] = draft.active_window_end.split(":").map(Number);
  const windowHours = Math.max(0, ((eh * 60 + em - (sh * 60 + sm) + 1440) % 1440 || 1440) / 60);
  const dailyCap = accountList.reduce((t, a) => t + a.daily_cap, 0);
  const estimate = Math.min(dailyCap, Math.round(draft.hourly_cap * windowHours * Math.max(1, accountList.length)));
  const lastRun = allSources.map(s => s.last_checked_at).filter(Boolean).sort().pop() ?? null;
  const jobsToday = summary.data ? Object.values(summary.data.distribution).reduce((a, b) => a + b, 0) : 0;

  return <><PageHeader title="Automation Rules" description="Define when, what, and where ClipRelay publishes."><div className="pause-control"><span>{paused ? "All paused" : "Automations live"}</span><Toggle checked={!paused} onChange={() => { set("automations_paused", !paused); save.mutate({ automations_paused: !paused }); }}/></div><Button icon="check" variant="primary" disabled={!dirty || save.isPending} onClick={() => save.mutate(draft)}>Save rule</Button></PageHeader>
    <div className="rules-layout"><Card className="rule-card"><div className="rule-head"><div className="rule-number">01</div><div><div className="card-title">{draft.name}</div><div className="card-caption">Last ran {relativeTime(lastRun, { suffix: true }).toLowerCase()} · {jobsToday} jobs created today</div></div><Badge tone={paused ? "neutral" : "success"}>{paused ? "Paused" : "Active"}</Badge></div>
      <div className="builder"><div className="builder-label">WHEN</div><div className="builder-row">
        <Menu align="left" items={[...INTERVAL_PRESETS.map(m => ({ label: `Every ${intervalLabel(m)}`, active: draft.default_interval_minutes === m, onSelect: () => set("default_interval_minutes", m) }))]} trigger={t => <button type="button" className="select-box" onClick={t}><Icon name="clock" size={16}/><span>Every {intervalLabel(draft.default_interval_minutes)}</span><Icon name="chevron" size={14}/></button>}/>
        <div className="select-box"><input className="inline-input" type="time" value={draft.active_window_start} onChange={e => set("active_window_start", e.target.value)} aria-label="Window start"/><span>—</span><input className="inline-input" type="time" value={draft.active_window_end} onChange={e => set("active_window_end", e.target.value)} aria-label="Window end"/></div>
        <div className="days">{DAYS.map((x, i) => <button type="button" className={draft.active_days.includes(i) ? "on" : ""} key={i} onClick={() => set("active_days", draft.active_days.includes(i) ? draft.active_days.filter(d => d !== i) : [...draft.active_days, i].sort())}>{x}</button>)}</div></div>
        <div className="builder-label">IF</div><div className="condition"><span>Source page</span><b>is</b>{active.slice(0, 3).map(s => <div className="chip" key={s.id}><Avatar label={s.initials} color={s.color}/>@{s.username}</div>)}{active.length > 3 && <div className="chip">+{active.length - 3} more</div>}{active.length === 0 && <div className="chip">any active source</div>}<strong>AND</strong><span>Duration</span><b>is under</b><div className="value-box"><input className="inline-input" type="number" min={5} max={60} value={draft.max_duration_sec} onChange={e => set("max_duration_sec", Math.min(60, Math.max(5, Number(e.target.value) || 60)))} style={{ width: 30 }}/> sec</div></div>
        <div className="builder-label" style={{ display: "flex", alignItems: "center", gap: 8 }}>LANGUAGE GATE <Toggle checked={draft.language_gate_enabled} onChange={() => set("language_gate_enabled", !draft.language_gate_enabled)} label="Language gate"/></div>
        <div className="language-gate" style={{ opacity: draft.language_gate_enabled ? 1 : 0.45 }}><div className="gate-step"><span><Icon name="logs" size={15}/></span><div><strong>Read title &amp; caption</strong><small>Runs immediately after fetch</small></div></div><Icon name="arrow" size={15}/><div className="gate-step"><span><Icon name="sparkles" size={15}/></span><div><strong>Detect caption language</strong><small>Automatic language identification</small></div></div><Icon name="arrow" size={15}/>
          <div className="gate-result"><span>CONTINUE ONLY IF</span><div className="lang-chips">{draft.allowed_languages.map((l, i) => <span key={l} style={{ display: "contents" }}>{i > 0 && <b>OR</b>}<button type="button" style={{ border: 0, background: "none", padding: 0, cursor: "pointer" }} title="Remove" onClick={() => set("allowed_languages", draft.allowed_languages.filter(x => x !== l))}><Badge tone="success">{languageName(l)}</Badge></button></span>)}
            <Menu align="left" items={Object.entries(LANGUAGES).filter(([c]) => !draft.allowed_languages.includes(c)).map(([c, n]) => ({ label: n, onSelect: () => set("allowed_languages", [...draft.allowed_languages, c]) }))} trigger={t => <button type="button" className="badge" style={{ cursor: "pointer" }} onClick={t}>+</button>}/></div></div>
          <div className="gate-reject"><Icon name="close" size={14}/><div><strong>All other languages</strong><small>Remove from processing</small></div></div></div>
        <div className="builder-label">THEN</div><div className="condition"><span>Use prompt</span>
          <Menu align="left" items={(promptList.data ?? []).map(p => ({ label: p.name, active: p.is_default, onSelect: () => setDefaultPrompt.mutate(p.id) }))} trigger={t => <button type="button" className="chip" onClick={t} style={{ cursor: "pointer", color: "inherit" }}><Icon name="sparkles" size={14}/>{defaultPrompt?.name ?? "No prompt"}</button>}/>
          <strong>AND</strong><span>Post to</span>{accountList.slice(0, 3).map(a => <div className="chip" key={a.id}><Avatar label={a.initials} color="dark"/>@{a.username}</div>)}{accountList.length > 3 && <div className="chip">+{accountList.length - 3}</div>}{accountList.length === 0 && <div className="chip">no TikTok accounts</div>}
          <b>· {draft.unique_video_per_account ? "one unique account per video" : "every linked account"}</b><Toggle checked={draft.unique_video_per_account} onChange={() => set("unique_video_per_account", !draft.unique_video_per_account)} label="Unique video per account"/></div>
        <div className="rule-settings"><div><span>Daily cap</span><strong>{dailyCap} posts</strong></div><div><span>Hourly cap</span><strong><input className="inline-input" type="number" min={1} max={60} value={draft.hourly_cap} onChange={e => set("hourly_cap", Math.max(1, Number(e.target.value) || 1))} style={{ width: 34 }}/> posts</strong></div>
          <div><span>Random delay</span><strong><input className="inline-input" type="number" min={0} max={240} value={draft.random_delay_min_minutes} onChange={e => set("random_delay_min_minutes", Math.max(0, Number(e.target.value) || 0))} style={{ width: 28 }}/>–<input className="inline-input" type="number" min={0} max={240} value={draft.random_delay_max_minutes} onChange={e => set("random_delay_max_minutes", Math.max(0, Number(e.target.value) || 0))} style={{ width: 28 }}/> minutes</strong></div>
          <div><span>Timezone</span><strong><select className="inline-input" value={draft.timezone} onChange={e => set("timezone", e.target.value)}>{[...new Set([draft.timezone, ...TIMEZONES])].map(tz => <option key={tz} value={tz}>{tz}</option>)}</select></strong></div></div></div>
    </Card><Card className="rule-summary"><div className="card-title">Schedule summary</div><div className="clock-face"><div><strong>{draft.default_interval_minutes >= 60 ? draft.default_interval_minutes / 60 : draft.default_interval_minutes}</strong><span>{draft.default_interval_minutes >= 60 ? (draft.default_interval_minutes === 60 ? "hour" : "hours") : "minutes"}</span></div></div><div className="summary-row"><span>Active window</span><strong>{draft.active_window_start}–{draft.active_window_end}</strong></div><div className="summary-row"><span>Next run</span><strong>{paused ? "Paused" : summary.data?.next_run.at ? relativeTime(summary.data.next_run.at) : "—"}</strong></div><div className="summary-row"><span>Estimated posts</span><strong>up to {estimate} / day</strong></div><Button className="full" onClick={() => schedulesRef.current?.scrollIntoView({ behavior: "smooth" })}>Edit schedule</Button></Card></div>
    <div ref={schedulesRef}><SourceSchedules items={allSources}/></div>
  </>;
}
