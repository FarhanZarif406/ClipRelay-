import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { credentials, settings, users } from "@/api/endpoints";
import type { NotificationSettings } from "@/api/types";
import { CredentialCard } from "@/components/CredentialCard";
import { ChannelOverrides, GlobalRules, RuleHistory } from "@/components/RulesEditor";
import MainSwitch from "@/components/MainSwitch";
import { Icon, type IconName } from "@/components/Icon";
import { Field } from "@/components/Modal";
import { useErrorToast, useToast } from "@/components/Toast";
import { Avatar, Badge, Button, Card, PageHeader, Toggle } from "@/components/ui";
import { useAuth } from "@/hooks/useAuth";
import { useTheme } from "@/hooks/useTheme";
import { initialsOf } from "@/lib/format";

const TABS = ["Main switch", "Pipeline rules", "Channel overrides", "Change history", "API keys", "Notifications", "Team members", "Appearance"] as const;
/** Tabs only the admin sees: the main switch, API keys and everything else that belongs to the whole workspace. */
const ADMIN_TABS: readonly string[] = ["Main switch", "API keys", "Notifications", "Team members"];
type Tab = (typeof TABS)[number];
/** Each tab's icon and what it holds, for the menu and the heading above the tab. */
const TAB_INFO: Record<Tab, { icon: IconName; text: string }> = {
  "Main switch": { icon: "pause", text: "Stop or start the whole tool for every member" },
  "Pipeline rules": { icon: "rules", text: "How new videos are found, limited, captioned and kept" },
  "Channel overrides": { icon: "filter", text: "Different rules for one of your channels" },
  "Change history": { icon: "clock", text: "Who changed which rule, and when" },
  "API keys": { icon: "link", text: "The workspace's own keys and services" },
  "Notifications": { icon: "bell", text: "Where alerts about failures are sent" },
  "Team members": { icon: "shield", text: "Owners and members of the workspace" },
  "Appearance": { icon: "sun", text: "Light or dark, for this browser" },
};

const CARD_KEYS = new Set(["llm", "ytdlp"]);  // the downloader has its own Video Source card

export function OtherIntegrations({ isOwner }: { isOwner: boolean }) {
  const { data } = useQuery({ queryKey: ["settings", "integrations"], queryFn: settings.integrations });
  const [results, setResults] = useState<Record<string, { ok: boolean; message: string }>>({});
  const test = useMutation({ mutationFn: (key: string) => settings.testIntegration(key), onSuccess: (r, key) => setResults(x => ({ ...x, [key]: r })) });
  return <Card><div className="card-title">Editor and storage</div><div className="card-caption">FFmpeg edits the videos and is installed with the app — no key is needed. “Test” runs a real test edit.</div>
    {data?.filter(x => !CARD_KEYS.has(x.key)).map(x => { const r = results[x.key]; return <div className="api-row" key={x.key}><div><strong>{x.name}</strong><span>{x.masked}</span></div>{r ? <span className={`test-result ${r.ok ? "ok" : "fail"}`}>{r.message}</span> : <Badge tone={x.configured ? "success" : "warning"}>{x.configured ? (x.source === "app" ? "Set in app" : x.key === "ytdlp" || x.key === "ffmpeg" ? "Installed" : x.source === "env" ? "From .env" : "Configured") : "Needs setup"}</Badge>}{isOwner && <Button onClick={() => test.mutate(x.key)} disabled={test.isPending && test.variables === x.key}>{test.isPending && test.variables === x.key ? "Testing…" : "Test"}</Button>}</div>; })}
  </Card>;
}

