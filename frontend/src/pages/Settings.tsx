import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { credentials, settings, users } from "@/api/endpoints";
import type { NotificationSettings } from "@/api/types";
import { AIModels } from "@/components/AIModels";
import { CredentialCard } from "@/components/CredentialCard";
import { Icon } from "@/components/Icon";
import { Field } from "@/components/Modal";
import { useErrorToast, useToast } from "@/components/Toast";
import { Avatar, Badge, Button, Card, PageHeader, Toggle } from "@/components/ui";
import { useAuth } from "@/hooks/useAuth";
import { useTheme } from "@/hooks/useTheme";
import { initialsOf } from "@/lib/format";

const TABS = ["API keys", "AI models", "Notifications", "Team members", "Appearance"] as const;
type Tab = (typeof TABS)[number];

function TikTokAuditToggle() {
  const queryClient = useQueryClient();
  const onError = useErrorToast();
  const { data: policy } = useQuery({ queryKey: ["policy"], queryFn: settings.policy });
  const save = useMutation({ mutationFn: (v: boolean) => settings.savePolicy({ tiktok_app_audited: v }), onSuccess: p => queryClient.setQueryData(["policy"], p), onError });
  return <div className="setting-inline"><div><strong>App audited</strong><span>Turn on once TikTok approves the app in the Content Posting audit. Until then posts are private (SELF_ONLY).</span></div><Toggle checked={!!policy?.tiktok_app_audited} onChange={() => policy && save.mutate(!policy.tiktok_app_audited)} label="App audited"/></div>;
}

/** Integrations that are configured on the server only (storage, FFmpeg) or elsewhere in Settings. */
const CARD_KEYS = new Set(["instagram", "tiktok", "llm", "transcription"]);

function OtherIntegrations({ isOwner }: { isOwner: boolean }) {
  const { data } = useQuery({ queryKey: ["settings", "integrations"], queryFn: settings.integrations });
  const [results, setResults] = useState<Record<string, { ok: boolean; message: string }>>({});
  const test = useMutation({ mutationFn: (key: string) => settings.testIntegration(key), onSuccess: (r, key) => setResults(x => ({ ...x, [key]: r })) });
  return <Card><div className="card-title">Other integrations</div><div className="card-caption">Storage and FFmpeg are configured in the server’s <code>.env</code> file.</div>
    {data?.filter(x => !CARD_KEYS.has(x.key)).map(x => { const r = results[x.key]; return <div className="api-row" key={x.key}><div><strong>{x.name}</strong><span>{x.masked}</span></div>{r ? <span className={`test-result ${r.ok ? "ok" : "fail"}`}>{r.message}</span> : <Badge tone={x.configured ? "success" : "warning"}>{x.configured ? (x.source === "app" ? "Set in app" : x.source === "env" ? "From .env" : "Configured") : "Needs setup"}</Badge>}{isOwner && <Button onClick={() => test.mutate(x.key)} disabled={test.isPending && test.variables === x.key}>{test.isPending && test.variables === x.key ? "Testing…" : "Test connection"}</Button>}</div>; })}
  </Card>;
}

function ApiKeys() {
  const { user } = useAuth();
  const isOwner = user?.role === "owner";
  const { data } = useQuery({ queryKey: ["credentials"], queryFn: credentials.list });
  return <>
    {!isOwner && <div className="form-note" style={{ marginTop: 0 }}>Only workspace owners can view or change API keys.</div>}
    {data?.map(card => <CredentialCard key={card.group} card={card} isOwner={isOwner}>{card.group === "tiktok" && isOwner ? <TikTokAuditToggle/> : null}</CredentialCard>)}
    <OtherIntegrations isOwner={isOwner}/>
  </>;
}

function Appearance() {
  const { theme, setTheme } = useTheme();
  return <Card><div className="card-title">Appearance</div><div className="card-caption">Choose how ClipRelay looks on this device.</div><div className="theme-options"><button className={theme === "dark" ? "active" : ""} onClick={() => setTheme("dark")}><div className="theme-preview dark-preview"><i/><i/><i/></div><span><Icon name="moon" size={16}/>Dark</span></button><button className={theme === "light" ? "active" : ""} onClick={() => setTheme("light")}><div className="theme-preview light-preview"><i/><i/><i/></div><span><Icon name="sun" size={16}/>Light</span></button></div></Card>;
}

