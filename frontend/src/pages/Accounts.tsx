import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { accounts } from "@/api/endpoints";
import type { Account, FeatureValue, PlanInput, PlanList, PlanRow } from "@/api/types";
import { AIModels } from "@/components/AIModels";
import { SecretInput } from "@/components/CredentialCard";
import { YouTubeKeyCard } from "@/components/YouTubeKeyCard";
import { Menu } from "@/components/Menu";
import { Field, Modal } from "@/components/Modal";
import { useErrorToast, useToast } from "@/components/Toast";
import { Avatar, Badge, Button, Card, Empty, PageHeader, Spinner, Toggle } from "@/components/ui";
import { initialsOf } from "@/lib/format";

const message = (error: unknown) => (error instanceof Error ? error.message : String(error));
const day = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
/** A date input's "2026-12-31" as the end of that day, and back. */
const toEnd = (value: string) => (value ? new Date(`${value}T23:59:59`).toISOString() : null);
const toInput = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("en-CA") : "");
/** A limit as shown on a plan: 0 means no limit, except for the auto-check, where it means push only. */
const limitText = (key: string, value: number) => (key === "auto_check_minutes" ? (value ? `Every ${value} min` : "Push only") : key === "trial_days" ? (value ? `${value} days, then stops` : "No end") : key === "skipped_keep_hours" ? (value ? `Cleared after ${value} h` : "Kept") : value ? String(value) : "No limit");

/** A plan switch in three steps: off, on for the plan's first day only, or on. */
function FeatureChoice({ value, onChange }: { value: FeatureValue; onChange: (v: FeatureValue) => void }) {
  const options: [FeatureValue, string][] = [[false, "Off"], ["first_day", "First day"], [true, "On"]];
  return <div className="feature-choice" role="radiogroup">{options.map(([v, label]) =>
    <button key={label} type="button" role="radio" aria-checked={value === v} className={value === v ? "on" : ""} onClick={e => { e.preventDefault(); onChange(v); }}>{label}</button>)}</div>;
}
const featureText = (v: FeatureValue) => (v === "first_day" ? "first day only" : v ? "on" : "off");