export function ApiKeys() {
  const { user } = useAuth();
  const isOwner = user?.role === "owner";
  const { data } = useQuery({ queryKey: ["credentials"], queryFn: credentials.list });
  return <>
    {!isOwner && <div className="form-note" style={{ marginTop: 0 }}>Only workspace owners can view or change API keys.</div>}
    {data?.filter(card => card.group !== "smtp").map(card => <CredentialCard key={card.group} card={card} isOwner={isOwner}></CredentialCard>)}
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
  const testEmail = useMutation({ mutationFn: settings.testEmail, onSuccess: r => toast({ title: r.ok ? "Test email sent" : "Test email failed", message: r.message, tone: r.ok ? "success" : "danger" }), onError });
  const { user } = useAuth();
  const isOwner = user?.role === "owner";
  const smtpCard = useQuery({ queryKey: ["credentials"], queryFn: credentials.list }).data?.find(c => c.group === "smtp");
  if (!draft) return null;
  const flag = (k: "notify_failures" | "notify_tokens", label: string, help: string) => <div className="setting-row"><div><strong>{label}</strong><span>{help}</span></div><Toggle checked={draft[k]} onChange={() => setDraft({ ...draft, [k]: !draft[k] })}/></div>;
  return <><Card><div className="card-title">Notifications</div><div className="card-caption">Alerts always appear in the dashboard. Add a webhook (Slack, Discord, or any HTTPS endpoint) and/or email to get them elsewhere.</div>
    <div style={{ marginTop: 16 }} className="field-row"><Field label="Webhook URL" hint="Receives JSON: {text, content, kind}."><input value={draft.webhook_url} onChange={e => setDraft({ ...draft, webhook_url: e.target.value })} placeholder="https://hooks.slack.com/services/…"/></Field>
      <Field label="Alert email" hint="Comma-separated. Needs the SMTP settings below."><input value={draft.email} onChange={e => setDraft({ ...draft, email: e.target.value })} placeholder="ops@example.com"/></Field></div>
    {flag("notify_failures", "Failed jobs", "When a job fails after all retries")}
    {flag("notify_tokens", "Key problems", "When a saved API key or an AI model stops working")}
    <div className="modal-foot"><Button onClick={() => test.mutate()} disabled={!data?.webhook_url || test.isPending}>Test webhook</Button><Button onClick={() => testEmail.mutate()} disabled={!data?.email || testEmail.isPending}>{testEmail.isPending ? "Sending…" : "Send test email"}</Button><Button variant="primary" onClick={() => save.mutate(draft)} disabled={save.isPending}>Save</Button></div>
  </Card>
  {smtpCard && <CredentialCard card={smtpCard} isOwner={isOwner} presets={[{ label: "Gmail preset", values: { host: "smtp.gmail.com", port: "587", security: "starttls" }, hint: "Gmail: use your full address as username and from address, and a 16-character app password (Google Account → Security → 2-Step Verification → App passwords)." }]}/>}
  </>;
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
  const [params] = useSearchParams();
  const isAdmin = user?.role === "owner";
  const tabs = TABS.filter(x => isAdmin || !ADMIN_TABS.includes(x));
  const wanted: Tab = params.get("tab") === "keys" ? "API keys" : "Pipeline rules";
  const [chosen, setTab] = useState<Tab>(wanted);
  const tab: Tab = tabs.includes(chosen) ? chosen : "Pipeline rules";
  return <><PageHeader title="Settings" description={isAdmin ? "Your own rules and accounts, plus the workspace's API keys, AI models and team." : "Your own rules and channel overrides. They apply only to your channels."}/><div className="settings-layout"><nav className="settings-nav" aria-label="Settings sections">{tabs.map(x => <button className={tab === x ? "active" : ""} key={x} onClick={() => setTab(x)} aria-current={tab === x ? "page" : undefined}><i><Icon name={TAB_INFO[x].icon} size={15}/></i><span><b data-i18n-skip>{x}</b><small>{TAB_INFO[x].text}</small></span></button>)}</nav><div className="settings-content">
    <div className="settings-head"><i><Icon name={TAB_INFO[tab].icon} size={19}/></i><div><b data-i18n-skip>{tab}</b><span>{TAB_INFO[tab].text}.</span></div></div>
    {tab === "Pipeline rules" && <>
      <Card><div className="card-title">Set in one place</div><div className="card-caption">These are not repeated here, so there is only one place to change each of them.</div>
        <div className="api-row plain"><div><strong>Shape, speed, sound, text and watermark</strong><span>The edit every video gets, and presets per channel</span></div><Link className="button secondary" to="/editing">Open Editing Rules</Link></div>
        <div className="api-row plain"><div><strong>Caption prompt</strong><span>What the AI model is asked to write</span></div><Link className="button secondary" to="/prompts">Open Prompt Studio</Link></div>
        <div className="api-row plain"><div><strong>Require approval</strong><span>Review each video, or publish automatically</span></div><Link className="button secondary" to="/review">Open Review Queue</Link></div></Card>
      <GlobalRules groups={["Detection", "Publishing", "Caption", "Storage"]} hideKeys={["approval_required"]} caption="Your own defaults: they apply to your channels only, not to other members. A change applies to the next video, with no restart. One of your channels can override most of them under “Channel overrides”."/>
    </>}
    {tab === "Main switch" && <>
      <MainSwitch/>
      <div className="switch-facts">
        {[["pause", "When it is off", "No channel is checked and push notifications are ignored. Nothing is downloaded, edited, captioned or handed to Buffer, for any member."],
          ["clock", "Videos on their way", "They are paused where they are, and carry on from there as soon as the system is on again."],
          ["arrow", "Posts at Buffer", "Posts already scheduled in Buffer still go out: Buffer publishes them itself."],
          ["bell", "What members see", "Members cannot switch it, but every page tells them the system is off."]].map(([icon, title, text]) =>
          <Card key={title} className="switch-fact"><span className="switch-fact-icon"><Icon name={icon as IconName} size={17}/></span><div><b>{title}</b><span>{text}</span></div></Card>)}
      </div>
    </>}
    {tab === "Channel overrides" && <ChannelOverrides/>}
    {tab === "Change history" && <RuleHistory/>}
    {tab === "API keys" && <ApiKeys/>}
    {tab === "Notifications" && <Notifications/>}
    {tab === "Team members" && <Team/>}
    {tab === "Appearance" && <Appearance/>}
  </div></div></>;
}