function Notifications() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const { data } = useQuery({ queryKey: ["settings", "notifications"], queryFn: settings.notifications });
  const [draft, setDraft] = useState<NotificationSettings | null>(null);
  useEffect(() => { if (data) setDraft(data); }, [data]);
  const save = useMutation({ mutationFn: (body: Partial<NotificationSettings>) => settings.saveNotifications(body), onSuccess: d => { queryClient.setQueryData(["settings", "notifications"], d); toast({ title: "Notification settings saved" }); }, onError });
  const test = useMutation({ mutationFn: settings.testNotification, onSuccess: r => toast({ title: r.ok ? "Test sent" : "Test failed", message: r.message, tone: r.ok ? "success" : "danger" }), onError });
  if (!draft) return null;
  const flag = (k: "notify_violations" | "notify_failures" | "notify_tokens", label: string, help: string) => <div className="setting-row"><div><strong>{label}</strong><span>{help}</span></div><Toggle checked={draft[k]} onChange={() => setDraft({ ...draft, [k]: !draft[k] })}/></div>;
  return <Card><div className="card-title">Notifications</div><div className="card-caption">Alerts always appear in the dashboard. Add a webhook (Slack, Discord, or any HTTPS endpoint) to get them elsewhere.</div>
    <div style={{ marginTop: 16 }}><Field label="Webhook URL" hint="Receives JSON: {text, content, kind}."><input value={draft.webhook_url} onChange={e => setDraft({ ...draft, webhook_url: e.target.value })} placeholder="https://hooks.slack.com/services/…"/></Field></div>
    {flag("notify_violations", "Violations", "When TikTok flags or removes a video")}
    {flag("notify_failures", "Failed jobs", "When a job fails after all retries")}
    {flag("notify_tokens", "Token problems", "When a TikTok account needs reconnecting")}
    <div className="modal-foot"><Button onClick={() => test.mutate()} disabled={!data?.webhook_url || test.isPending}>Send test</Button><Button variant="primary" onClick={() => save.mutate(draft)} disabled={save.isPending}>Save</Button></div>
  </Card>;
}

function Team() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const { data } = useQuery({ queryKey: ["users"], queryFn: users.list });
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const create = useMutation({ mutationFn: () => users.create(form), onSuccess: () => { setForm({ name: "", email: "", password: "" }); queryClient.invalidateQueries({ queryKey: ["users"] }); toast({ title: "Team member added" }); }, onError });
  const remove = useMutation({ mutationFn: (id: number) => users.remove(id), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["users"] }), onError });
  const setRole = useMutation({ mutationFn: ({ id, role }: { id: number; role: "owner" | "member" }) => users.setRole(id, role), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["users"] }); toast({ title: "Role updated" }); }, onError });
  const isOwner = user?.role === "owner";
  const owners = data?.filter(u => u.role === "owner").length ?? 0;
  return <Card><div className="card-title">Team members</div><div className="card-caption">Owners manage API keys, AI models and the team. Members run the automation but only see whether keys are configured.</div>
    <div style={{ marginTop: 10 }}>{data?.map(u => <div className="team-row" key={u.id}><Avatar label={initialsOf(u.name || u.email)}/><div><strong>{u.name || u.email}{u.id === user?.id ? " (you)" : ""}</strong><span>{u.email}</span></div>
      <Badge tone={u.role === "owner" ? "primary" : "neutral"} dot={false}>{u.role === "owner" ? "Owner" : "Member"}</Badge>
      {isOwner && (u.role === "owner"
        ? <Button onClick={() => setRole.mutate({ id: u.id, role: "member" })} disabled={owners <= 1 || setRole.isPending} title={owners <= 1 ? "A workspace needs at least one owner" : undefined}>Make member</Button>
        : <Button onClick={() => setRole.mutate({ id: u.id, role: "owner" })} disabled={setRole.isPending}>Make owner</Button>)}
      {isOwner && u.id !== user?.id && <Button variant="danger" onClick={() => window.confirm(`Remove ${u.email}?`) && remove.mutate(u.id)}>Remove</Button>}</div>)}</div>
    {isOwner && <form className="inline-form" onSubmit={e => { e.preventDefault(); create.mutate(); }}><input className="input" placeholder="Name" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })}/><input className="input" type="email" required placeholder="Email" value={form.email} onChange={e => setForm({ ...form, email: e.target.value })}/><input className="input" type="password" required minLength={8} placeholder="Temporary password" value={form.password} onChange={e => setForm({ ...form, password: e.target.value })}/><Button type="submit" variant="primary" icon="plus" disabled={create.isPending}>Add member</Button></form>}
  </Card>;
}

export default function Settings() {
  const { user } = useAuth();
  const [tab, setTab] = useState<Tab>("API keys");
  return <><PageHeader title="Settings" description="Manage integrations, notifications, team access, and appearance."/><div className="settings-layout"><div className="settings-nav">{TABS.map(x => <button className={tab === x ? "active" : ""} key={x} onClick={() => setTab(x)}>{x}</button>)}</div><div className="settings-content">
    {tab === "API keys" && <><ApiKeys/><Appearance/></>}
    {tab === "AI models" && <AIModels isOwner={user?.role === "owner"}/>}
    {tab === "Notifications" && <Notifications/>}
    {tab === "Team members" && <Team/>}
    {tab === "Appearance" && <Appearance/>}
  </div></div></>;
}
