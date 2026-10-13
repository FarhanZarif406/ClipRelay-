import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { push, youtubeApi } from "@/api/endpoints";
import type { PushInfo, PushSubscription, Tone, YouTubeApiInfo } from "@/api/types";
import { SecretInput } from "@/components/CredentialCard";
import { Field, Modal } from "@/components/Modal";
import { Badge, Button, Card } from "@/components/ui";
import { relativeTime } from "@/lib/format";

type State = "Connected" | "Not configured" | "Error";
const TONE: Record<State, Tone> = { Connected: "success", "Not configured": "neutral", Error: "danger" };
const message = (error: unknown) => (error instanceof Error ? error.message : String(error));
const day = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });

function Metric({ label, value, danger, children }: { label: string; value: string; danger?: boolean; children?: ReactNode }) {
  return <div className="source-metric"><span>{label}</span><strong className={danger ? "bad" : ""}>{value}</strong>{children}</div>;
}

/** A stored secret: masked once saved, or a prompt to add one. */
function SecretField({ label, empty, masked, note, onReplace, onRemove }: { label: string; empty: boolean; masked: string; note: string; onReplace: () => void; onRemove?: () => void }) {
  return <div className="source-field"><label>{label}</label>
    {empty
      ? <div className="source-secret empty"><span>No key configured</span><Button variant="primary" onClick={onReplace}>Add key</Button></div>
      : <div className="source-secret"><div><code>{masked}</code><small>{note}</small></div>{onRemove && <button type="button" className="link-button danger" onClick={onRemove}>Remove</button>}<Button variant="ghost" onClick={onReplace}>Replace</Button></div>}
  </div>;
}

function ReadOnlyValue({ label, value, copy }: { label: string; value: string; copy: boolean }) {
  const [copied, setCopied] = useState(false);
  return <div className="source-field"><label>{label}</label>
    <div className="source-readonly"><code>{value}</code>{copy && <button type="button" className="link-button" onClick={() => void navigator.clipboard?.writeText(value).then(() => setCopied(true), () => {})}>{copied ? "Copied ✓" : "Copy"}</button>}</div>
  </div>;
}

function ReplaceKeyModal({ label, adding, onClose, onSave }: { label: string; adding: boolean; onClose: () => void; onSave: (value: string) => Promise<unknown> }) {
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const replace = async (event?: FormEvent) => {
    event?.preventDefault();
    if (!value.trim() || saving) return;
    setSaving(true);
    setError(null);
    try {
      await onSave(value.trim());
      onClose();
    } catch (reason) {
      setError(message(reason));
      setSaving(false);
    }
  };
  return <Modal title={`${adding ? "Add" : "Replace"} ${label}`} caption="Kept on the server. It is never shown again after saving." onClose={onClose}
    footer={<><Button onClick={onClose}>Cancel</Button><Button variant={adding ? "primary" : "danger"} disabled={saving || !value.trim()} onClick={() => void replace()}>{saving ? "Saving…" : adding ? "Save key" : "Replace key"}</Button></>}>
    <form onSubmit={replace}><Field label={adding ? "Key" : "New key"}><SecretInput value={value} onChange={setValue} placeholder="Paste the new key"/></Field></form>
    {error ? <div className="form-error">{error}</div> : !adding && <div className="form-note">The current key stops being used immediately.</div>}
  </Modal>;
}

function CardShell({ icon, title, description, state, children, metrics, action, result, failed }: {
  icon: string; title: string; description: string; state: State; children: ReactNode; metrics: ReactNode; action: ReactNode; result: string; failed?: boolean;
}) {
  return <Card className={`source-card${state === "Error" ? " errored" : ""}`}>
    <div className="source-head"><div className="source-icon">{icon}</div><div><div className="card-title">{title}</div><div className="card-caption">{description}</div></div><Badge tone={TONE[state]}>{state}</Badge></div>
    {children}
    <div className="source-metrics three">{metrics}</div>
    <div className="source-test">{action}<span className={failed ? "bad" : ""}>{result}</span></div>
  </Card>;
}

