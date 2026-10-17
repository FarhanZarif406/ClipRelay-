import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { accounts } from "@/api/endpoints";
import type { Account, PlanInput, PlanList, PlanRow } from "@/api/types";
import { AIModels } from "@/components/AIModels";
import { SecretInput } from "@/components/CredentialCard";
import { YouTubeKeyCard } from "@/components/YouTubeKeyCard";
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

function PlanSelect({ list, value, onChange }: { list: PlanList; value: number | null; onChange: (id: number | null) => void }) {
  const fallback = list.plans.find(p => p.is_default);
  return <select value={value ?? ""} onChange={e => onChange(e.target.value ? Number(e.target.value) : null)}>
    <option value="">Default plan{fallback ? ` (${fallback.name})` : ""}</option>
    {list.plans.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
  </select>;
}

/** A new account, or the plan, name and password of an existing one. */
function AccountModal({ list, account, onClose }: { list: PlanList; account?: Account; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState(account?.name ?? "");
  const [email, setEmail] = useState(account?.email ?? "");
  const [password, setPassword] = useState("");
  const [planId, setPlanId] = useState<number | null>(account?.plan_id ?? null);
  const [expires, setExpires] = useState(toInput(account?.plan_expires_at ?? null));
  const [error, setError] = useState("");
  const save = useMutation({
    mutationFn: () => account
      ? accounts.update(account.id, { name, plan_id: planId, plan_expires_at: toEnd(expires), ...(password ? { password } : {}) })
      : accounts.create({ name, email, password, plan_id: planId, plan_expires_at: toEnd(expires) }),
    onSuccess: saved => { queryClient.invalidateQueries({ queryKey: ["accounts"] }); queryClient.invalidateQueries({ queryKey: ["plans"] }); toast({ title: account ? `Saved ${saved.email}` : `Account ${saved.email} created`, message: account ? undefined : "Give them the email and password to sign in." }); onClose(); },
    onError: reason => setError(message(reason)),
  });
  const submit = (event: FormEvent) => { event.preventDefault(); setError(""); save.mutate(); };
  const valid = account ? !password || password.length >= 8 : !!email.trim() && password.length >= 8;
  return <Modal title={account ? `Account · ${account.email}` : "New account"} caption={account ? "Change its plan, name or password." : "The person signs in with this email and password."} onClose={onClose}
    footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!valid || save.isPending} onClick={() => { setError(""); save.mutate(); }}>{save.isPending ? "Saving…" : account ? "Save" : "Create account"}</Button></>}>
    <form onSubmit={submit}>
      <Field label="Name"><input value={name} maxLength={120} onChange={e => setName(e.target.value)} placeholder="Their name"/></Field>
      {!account && <Field label="Email"><input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="name@example.com"/></Field>}
      <Field label={account ? "New password (optional)" : "Password"} hint="At least 8 characters."><SecretInput value={password} onChange={setPassword} placeholder={account ? "Leave empty to keep it" : "Choose a password"}/></Field>
      <Field label="Plan" hint="What this account may use."><PlanSelect list={list} value={planId} onChange={setPlanId}/></Field>
      <Field label="Plan ends on (optional)" hint={expires ? "After this day the account goes back to the default plan." : "Empty: the plan does not end."}>
        <div className="lookup-row"><input type="date" value={expires} onChange={e => setExpires(e.target.value)}/>{expires && <Button onClick={() => setExpires("")}>Clear</Button>}</div></Field>
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
        <td>{a.role === "owner" ? <Badge tone="primary" dot={false}>Owner · everything</Badge> : <Badge tone={a.plan_expired ? "warning" : "neutral"} dot={false}>{a.plan}</Badge>}</td>
        <td>{a.role === "owner" ? "—" : a.plan_expires_at ? <span className={a.plan_expired ? "bad" : ""}>{day(a.plan_expires_at)}{a.plan_expired ? " (ended)" : ""}</span> : "Never"}</td>
        <td style={{ textAlign: "right" }}>{a.channels}</td><td style={{ textAlign: "right" }}>{a.videos_today}</td><td style={{ textAlign: "right" }}>{a.buffer_keys}</td>
        <td>{a.suspended ? <Badge tone="danger">Suspended</Badge> : <Badge tone="success">Active</Badge>}</td>
        <td><div className="row-actions">{a.role !== "owner" && <>
          <Button onClick={() => setEditing(a)}>Edit</Button>
          <Button onClick={() => setKeysOf(a)}>Keys</Button>
          <Button disabled={change.isPending} onClick={() => (a.suspended || window.confirm(`Suspend ${a.email}? They cannot sign in, and their channels stop being watched until you reactivate them.`)) && change.mutate({ id: a.id, suspended: !a.suspended })}>{a.suspended ? "Activate" : "Suspend"}</Button>
          <Button variant="danger" disabled={remove.isPending} onClick={() => window.confirm(`Delete the account ${a.email}? They can no longer sign in, and their channels stop being watched.`) && remove.mutate(a.id)}>Delete</Button></>}</div></td>
      </tr>)}</tbody></table></div>
      {isLoading && <Spinner/>}
      {data && data.length <= 1 && <Empty icon="plus" title="No accounts yet">Press “New account” to make a login for someone, with the plan they get.</Empty>}
    </Card>
    {editing && <AccountModal list={list} account={editing === "new" ? undefined : editing} onClose={() => setEditing(null)}/>}
    {keysOf && <KeysModal account={keysOf} onClose={() => setKeysOf(null)}/>}
  </>;
}