function PlanSelect({ list, value, onChange }: { list: PlanList; value: number | null; onChange: (id: number | null) => void }) {
  const fallback = list.plans.find(p => p.is_default);
  return <select value={value ?? ""} onChange={e => onChange(e.target.value ? Number(e.target.value) : null)}>
    <option value="">Default plan{fallback ? ` (${fallback.name})` : ""}</option>
    {list.plans.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
  </select>;
}

/** The plan an account is on: the chosen one, or the default one. */
const planOf = (list: PlanList, id: number | null) => list.plans.find(p => p.id === id) ?? list.plans.find(p => p.is_default) ?? list.plans[0];

/**
 * This account's own switches and limits, A to Z: they start as its plan's, and the owner can raise or lower any of
 * them for this account alone. A changed one is marked Custom and can be put back to the plan's.
 */
function MemberLimits({ list, plan, features, limits, touched, onFeature, onLimit, onReset, onResetAll }: {
  list: PlanList; plan: PlanRow | undefined; features: Record<string, FeatureValue>; limits: Record<string, number>; touched: Set<string>;
  onFeature: (key: string, value: FeatureValue) => void; onLimit: (key: string, value: number) => void; onReset: (key: string) => void; onResetAll: () => void;
}) {
  const isFeature = (key: string) => list.features.some(f => f.key === key);
  const custom = (key: string) => touched.has(key) && (isFeature(key) ? (features[key] ?? false) !== (plan?.features[key] ?? false) : limits[key] !== (plan?.limits[key] ?? 0));
  const changed = [...touched].filter(custom).length;
  return <div className="member-limits">
    <div className="member-limits-head"><div><b>Limits for this account</b><small>{`They start as the ${plan?.name ?? ""} plan's. Raise or lower any of them for this account only; the plan itself does not change.`}</small></div>
      {changed > 0 && <Button onClick={onResetAll}>{`Reset all to the plan (${changed})`}</Button>}</div>
    <div className="section-label">Features</div>
    <div className="plan-switches">{list.features.map(f => <div className={`plan-switch ${custom(f.key) ? "is-custom" : ""}`} key={f.key}>
      <div><b>{f.label}{custom(f.key) && <span className="custom-tag">Custom</span>}</b><small>{custom(f.key) ? `The plan has it ${featureText(plan?.features[f.key] ?? false)}.` : f.help}</small>
        <FeatureChoice value={features[f.key] ?? false} onChange={v => onFeature(f.key, v)}/>
        {custom(f.key) && <button type="button" className="link-button" onClick={e => { e.preventDefault(); onReset(f.key); }}>Reset to plan</button>}</div></div>)}</div>
    <div className="section-label">Limits</div>
    <div className="plan-limits">{list.limits.map(l => <div key={l.key} className={custom(l.key) ? "is-custom" : ""}>
      <Field label={l.label} tag={custom(l.key) ? <span className="custom-tag">Custom</span> : undefined}
        hint={`Plan: ${limitText(l.key, plan?.limits[l.key] ?? 0)}.${["auto_check_minutes", "trial_days", "skipped_keep_hours"].includes(l.key) ? "" : " 0 = no limit."}`}>
        <div className="lookup-row"><input type="number" min={0} max={l.max} value={Number.isNaN(limits[l.key]) ? "" : limits[l.key]}
          onChange={e => onLimit(l.key, e.target.value === "" ? NaN : Number(e.target.value))}/>
          {custom(l.key) && <Button onClick={() => onReset(l.key)}>Reset</Button>}</div></Field></div>)}</div>
  </div>;
}

/** A new account, or the plan, name and password of an existing one, with any of its limits changed for it alone. */
function AccountModal({ list, account, onClose }: { list: PlanList; account?: Account; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState(account?.name ?? "");
  const [email, setEmail] = useState(account?.email ?? "");
  const [password, setPassword] = useState("");
  const [planId, setPlanId] = useState<number | null>(account?.plan_id ?? null);
  const [expires, setExpires] = useState(() => {
    if (account) return toInput(account.plan_expires_at);
    const days = planOf(list, null)?.limits.trial_days;  // a new account starts on the default plan
    return days ? new Date(Date.now() + days * 86_400_000).toLocaleDateString("en-CA") : "";
  })
  const [error, setError] = useState("");
  const plan = planOf(list, planId);
  // The account's own switch where the owner set one, else its plan's (which may be "first day only").
  const [features, setFeatures] = useState<Record<string, FeatureValue>>(() => ({ ...(plan?.features ?? {}), ...Object.fromEntries((account?.custom ?? []).filter(k => k in (account?.features ?? {})).map(k => [k, account!.features[k]])) }));
  const [limits, setLimits] = useState<Record<string, number>>(() => ({ ...(account?.limits ?? plan?.limits ?? {}) }));
  const [touched, setTouched] = useState<Set<string>>(() => new Set(account?.custom ?? []));
  const touch = (key: string) => setTouched(t => new Set(t).add(key));
  const choosePlan = (id: number | null) => {
    // A new plan fills in everything the owner has not changed by hand.
    const next = planOf(list, id);
    setPlanId(id);
    if (!next) return;
    // A plan with a length ends that many days from today; the owner can still change the date.
    if (next.limits.trial_days) setExpires(new Date(Date.now() + next.limits.trial_days * 86_400_000).toLocaleDateString("en-CA"));
    setFeatures(f => Object.fromEntries(list.features.map(x => [x.key, touched.has(x.key) ? f[x.key] ?? false : next.features[x.key] ?? false])));
    setLimits(v => Object.fromEntries(list.limits.map(x => [x.key, touched.has(x.key) ? v[x.key] : next.limits[x.key] ?? 0])));
  };
  const resetKey = (key: string) => {
    setTouched(t => { const n = new Set(t); n.delete(key); return n; });
    if (list.features.some(f => f.key === key)) setFeatures(f => ({ ...f, [key]: plan?.features[key] ?? false }));
    else setLimits(v => ({ ...v, [key]: plan?.limits[key] ?? 0 }));
  };
  const resetAll = () => { setTouched(new Set()); setFeatures({ ...(plan?.features ?? {}) }); setLimits({ ...(plan?.limits ?? {}) }); };
  const limitsOk = list.limits.every(l => Number.isInteger(limits[l.key]) && limits[l.key] >= 0 && limits[l.key] <= l.max);
  const save = useMutation({
    mutationFn: () => account
      ? accounts.update(account.id, { name, plan_id: planId, plan_expires_at: toEnd(expires), features, limits, ...(password ? { password } : {}) })
      : accounts.create({ name, email, password, plan_id: planId, plan_expires_at: toEnd(expires), features, limits }),
    onSuccess: saved => { queryClient.invalidateQueries({ queryKey: ["accounts"] }); queryClient.invalidateQueries({ queryKey: ["plans"] }); toast({ title: account ? `Saved ${saved.email}` : `Account ${saved.email} created`, message: account ? undefined : "Give them the email and password to sign in." }); onClose(); },
    onError: reason => setError(message(reason)),
  });
  const submit = (event: FormEvent) => { event.preventDefault(); setError(""); save.mutate(); };
  const valid = (account ? !password || password.length >= 8 : !!email.trim() && password.length >= 8) && limitsOk;
  return <Modal className="wide" title={account ? `Account · ${account.email}` : "New account"} caption={account ? "Change its plan, its own limits, name or password." : "The person signs in with this email and password. Choose a plan, then change any limit for them alone."} onClose={onClose}
    footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!valid || save.isPending} onClick={() => { setError(""); save.mutate(); }}>{save.isPending ? "Saving…" : account ? "Save" : "Create account"}</Button></>}>
    <form onSubmit={submit}>
      <Field label="Name"><input value={name} maxLength={120} onChange={e => setName(e.target.value)} placeholder="Their name"/></Field>
      {!account && <Field label="Email"><input type="email" name="new-account-email" autoComplete="off" value={email} onChange={e => setEmail(e.target.value)} placeholder="name@example.com"/></Field>}
      {/* "new-password": the browser must not fill in the owner's own saved sign-in here */}
      <Field label={account ? "New password (optional)" : "Password"} hint="At least 8 characters."><SecretInput value={password} onChange={setPassword} autoComplete="new-password" placeholder={account ? "Leave empty to keep it" : "Choose a password"}/></Field>
      <Field label="Plan" hint="What this account may use. Its limits below start as this plan's."><PlanSelect list={list} value={planId} onChange={choosePlan}/></Field>
      <Field label="Plan ends on (optional)" hint={expires ? "After this day the account goes back to the default plan." : "Empty: the plan does not end."}>
        <div className="lookup-row"><input type="date" value={expires} onChange={e => setExpires(e.target.value)}/>{expires && <Button onClick={() => setExpires("")}>Clear</Button>}</div></Field>
      <MemberLimits list={list} plan={plan} features={features} limits={limits} touched={touched} onResetAll={resetAll} onReset={resetKey}
        onFeature={(key, value) => { touch(key); setFeatures(f => ({ ...f, [key]: value })); }} onLimit={(key, value) => { touch(key); setLimits(v => ({ ...v, [key]: value })); }}/>
      {error && <div className="form-error">{error}</div>}
      <button type="submit" hidden/>
    </form>
  </Modal>;
}

