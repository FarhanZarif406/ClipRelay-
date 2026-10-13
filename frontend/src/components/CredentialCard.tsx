import { useEffect, useState, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { credentials } from "@/api/endpoints";
import type { CredentialCard as Card_, CredentialResult, CredentialState } from "@/api/types";
import { dayTime } from "@/lib/format";
import { Icon } from "./Icon";
import { Field, Modal } from "./Modal";
import { useErrorToast, useToast } from "./Toast";
import { Badge, Button, Card } from "./ui";

const STATE: Record<CredentialState | "testing", { label: string; tone: "success" | "warning" | "danger" | "primary" | "neutral" }> = {
  none: { label: "Not configured", tone: "neutral" },
  env: { label: "From .env", tone: "neutral" },
  unverified: { label: "Unverified", tone: "warning" },
  valid: { label: "Valid", tone: "success" },
  invalid: { label: "Invalid", tone: "danger" },
  testing: { label: "Testing…", tone: "primary" },
};

export function CredentialBadge({ state, testing }: { state: CredentialState; testing?: boolean }) {
  const s = STATE[testing ? "testing" : state];
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

export function SecretInput({ value, onChange, placeholder, autoComplete = "off" }: { value: string; onChange: (v: string) => void; placeholder?: string; autoComplete?: string }) {
  const [shown, setShown] = useState(false);
  return <div className="secret-input"><input type={shown ? "text" : "password"} value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} autoComplete={autoComplete} spellCheck={false}/><button type="button" onClick={() => setShown(s => !s)}>{shown ? "Hide" : "Show"}</button></div>;
}

export function CopyField({ value }: { value: string }) {
  const toast = useToast();
  const copy = () => navigator.clipboard?.writeText(value).then(() => toast({ title: "Copied", message: value }), () => undefined);
  return <div className="secret-input readonly"><input readOnly value={value} onFocus={e => e.target.select()}/><button type="button" onClick={copy}>Copy</button></div>;
}

/** Member view: status only — no values, no actions. */
function MemberCard({ card }: { card: Card_ }) {
  return <Card className="credential-card"><div className="credential-head"><div><div className="card-title">{card.title}</div><div className="card-caption">Managed by the workspace owner.</div></div><Badge tone={card.configured ? "success" : "warning"}>{card.configured ? "Configured" : "Needs setup"}</Badge></div></Card>;
}

export type Preset = { label: string; values: Record<string, string>; hint?: string };

export function CredentialCard({ card, isOwner, children, presets }: { card: Card_; isOwner: boolean; children?: ReactNode; presets?: Preset[] }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const [values, setValues] = useState<Record<string, string>>({});
  const [result, setResult] = useState<{ ok: boolean | null; message: string } | null>(null);
  const [removing, setRemoving] = useState(false);

  useEffect(() => {
    setValues(Object.fromEntries((card.fields ?? []).map(f => [f.key, f.secret ? "" : f.value ?? ""])));
  }, [card]);

  const refresh = (next?: Card_) => {
    if (next) queryClient.setQueryData<Card_[]>(["credentials"], list => list?.map(c => c.group === next.group ? next : c));
    queryClient.invalidateQueries({ queryKey: ["credentials"] });
    queryClient.invalidateQueries({ queryKey: ["settings", "integrations"] });
  };
  // Only send what changed: blank secrets mean "keep the stored value".
  const changed = () => Object.fromEntries(Object.entries(values).filter(([k, v]) => { const f = card.fields?.find(x => x.key === k); return v.trim() && (f?.secret || v.trim() !== (f?.value ?? "")); }));
  const report = (r: CredentialResult) => { setResult({ ok: r.ok, message: r.message }); refresh(r.card); };

  const validate = useMutation({ mutationFn: () => credentials.validate(card.group, changed()), onSuccess: report, onError });
  const save = useMutation({
    mutationFn: () => credentials.save(card.group, changed()),
    onSuccess: r => { report(r); toast({ title: `${card.title} saved`, message: r.ok === false ? "Saved, but validation failed — see the card." : "Takes effect immediately." }); },
    onError,
  });
  const remove = useMutation({
    mutationFn: () => credentials.remove(card.group),
    onSuccess: r => { setRemoving(false); setResult(null); refresh(r.card); toast({ title: `${card.title} removed`, message: r.fallback === "env" ? "Now using the values from .env." : "This integration is no longer configured." }); },
    onError,
  });

  if (!isOwner || !card.fields) return <MemberCard card={card}/>;
  const savedInApp = card.fields.some(f => f.source === "app");
  const dirty = Object.keys(changed()).length > 0;
  const busy = validate.isPending || save.isPending;

  return <Card className="credential-card">
    <div className="credential-head"><div><div className="card-title">{card.title}</div><div className="card-caption">{savedInApp ? "Set in app" : card.state === "env" ? "From .env — saving here overrides it" : "Not configured yet"}{card.verified_at ? ` · verified ${dayTime(card.verified_at)}` : ""}</div></div><CredentialBadge state={card.state} testing={busy}/></div>
    {card.state === "invalid" && card.last_error && !result && <div className="form-error">{card.last_error}</div>}
    {presets && <div className="inline-form" style={{ marginTop: 0, marginBottom: 12 }}>{presets.map(p => <Button key={p.label} onClick={() => { setValues(v => ({ ...v, ...p.values })); setResult(p.hint ? { ok: null, message: p.hint } : null); }}>{p.label}</Button>)}</div>}
    <div className="credential-fields">
      {card.fields.map(f => <Field key={f.key} label={`${f.label}${f.source ? ` · ${f.source === "app" ? "set in app" : f.source === "env" ? "from .env" : "default"}` : ""}`}>
        {f.secret ? <SecretInput value={values[f.key] ?? ""} onChange={v => setValues(x => ({ ...x, [f.key]: v }))} placeholder={f.masked ? `${f.masked} — leave blank to keep` : "Not set"}/>
          : <input value={values[f.key] ?? ""} onChange={e => setValues(x => ({ ...x, [f.key]: e.target.value }))} placeholder="Not set" spellCheck={false}/>}
      </Field>)}
    </div>
    {children}
    {result && <div className={result.ok === false ? "form-error" : "form-note"}>{result.ok === true && <strong>Valid. </strong>}{result.ok === null && <strong>Unverified. </strong>}{result.message}</div>}
    <div className="credential-foot">
      {card.docs_url && <a className="muted" href={card.docs_url} target="_blank" rel="noreferrer"><Icon name="link" size={13}/> Setup guide</a>}
      <span style={{ flex: 1 }}/>
      {savedInApp && <Button variant="danger" onClick={() => setRemoving(true)} disabled={remove.isPending}>Remove</Button>}
      <Button onClick={() => validate.mutate()} disabled={busy}>{validate.isPending ? "Validating…" : "Validate"}</Button>
      <Button variant="primary" onClick={() => save.mutate()} disabled={!dirty || busy}>{save.isPending ? "Saving…" : "Save"}</Button>
    </div>
    {removing && <Modal title={`Remove ${card.title.toLowerCase()} credentials?`} caption="The values saved in the app are deleted." onClose={() => setRemoving(false)}
      footer={<><Button onClick={() => setRemoving(false)}>Cancel</Button><Button variant="danger" onClick={() => remove.mutate()} disabled={remove.isPending}>Remove</Button></>}>
      <div className="form-note">If the server’s <code>.env</code> has values for this integration, ClipRelay falls back to them right away. Otherwise the integration becomes not configured.</div>
    </Modal>}
  </Card>;
}
