import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { dashboard, prompts, settings, tiktok } from "@/api/endpoints";
import type { Policy } from "@/api/types";
import { Icon } from "@/components/Icon";
import { Menu } from "@/components/Menu";
import { useErrorToast, useToast } from "@/components/Toast";
import { Avatar, Badge, Button, Card, PageHeader, Toggle } from "@/components/ui";
import { DAYS, LANGUAGES, languageName } from "@/lib/format";

const TIMEZONES = ["UTC", "Europe/London", "Europe/Berlin", "America/New_York", "America/Chicago", "America/Los_Angeles", "Asia/Karachi", "Asia/Kolkata", "Asia/Dubai", "Asia/Dhaka", "Asia/Singapore", "Asia/Tokyo", "Australia/Sydney"];

export default function AutomationRules() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const policyQuery = useQuery({ queryKey: ["policy"], queryFn: settings.policy });
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
  const accountList = accounts.data?.items.filter(a => a.status === "active" || a.status === "expiring") ?? [];
  const defaultPrompt = promptList.data?.find(p => p.is_default);
  const [sh, sm] = draft.active_window_start.split(":").map(Number);
  const [eh, em] = draft.active_window_end.split(":").map(Number);
  const windowHours = Math.max(0, ((eh * 60 + em - (sh * 60 + sm) + 1440) % 1440 || 1440) / 60);
  const dailyCap = accountList.reduce((t, a) => t + a.daily_cap, 0);
  const estimate = Math.min(dailyCap, Math.round(draft.hourly_cap * windowHours * Math.max(1, accountList.length)));
  const jobsToday = summary.data ? Object.values(summary.data.distribution).reduce((a, b) => a + b, 0) : 0;

  return <><PageHeader title="Automation Rules" description="Define when, what, and where ClipRelay publishes."><div className="pause-control"><span>{paused ? "All paused" : "Automations live"}</span><Toggle checked={!paused} onChange={() => { set("automations_paused", !paused); save.mutate({ automations_paused: !paused }); }}/></div><Button icon="check" variant="primary" disabled={!dirty || save.isPending} onClick={() => save.mutate(draft)}>Save rule</Button></PageHeader>
    <div className="rules-layout"><Card className="rule-card"><div className="rule-head"><div className="rule-number">01</div><div><div className="card-title">{draft.name}</div><div className="card-caption">{jobsToday} jobs created today</div></div><Badge tone={paused ? "neutral" : "success"}>{paused ? "Paused" : "Active"}</Badge></div>
      <div className="builder"><div className="builder-label">WHEN</div><div className="builder-row">
        <div className="select-box"><input className="inline-input" type="time" value={draft.active_window_start} onChange={e => set("active_window_start", e.target.value)} aria-label="Window start"/><span>—</span><input className="inline-input" type="time" value={draft.active_window_end} onChange={e => set("active_window_end", e.target.value)} aria-label="Window end"/></div>
        <div className="days">{DAYS.map((x, i) => <button type="button" className={draft.active_days.includes(i) ? "on" : ""} key={i} onClick={() => set("active_days", draft.active_days.includes(i) ? draft.active_days.filter(d => d !== i) : [...draft.active_days, i].sort())}>{x}</button>)}</div></div>
        <div className="builder-label">IF</div><div className="condition"><span>Duration, daily caps, speed and flip</span><b>are set in</b><a className="chip" href="/settings?tab=rules" style={{ textDecoration: "none" }}><Icon name="settings" size={14}/>Settings → Pipeline rules</a></div>
        <div className="builder-label" style={{ display: "flex", alignItems: "center", gap: 8 }}>LANGUAGE GATE <Toggle checked={draft.language_gate_enabled} onChange={() => set("language_gate_enabled", !draft.language_gate_enabled)} label="Language gate"/></div>
        <div className="language-gate" style={{ opacity: draft.language_gate_enabled ? 1 : 0.45 }}><div className="gate-step"><span><Icon name="logs" size={15}/></span><div><strong>Read title &amp; caption</strong><small>Runs as soon as a video comes in</small></div></div><Icon name="arrow" size={15}/><div className="gate-step"><span><Icon name="sparkles" size={15}/></span><div><strong>Detect caption language</strong><small>Automatic language identification</small></div></div><Icon name="arrow" size={15}/>
          <div className="gate-result"><span>CONTINUE ONLY IF</span><div className="lang-chips">{draft.allowed_languages.map((l, i) => <span key={l} style={{ display: "contents" }}>{i > 0 && <b>OR</b>}<button type="button" style={{ border: 0, background: "none", padding: 0, cursor: "pointer" }} title="Remove" onClick={() => set("allowed_languages", draft.allowed_languages.filter(x => x !== l))}><Badge tone="success">{languageName(l)}</Badge></button></span>)}
            <Menu align="left" items={Object.entries(LANGUAGES).filter(([c]) => !draft.allowed_languages.includes(c)).map(([c, n]) => ({ label: n, onSelect: () => set("allowed_languages", [...draft.allowed_languages, c]) }))} trigger={t => <button type="button" className="badge" style={{ cursor: "pointer" }} onClick={t}>+</button>}/></div></div>
          <div className="gate-reject"><Icon name="close" size={14}/><div><strong>All other languages</strong><small>Remove from processing</small></div></div></div>
        <div className="builder-label">THEN</div><div className="condition"><span>Use prompt</span>
          <Menu align="left" items={(promptList.data ?? []).map(p => ({ label: p.name, active: p.is_default, onSelect: () => setDefaultPrompt.mutate(p.id) }))} trigger={t => <button type="button" className="chip" onClick={t} style={{ cursor: "pointer", color: "inherit" }}><Icon name="sparkles" size={14}/>{defaultPrompt?.name ?? "No prompt"}</button>}/>
          <strong>AND</strong><span>Post to</span>{accountList.slice(0, 3).map(a => <div className="chip" key={a.id}><Avatar label={a.initials} color="dark"/>@{a.username}</div>)}{accountList.length > 3 && <div className="chip">+{accountList.length - 3}</div>}{accountList.length === 0 && <div className="chip">no TikTok accounts</div>}
          <b>· each channel posts to its default account</b></div>
        <div className="rule-settings"><div><span>Daily cap</span><strong>{dailyCap} posts</strong></div><div><span>Hourly cap</span><strong><input className="inline-input" type="number" min={1} max={60} value={draft.hourly_cap} onChange={e => set("hourly_cap", Math.max(1, Number(e.target.value) || 1))} style={{ width: 34 }}/> posts</strong></div>
          <div><span>Random delay</span><strong><input className="inline-input" type="number" min={0} max={240} value={draft.random_delay_min_minutes} onChange={e => set("random_delay_min_minutes", Math.max(0, Number(e.target.value) || 0))} style={{ width: 28 }}/>–<input className="inline-input" type="number" min={0} max={240} value={draft.random_delay_max_minutes} onChange={e => set("random_delay_max_minutes", Math.max(0, Number(e.target.value) || 0))} style={{ width: 28 }}/> minutes</strong></div>
          <div><span>Timezone</span><strong><select className="inline-input" value={draft.timezone} onChange={e => set("timezone", e.target.value)}>{[...new Set([draft.timezone, ...TIMEZONES])].map(tz => <option key={tz} value={tz}>{tz}</option>)}</select></strong></div></div></div>
    </Card><Card className="rule-summary"><div className="card-title">Schedule summary</div><div className="clock-face"><div><strong>{Math.round(windowHours)}</strong><span>{Math.round(windowHours) === 1 ? "hour" : "hours"} a day</span></div></div><div className="summary-row"><span>Active window</span><strong>{draft.active_window_start}–{draft.active_window_end}</strong></div><div className="summary-row"><span>Status</span><strong>{paused ? "Paused" : "Live"}</strong></div><div className="summary-row"><span>Estimated posts</span><strong>up to {estimate} / day</strong></div></Card></div>
  </>;
}