/** The owner sets up an account's own keys for them: its AI models, its YouTube key and its Buffer keys. */
function KeysModal({ account, onClose }: { account: Account; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { data, error } = useQuery({ queryKey: ["account-buffer", account.id], queryFn: () => accounts.buffer(account.id) });
  const [key, setKey] = useState("");
  const [label, setLabel] = useState("");
  const [problem, setProblem] = useState("");
  const done = (status: Awaited<ReturnType<typeof accounts.buffer>>, title: string) => { queryClient.setQueryData(["account-buffer", account.id], status); queryClient.invalidateQueries({ queryKey: ["accounts"] }); toast({ title }); };
  const add = useMutation({ mutationFn: () => accounts.addBufferKey(account.id, key.trim(), label.trim()), onSuccess: s => { done(s, "Buffer accepted the key"); setKey(""); setLabel(""); setProblem(""); }, onError: r => setProblem(message(r)) });
  const remove = useMutation({ mutationFn: (keyId: number) => accounts.removeBufferKey(account.id, keyId), onSuccess: s => done(s, "Key removed"), onError: r => setProblem(message(r)) });
  return <Modal className="wide" title={`Keys · ${account.email}`} caption="Keys added here belong to this account, as if they had added them. Its videos use only its own keys." onClose={onClose} footer={<Button onClick={onClose}>Close</Button>}>
    <div className="account-keys">
      <AIModels forUser={account.id}/>
      <YouTubeKeyCard forUser={account.id}/>
    </div>
    <div className="section-label">Buffer keys</div>
    {error && <div className="form-error">{message(error)}</div>}
    {!data && !error && <Spinner/>}
    {data && <div className="buffer-keys">
      {data.keys.length === 0 && <p className="note-row">No Buffer key yet.</p>}
      {data.keys.map(item => <div className="source-secret" key={item.id}><div><span className="buffer-key-name"><b>{item.label}</b><code>••••••••{item.last4}</code></span>
        <small>{item.accounts} account{item.accounts === 1 ? "" : "s"} · saved {day(item.saved_at)}</small>{item.error && <small className="bad">{item.error}</small>}</div>
        <Button variant="danger" disabled={remove.isPending} onClick={() => window.confirm(`Remove ${item.label}?`) && remove.mutate(item.id)}>Remove</Button></div>)}
      {data.keys.length < data.max_keys
        ? <form className="buffer-key-form" onSubmit={e => { e.preventDefault(); if (key.trim()) add.mutate(); }}>
          <div className="buffer-key-fields">
            <Field label="Name (optional)"><input value={label} maxLength={40} onChange={e => setLabel(e.target.value)} placeholder="Key name"/></Field>
            <Field label="API key" hint="Checked with Buffer before it is saved."><SecretInput value={key} onChange={setKey} placeholder="Paste a Buffer API key"/></Field>
          </div>
          <div className="inline-form"><Button variant="primary" type="submit" disabled={!key.trim() || add.isPending}>{add.isPending ? "Checking with Buffer…" : "Add key"}</Button></div>
        </form>
        : <small className="muted">This account has all {data.max_keys} keys its plan allows.</small>}
      {problem && <div className="form-error">{problem}</div>}
    </div>}
  </Modal>;
}

function AccountsTab({ list }: { list: PlanList }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const { data, isLoading } = useQuery({ queryKey: ["accounts"], queryFn: accounts.list, refetchInterval: 60_000 });
  const [editing, setEditing] = useState<Account | "new" | null>(null);
  const [keysOf, setKeysOf] = useState<Account | null>(null);
  const change = useMutation({
    mutationFn: ({ id, suspended }: { id: number; suspended: boolean }) => accounts.update(id, { suspended }),
    onSuccess: a => { queryClient.invalidateQueries({ queryKey: ["accounts"] }); toast({ title: a.suspended ? `${a.email} is suspended` : `${a.email} is active again` }); },
    onError,
  });
  const remove = useMutation({ mutationFn: (id: number) => accounts.remove(id), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["accounts"] }); queryClient.invalidateQueries({ queryKey: ["plans"] }); toast({ title: "Account deleted" }); }, onError });
  return <>
    <div className="accounts-bar"><span className="muted">{data ? `${data.filter(a => a.role !== "owner").length} accounts` : ""}</span><Button variant="primary" icon="plus" onClick={() => setEditing("new")}>New account</Button></div>
    <Card className="table-card"><div className="table-wrap"><table><thead><tr><th>Account</th><th>Plan</th><th>Plan ends</th><th style={{ textAlign: "right" }}>Channels</th><th style={{ textAlign: "right" }}>Videos today</th><th style={{ textAlign: "right" }}>Buffer keys</th><th>Status</th><th/></tr></thead><tbody>
      {(data ?? []).map(a => <tr key={a.id}>
        <td><div className="account-cell"><Avatar label={initialsOf(a.name || a.email)}/><div><strong>{a.name || a.email}</strong><small>{a.email}</small></div></div></td>
        <td>{a.role === "owner" ? <Badge tone="primary" dot={false}>Owner · everything</Badge> : <span className="plan-cell"><Badge tone={a.plan_expired ? "warning" : "neutral"} dot={false}>{a.plan}</Badge>{a.custom.length > 0 && <span className="custom-tag" title={`Changed for this account: ${a.custom.join(", ")}`}>{`+${a.custom.length} custom`}</span>}</span>}</td>
        <td>{a.role === "owner" ? "—" : a.plan_expires_at ? <span className={a.plan_expired ? "bad" : ""}>{day(a.plan_expires_at)}{a.plan_expired ? " (ended)" : ""}</span> : "Never"}</td>
        <td style={{ textAlign: "right" }}>{a.channels}</td><td style={{ textAlign: "right" }}>{a.videos_today}</td><td style={{ textAlign: "right" }}>{a.buffer_keys}</td>
        <td>{a.suspended ? <Badge tone="danger">Suspended</Badge> : <Badge tone="success">Active</Badge>}</td>
        <td><div className="row-actions">{a.role !== "owner" && <>
          <Button onClick={() => setEditing(a)}>Edit</Button>
          <Button onClick={() => setKeysOf(a)}>Keys</Button>
          {/* Suspend and Delete sit in a menu, so every row stays on one even line. */}
          <Menu items={[
            { label: a.suspended ? "Activate" : "Suspend", icon: a.suspended ? "check" : "pause", disabled: change.isPending,
              onSelect: () => { if (a.suspended || window.confirm(`Suspend ${a.email}? They cannot sign in, and their channels stop being watched until you reactivate them.`)) change.mutate({ id: a.id, suspended: !a.suspended }); } },
            { label: "Delete", icon: "close", danger: true, disabled: remove.isPending,
              onSelect: () => { if (window.confirm(`Delete the account ${a.email}? They can no longer sign in, and their channels stop being watched.`)) remove.mutate(a.id); } },
          ]} trigger={t => <Button variant="ghost" icon="more" title="More" onClick={t}/>}/></>}</div></td>
      </tr>)}</tbody></table></div>
      {isLoading && <Spinner/>}
      {data && data.length <= 1 && <Empty icon="plus" title="No accounts yet">Press “New account” to make a login for someone, with the plan they get.</Empty>}
    </Card>
    {editing && <AccountModal list={list} account={editing === "new" ? undefined : editing} onClose={() => setEditing(null)}/>}
    {keysOf && <KeysModal account={keysOf} onClose={() => setKeysOf(null)}/>}
  </>;
}