/** Integrations → YouTube Data API: the key, the project ID and a live connection test. */
export function YouTubeApiCard() {
  const queryClient = useQueryClient();
  const { data: status, error } = useQuery({ queryKey: ["youtube-api"], queryFn: youtubeApi.info });
  const set = (next: YouTubeApiInfo) => queryClient.setQueryData(["youtube-api"], next);
  const test = useMutation({ mutationFn: youtubeApi.test, onSuccess: result => set(result.status_info) });
  const [replacing, setReplacing] = useState(false);
  const [project, setProject] = useState<string | null>(null);
  const [projectError, setProjectError] = useState<string | null>(null);
  const saveProject = useMutation({
    mutationFn: () => youtubeApi.save({ project_id: (project ?? "").trim() }),
    onSuccess: next => { set(next); setProject(null); setProjectError(null); },
    onError: reason => setProjectError(message(reason)),
  });
  const remove = useMutation({ mutationFn: youtubeApi.removeKey, onSuccess: next => { set(next); test.reset(); } });

  // A saved key is tested once when the page opens, so the badge shows Google's own answer.
  const hasKey = status?.has_key;
  const run = test.mutate;
  useEffect(() => { if (hasKey) run(); }, [hasKey, run]);

  const result = test.data;
  const state: State = !status?.has_key ? "Not configured" : error || test.isError || result?.ok === false ? "Error" : result?.ok ? "Connected" : "Not configured";
  const summary = test.isPending ? "Testing…" : error ? message(error) : test.isError ? message(test.error) : !status?.has_key ? "Not tested — no API key saved"
    : !result ? "Not tested" : result.ok ? "Connected — Google accepted the key" : result.status ? `${result.status} — ${result.message}` : result.message;
  const usage = status?.usage;
  const projectValue = project ?? status?.project_id ?? "";
  const fromApp = status?.source === "app";

  return <CardShell icon="YT" title="YouTube Data API" state={state} description="Fetches channel and video details when a channel publishes. Optional: without a key ClipRelay reads YouTube’s public pages instead."
    metrics={<>
      <Metric label="Quota used today" value={usage ? `${usage.units_today.toLocaleString()} of ${usage.daily_quota.toLocaleString()}` : "—"}><div className="source-bar"><i style={{ width: `${Math.min(100, ((usage?.units_today ?? 0) / (usage?.daily_quota ?? 1)) * 100)}%` }}/></div></Metric>
      <Metric label="Metadata calls today" value={String(usage?.video_calls_today ?? 0)}/>
      <Metric label="Last successful call" value={usage?.last_ok_at ? relativeTime(usage.last_ok_at, { suffix: true }) : "None yet"}/>
    </>}
    action={<Button variant="ghost" disabled={!status?.has_key || test.isPending} onClick={() => test.mutate()}>Test connection</Button>} result={summary} failed={state === "Error"}>
    <div className="source-grid">
      <SecretField label="API key" empty={!status?.has_key} masked={`••••••••••••${status?.key_last4 ?? ""}`} onReplace={() => setReplacing(true)}
        onRemove={fromApp && !remove.isPending ? () => { if (window.confirm("Remove the YouTube API key? ClipRelay goes back to reading YouTube’s public pages.")) remove.mutate(); } : undefined}
        note={fromApp ? (status?.updated_at ? `Saved on the server on ${day(status.updated_at)}` : "Saved on the server") : "Set in .env on the server — a key saved here replaces it"}/>
      <div className="source-field"><label htmlFor="youtube-project">Project ID</label>
        <form className="lookup-row" onSubmit={event => { event.preventDefault(); saveProject.mutate(); }}>
          <input id="youtube-project" value={projectValue} placeholder="your-google-cloud-project" spellCheck={false} autoComplete="off" onChange={event => setProject(event.target.value)}/>
          <Button type="submit" disabled={saveProject.isPending || project === null || project.trim() === (status?.project_id ?? "")}>{saveProject.isPending ? "Saving…" : "Save"}</Button>
        </form>
        <small className={projectError ? "bad" : ""}>{projectError ?? "The Google Cloud project the key belongs to. Only a note for you; it is not sent anywhere."}</small>
      </div>
    </div>
    {replacing && <ReplaceKeyModal label="API key" adding={!status?.has_key} onClose={() => setReplacing(false)} onSave={async key => { set(await youtubeApi.save({ api_key: key })); test.mutate(); }}/>}
  </CardShell>;
}

const SUBSCRIPTION: Record<PushSubscription["status"], { label: string; tone: Tone }> = {
  verified: { label: "Receiving", tone: "success" },
  pending: { label: "Waiting for hub", tone: "warning" },
  failed: { label: "Failed", tone: "danger" },
};

/** The monitored channels, each with the hub's own answer. */
function PushChannelList({ subscriptions }: { subscriptions: PushSubscription[] }) {
  if (subscriptions.length === 0) return <small className="source-hint">No channels are being monitored yet. Add one on the Channels page; it is subscribed by itself.</small>;
  return <div className="push-list">{subscriptions.map(item => <div key={item.channel_id}>
    <code>{item.channel_id}</code><span><Badge tone={SUBSCRIPTION[item.status].tone}>{SUBSCRIPTION[item.status].label}</Badge></span>
    <span className={item.status === "failed" ? "bad" : ""}>{item.detail}</span>
  </div>)}</div>;
}