const blank = (list: PlanList): PlanInput => ({ name: "", description: "", is_default: false, features: Object.fromEntries(list.features.map(f => [f.key, false])), limits: Object.fromEntries(list.limits.map(l => [l.key, 0])) });

/** One plan: its switches and its limits. */
function PlanModal({ list, plan, onClose }: { list: PlanList; plan?: PlanRow; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [draft, setDraft] = useState<PlanInput>(plan ? { name: plan.name, description: plan.description, is_default: plan.is_default, features: { ...plan.features }, limits: { ...plan.limits } } : blank(list));
  const [error, setError] = useState("");
  const save = useMutation({
    mutationFn: () => (plan ? accounts.updatePlan(plan.id, draft) : accounts.createPlan(draft)),
    onSuccess: saved => { queryClient.setQueryData(["plans"], saved); queryClient.invalidateQueries({ queryKey: ["accounts"] }); toast({ title: `Plan “${draft.name}” saved` }); onClose(); },
    onError: reason => setError(message(reason)),
  });
  const limitOk = list.limits.every(l => Number.isInteger(draft.limits[l.key]) && draft.limits[l.key] >= 0 && draft.limits[l.key] <= l.max);
  return <Modal className="wide" title={plan ? `Plan · ${plan.name}` : "New plan"} caption="Switch on what accounts on this plan may use. A limit of 0 means no limit." onClose={onClose}
    footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!draft.name.trim() || !limitOk || save.isPending} onClick={() => { setError(""); save.mutate(); }}>{save.isPending ? "Saving…" : "Save plan"}</Button></>}>
    <div className="plan-form">
      <div className="buffer-key-fields">
        <Field label="Name"><input value={draft.name} maxLength={60} onChange={e => setDraft({ ...draft, name: e.target.value })} placeholder="e.g. Pro"/></Field>
        <Field label="Description (optional)"><input value={draft.description} maxLength={500} onChange={e => setDraft({ ...draft, description: e.target.value })} placeholder="What it is for"/></Field>
      </div>
      <div className="section-label">Features</div>
      <div className="plan-switches">{list.features.map(f => <label className="plan-switch" key={f.key}>
        <Toggle checked={!!draft.features[f.key]} label={f.label} onChange={() => setDraft({ ...draft, features: { ...draft.features, [f.key]: !draft.features[f.key] } })}/>
        <div><b>{f.label}</b><small>{f.help}</small></div></label>)}</div>
      <div className="section-label">Limits</div>
      <div className="plan-limits">{list.limits.map(l => <Field key={l.key} label={l.label} hint={["auto_check_minutes", "trial_days", "skipped_keep_hours"].includes(l.key) ? l.help : `${l.help} 0 = no limit.`}>
        <input type="number" min={0} max={l.max} value={Number.isNaN(draft.limits[l.key]) ? "" : draft.limits[l.key]} onChange={e => setDraft({ ...draft, limits: { ...draft.limits, [l.key]: e.target.value === "" ? NaN : Number(e.target.value) } })}/></Field>)}</div>
      <label className="plan-switch"><Toggle checked={draft.is_default} disabled={!!plan?.is_default} label="Default plan" onChange={() => setDraft({ ...draft, is_default: !draft.is_default })}/>
        <div><b>Default plan</b><small>New accounts get it, and so does any account whose plan has ended.</small></div></label>
      {error && <div className="form-error">{error}</div>}
    </div>
  </Modal>;
}

function PlansTab({ list }: { list: PlanList }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const [editing, setEditing] = useState<PlanRow | "new" | null>(null);
  const remove = useMutation({ mutationFn: (id: number) => accounts.removePlan(id), onSuccess: saved => { queryClient.setQueryData(["plans"], saved); queryClient.invalidateQueries({ queryKey: ["accounts"] }); toast({ title: "Plan deleted", message: "Its accounts are on the default plan now." }); }, onError });
  return <>
    <div className="accounts-bar"><span className="muted">{list.plans.length} plans</span><Button variant="primary" icon="plus" onClick={() => setEditing("new")}>New plan</Button></div>
    <div className="plan-grid">{list.plans.map(p => <Card className="plan-card" key={p.id}>
      <div className="plan-card-head"><div><strong>{p.name}</strong>{p.is_default && <Badge tone="primary" dot={false}>Default</Badge>}</div><span className="muted">{p.accounts} account{p.accounts === 1 ? "" : "s"}</span></div>
      {p.description && <p className="muted">{p.description}</p>}
      <ul className="plan-features">{list.features.map(f => <li key={f.key} className={p.features[f.key] ? "on" : "off"}>{p.features[f.key] ? "✓" : "✕"} {f.label}</li>)}</ul>
      <div className="plan-limit-row">{list.limits.map(l => <span key={l.key}><small>{l.label}</small><b>{limitText(l.key, p.limits[l.key])}</b></span>)}</div>
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