const blank = (list: PlanList): PlanInput => ({ name: "", description: "", is_default: false, price: 0, currency: "PKR", features: Object.fromEntries(list.features.map(f => [f.key, false])), limits: Object.fromEntries(list.limits.map(l => [l.key, 0])) });

/** One plan: its switches and its limits. */
function PlanModal({ list, plan, onClose }: { list: PlanList; plan?: PlanRow; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [draft, setDraft] = useState<PlanInput>(plan ? { name: plan.name, description: plan.description, is_default: plan.is_default, price: plan.price ?? 0, currency: plan.currency || "PKR", features: { ...plan.features }, limits: { ...plan.limits } } : blank(list));
  const [error, setError] = useState("");
  const save = useMutation({
    mutationFn: () => (plan ? accounts.updatePlan(plan.id, draft) : accounts.createPlan(draft)),
    onSuccess: saved => { queryClient.setQueryData(["plans"], saved); queryClient.invalidateQueries({ queryKey: ["accounts"] }); toast({ title: `Plan “${draft.name}” saved` }); onClose(); },
    onError: reason => setError(message(reason)),
  });
  const limitOk = list.limits.every(l => Number.isInteger(draft.limits[l.key]) && draft.limits[l.key] >= 0 && draft.limits[l.key] <= l.max)
    && Number.isInteger(draft.price) && draft.price >= 0 && draft.price <= 10_000_000;
  return <Modal className="wide" title={plan ? `Plan · ${plan.name}` : "New plan"} caption="Switch on what accounts on this plan may use. A limit of 0 means no limit." onClose={onClose}
    footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!draft.name.trim() || !limitOk || save.isPending} onClick={() => { setError(""); save.mutate(); }}>{save.isPending ? "Saving…" : "Save plan"}</Button></>}>
    <div className="plan-form">
      <div className="buffer-key-fields">
        <Field label="Name"><input value={draft.name} maxLength={60} onChange={e => setDraft({ ...draft, name: e.target.value })} placeholder="e.g. Pro"/></Field>
        <Field label="Description (optional)"><input value={draft.description} maxLength={500} onChange={e => setDraft({ ...draft, description: e.target.value })} placeholder="What it is for"/></Field>
      </div>
      <div className="buffer-key-fields">
        <Field label="Price" hint={draft.limits.trial_days ? `For the plan's ${draft.limits.trial_days} days. 0 = free.` : "Per month. 0 = free."}>
          <input type="number" min={0} max={10000000} value={Number.isNaN(draft.price) ? "" : draft.price} onChange={e => setDraft({ ...draft, price: e.target.value === "" ? NaN : Number(e.target.value) })} placeholder="e.g. 2999"/></Field>
        <Field label="Currency"><input value={draft.currency} maxLength={8} onChange={e => setDraft({ ...draft, currency: e.target.value.toUpperCase() })} placeholder="PKR"/></Field>
      </div>
      <div className="section-label">Features</div>
      <div className="plan-switches">{list.features.map(f => <div className="plan-switch" key={f.key}>
        <div><b>{f.label}</b><small>{f.help}</small>
          <FeatureChoice value={draft.features[f.key] ?? false} onChange={v => setDraft({ ...draft, features: { ...draft.features, [f.key]: v } })}/></div></div>)}</div>
      <div className="section-label">Limits</div>
      <div className="plan-limits">{list.limits.map(l => <Field key={l.key} label={l.label} hint={["auto_check_minutes", "trial_days", "skipped_keep_hours"].includes(l.key) ? l.help : `${l.help} 0 = no limit.`}>
        <input type="number" min={0} max={l.max} value={Number.isNaN(draft.limits[l.key]) ? "" : draft.limits[l.key]} onChange={e => setDraft({ ...draft, limits: { ...draft.limits, [l.key]: e.target.value === "" ? NaN : Number(e.target.value) } })}/></Field>)}</div>
      <label className="plan-switch"><Toggle checked={draft.is_default} disabled={!!plan?.is_default} label="Default plan" onChange={() => setDraft({ ...draft, is_default: !draft.is_default })}/>
        <div><b>Default plan</b><small>New accounts get it, and so does any account whose plan has ended.</small></div></label>
      {error && <div className="form-error">{error}</div>}
    </div>
  </Modal>;
}