/** Integrations → YouTube Push Notifications: the public address, the verify token and every channel's subscription. */
export function PushNotificationsCard() {
  const queryClient = useQueryClient();
  // Refreshes by itself, so a verification or a notification shows up while the page is open.
  const { data: status, error } = useQuery({ queryKey: ["push"], queryFn: push.info, refetchInterval: 5000 });
  const set = (next: PushInfo) => queryClient.setQueryData(["push"], next);
  const [base, setBase] = useState<string | null>(null);
  const [baseError, setBaseError] = useState<string | null>(null);
  const [channelId, setChannelId] = useState("");
  const [channelError, setChannelError] = useState<string | null>(null);
  const [replacing, setReplacing] = useState(false);
  const [showChannels, setShowChannels] = useState(false);
  const saveBase = useMutation({ mutationFn: () => push.save({ public_base_url: (base ?? "").trim() }), onSuccess: next => { set(next); setBase(null); setBaseError(null); queryClient.invalidateQueries({ queryKey: ["channels"] }); }, onError: reason => setBaseError(message(reason)) });
  const subscribe = useMutation({ mutationFn: () => push.subscribe(channelId.trim()), onSuccess: next => { set(next); setChannelId(""); setChannelError(null); setShowChannels(true); }, onError: reason => setChannelError(message(reason)) });
  const retry = useMutation({ mutationFn: push.retryFailed, onSuccess: set });

  const subscriptions = status?.subscriptions ?? [];
  const failed = subscriptions.filter(item => item.status === "failed");
  const verified = subscriptions.filter(item => item.status === "verified").length;
  const busy = saveBase.isPending || subscribe.isPending || retry.isPending;
  const state: State = !status?.available ? "Not configured" : error || failed.length > 0 ? "Error" : verified > 0 ? "Connected" : "Not configured";
  const baseValue = base ?? status?.public_base_url ?? "";

  return <CardShell icon="PS" title="YouTube Push Notifications" state={state} description="Receives upload notifications the moment a channel publishes. No API quota cost."
    metrics={<>
      <Metric label="Active subscriptions" value={`${verified} of ${subscriptions.length}`}/>
      <Metric label="Notifications today" value={String(status?.notifications.today ?? 0)}/>
      <Metric label="Failed renewals" value={String(failed.length)} danger={failed.length > 0}/>
    </>}
    action={<Button variant="ghost" disabled={busy || failed.length === 0} onClick={() => retry.mutate()}>{`Re-subscribe failed channels (${failed.length})`}</Button>}
    result={error ? message(error) : retry.isError ? message(retry.error) : busy ? "Working…" : !status?.available ? "No public address yet, so each channel’s upload feed is checked every few minutes instead." : "Channels are subscribed when added, and renewed and retried automatically."}
    failed={!!error || retry.isError}>
    {failed.length > 0 && <div className="form-error" style={{ marginTop: 0 }}>{failed.length} {failed.length === 1 ? "channel is" : "channels are"} not receiving notifications · <button type="button" className="link-button" onClick={() => setShowChannels(open => !open)}>{showChannels ? "Hide channels" : "View channels"}</button></div>}
    <div className="source-grid">
      <div className="source-field"><label htmlFor="push-base">Public base URL</label>
        <form className="lookup-row" onSubmit={event => { event.preventDefault(); saveBase.mutate(); }}>
          <input id="push-base" value={baseValue} placeholder="https://your-domain.com" spellCheck={false} autoComplete="off" onChange={event => setBase(event.target.value)}/>
          <Button type="submit" disabled={busy || base === null || base.trim() === (status?.public_base_url ?? "")}>{saveBase.isPending ? "Saving…" : "Save"}</Button>
        </form>
        <small className={baseError ? "bad" : ""}>{baseError ?? (status?.base_source === "env" ? "From PUBLIC_BASE_URL in .env — an address saved here replaces it." : "The public https:// address of this server (your domain, or a tunnel). YouTube sends the notifications there.")}</small>
      </div>
      <SecretField label="Verify token" empty={!status?.has_token} masked={`••••••••••••${status?.token_last4 ?? ""}`} onReplace={() => setReplacing(true)}
        note="Kept on the server · sent when subscribing, checked when the hub verifies"/>
      <ReadOnlyValue label="Callback URL" value={status?.callback_url || "Set the public base URL first"} copy={!!status?.callback_url}/>
      <div className="source-field"><label htmlFor="push-channel">Subscribe one channel</label>
        <form className="lookup-row" onSubmit={event => { event.preventDefault(); subscribe.mutate(); }}>
          <input id="push-channel" value={channelId} placeholder="Channel ID, e.g. UCxxxxxxxxxxxxxxxxxxxxxx" spellCheck={false} autoComplete="off" onChange={event => setChannelId(event.target.value)}/>
          <Button type="submit" variant="primary" disabled={!status?.available || busy || !channelId.trim()}>{subscribe.isPending ? "Subscribing…" : "Subscribe"}</Button>
        </form>
        <small className={channelError ? "bad" : ""}>{channelError ?? "Channels are subscribed by themselves when added. Use this to ask the hub again for one of them."}</small>
      </div>
    </div>
    {!showChannels && failed.length === 0 && subscriptions.length > 0 && <button type="button" className="link-button source-link" onClick={() => setShowChannels(true)}>View channels</button>}
    {showChannels && <PushChannelList subscriptions={subscriptions}/>}
    {replacing && <ReplaceKeyModal label="verify token" adding={!status?.has_token} onClose={() => setReplacing(false)} onSave={async token => set(await push.save({ verify_token: token }))}/>}
  </CardShell>;
}