/** Each tier's look: its colours and its sign (a gift for the trial, medals, a crown for the biggest). */
const TIER: Record<string, { tone: string; sign: "gift" | "medal" | "crown" | "star" }> = {
  "free trial": { tone: "trial", sign: "gift" }, bronze: { tone: "bronze", sign: "medal" }, silver: { tone: "silver", sign: "medal" },
  gold: { tone: "gold", sign: "medal" }, platinum: { tone: "platinum", sign: "crown" },
};

/** A plan card's limits in a few words each: "Videos/day 10", "Length 4 days". */
const SHORT: Record<string, string> = {
  channels: "Channels", videos_per_day: "Videos/day", podcasts_per_day: "Podcasts/day", buffer_keys: "Buffer keys", buffer_accounts: "Accounts",
  cloud_videos_per_month: "Cloud videos", auto_check_minutes: "Auto-check", trial_days: "Length", skipped_keep_hours: "Skipped kept",
};
function shortValue(p: PlanRow, key: string): string {
  const v = p.limits[key];
  if (key === "podcasts_per_day" && !p.features.podcasts) return "—";
  if (key === "cloud_videos_per_month") return !p.features.cloud_editing ? "—" : v ? (p.limits.trial_days ? `${v} in ${p.limits.trial_days}d` : `${v} / month`) : "No limit";
  if (key === "auto_check_minutes") return v ? `${v} min` : "Push only";
  if (key === "trial_days") return v ? `${v} days` : "No end";
  if (key === "skipped_keep_hours") return v ? `${v} h` : "Kept";
  return v ? String(v) : "No limit";
}

function TierIcon({ name }: { name: string }) {
  const tier = TIER[name.toLowerCase()] ?? { tone: "custom", sign: "star" as const };
  const sign = {
    gift: <><rect x="4" y="10" width="16" height="10" rx="2"/><path d="M3 7h18v3H3zM12 7v13M12 7c-1.5-3-5-3-5 0M12 7c1.5-3 5-3 5 0"/></>,
    medal: <><circle cx="12" cy="14" r="6"/><path d="M8.5 3h7L13 9h-2zM12 11.5l.9 1.9 2 .3-1.5 1.4.4 2-1.8-1-1.8 1 .4-2-1.5-1.4 2-.3z"/></>,
    crown: <><path d="M3 8l4.5 4L12 5l4.5 7L21 8l-2 11H5z"/><path d="M5 19h14"/></>,
    star: <path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"/>,
  }[tier.sign];
  return <span className={`tier-icon tier-${tier.tone}`} aria-hidden><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{sign}</svg></span>;
}

function PlansTab({ list }: { list: PlanList }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const [editing, setEditing] = useState<PlanRow | "new" | null>(null);
  const remove = useMutation({ mutationFn: (id: number) => accounts.removePlan(id), onSuccess: saved => { queryClient.setQueryData(["plans"], saved); queryClient.invalidateQueries({ queryKey: ["accounts"] }); toast({ title: "Plan deleted", message: "Its accounts are on the default plan now." }); }, onError });
  return <>
    <div className="accounts-bar"><span className="muted">{list.plans.length} plans</span><Button variant="primary" icon="plus" onClick={() => setEditing("new")}>New plan</Button></div>
    <div className="plan-grid">{list.plans.map(p => <Card className={`plan-card tier-card-${(TIER[p.name.toLowerCase()] ?? { tone: "custom" }).tone}`} key={p.id}>
      <div className="plan-card-head"><div><TierIcon name={p.name}/><div><strong>{p.name}</strong>{p.description && <p className="muted">{p.description}</p>}</div></div>
        <div className="plan-card-meta">
          <div className="plan-price">{p.price ? <><b>{`${p.currency || "PKR"} ${p.price.toLocaleString("en-US")}`}</b><small>{p.limits.trial_days ? `/ ${p.limits.trial_days} days` : "/ month"}</small></> : <><b>Free</b><small>{p.limits.trial_days ? `${p.limits.trial_days} days` : ""}</small></>}</div>
          <div className="plan-card-tags">{p.is_default && <Badge tone="primary" dot={false}>Default</Badge>}<span className="muted">{`${p.accounts} account${p.accounts === 1 ? "" : "s"}`}</span></div></div></div>
      <div className="plan-card-body">
      <ul className="plan-features">{list.features.map(f => <li key={f.key} className={p.features[f.key] === "first_day" ? "day1" : p.features[f.key] ? "on" : "off"}>{p.features[f.key] === "first_day" ? "◐" : p.features[f.key] ? "✓" : "✕"} {f.label}{p.features[f.key] === "first_day" ? " (first day)" : ""}</li>)}</ul>
      <div className="plan-limit-row">{list.limits.map(l => <span key={l.key} title={l.help}><small>{SHORT[l.key] ?? l.label}</small><b>{shortValue(p, l.key)}</b></span>)}</div>
      </div>
      <div className="row-actions"><Button onClick={() => setEditing(p)}>Edit</Button>{!p.is_default && <Button variant="danger" disabled={remove.isPending} onClick={() => window.confirm(`Delete the plan ${p.name}? Its accounts move to the default plan.`) && remove.mutate(p.id)}>Delete</Button>}</div>
    </Card>)}</div>
    {editing && <PlanModal list={list} plan={editing === "new" ? undefined : editing} onClose={() => setEditing(null)}/>}
  </>;
}

/** The owner's panel: every account and the plans that decide what each may use. */
export default function Accounts() {
  const [tab, setTab] = useState<"accounts" | "plans">("accounts");
  const { data: list, error } = useQuery({ queryKey: ["plans"], queryFn: accounts.plans });
  return <><PageHeader title="Accounts" description="Make a login for each person, give it a plan, and switch features on or off per plan. You, as the owner, can use everything."/>
    <div className="section-tabs" data-i18n-skip><button className={tab === "accounts" ? "active" : ""} onClick={() => setTab("accounts")}>Accounts</button><button className={tab === "plans" ? "active" : ""} onClick={() => setTab("plans")}>Plans</button></div>
    {error && <div className="form-error">{message(error)}</div>}
    {!list && !error && <Spinner/>}
    {list && (tab === "accounts" ? <AccountsTab list={list}/> : <PlansTab list={list}/>)}
  </>;
}
