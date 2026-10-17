import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { buffer } from "@/api/endpoints";
import type { BufferChannel, BufferChannelChanges, BufferKey, BufferStatus } from "@/api/types";
import { SecretInput } from "@/components/CredentialCard";
import { Field, Modal } from "@/components/Modal";
import { useToast } from "@/components/Toast";
import { Avatar, Badge, Button, Card, Empty, PageHeader, Spinner, Toggle } from "@/components/ui";
import { initialsOf } from "@/lib/format";
import { PODCASTS } from "@/lib/mode";

const MAX_TIMES = 24;
const message = (error: unknown) => (error instanceof Error ? error.message : String(error));
type ZoneList = { supportedValuesOf?: (key: "timeZone") => string[] };  // newer than this project's TypeScript library
const knownZones: string[] = (Intl as unknown as ZoneList).supportedValuesOf?.("timeZone") ?? [];
const serviceName = (name: string) => (name === "tiktok" ? "TikTok" : name ? name[0].toUpperCase() + name.slice(1) : "Account");
const longDay = (value: string) => new Date(`${value}T12:00:00Z`).toLocaleDateString("en-GB", { timeZone: "UTC", day: "numeric", month: "short", year: "numeric" });
const savedDay = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });

/** "14:30" as people read it: "2:30 PM". */
function to12Hour(time: string) {
  const [hour, minute] = time.split(":").map(Number);
  return `${hour % 12 || 12}:${String(minute).padStart(2, "0")} ${hour < 12 ? "AM" : "PM"}`;
}
/** An hour of 1–12 with AM or PM, and a minute, as "HH:MM" on the 24-hour clock. */
function to24Hour(hour: number, minute: number, period: "AM" | "PM") {
  return `${String((hour % 12) + (period === "PM" ? 12 : 0)).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}
const inZone = (iso: string, timeZone: string, weekday = true) =>
  new Date(iso).toLocaleString("en-US", { timeZone, ...(weekday ? { weekday: "short" as const } : {}), day: "numeric", month: "short", hour: "numeric", minute: "2-digit", hour12: true });

/** The schedule of one Buffer account: its timezone, start date, times of day and daily limit. */
function ScheduleModal({ channel, onSave, onClose }: { channel: BufferChannel; onSave: (changes: BufferChannelChanges) => Promise<boolean>; onClose: () => void }) {
  const [timeZone, setTimeZone] = useState(channel.time_zone);
  const [startDate, setStartDate] = useState(channel.start_date ?? "");
  const [times, setTimes] = useState(channel.times);
  const [limit, setLimit] = useState(String(channel.daily_limit));
  // The time being put together, before it is added to the list.
  const [hour, setHour] = useState(9);
  const [minute, setMinute] = useState(0);
  const [period, setPeriod] = useState<"AM" | "PM">("AM");
  const [saving, setSaving] = useState(false);
  const zones = knownZones.includes(timeZone) ? knownZones : [timeZone, ...knownZones];
  const adding = to24Hour(hour, minute, period);
  const limitNumber = Number(limit);
  const valid = Number.isInteger(limitNumber) && limitNumber >= 1 && limitNumber <= 50;
  const save = async () => {
    setSaving(true);
    const saved = await onSave({ time_zone: timeZone, start_date: startDate || null, times, daily_limit: limitNumber });
    setSaving(false);
    if (saved) onClose();
  };

  return <Modal title={`Schedule · ${channel.name}`} caption="When clips go out on this account." onClose={onClose}
    footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!valid || saving} onClick={() => void save()}>{saving ? "Saving…" : "Save schedule"}</Button></>}>
    <Field label="Time zone" hint="The times below are on this clock."><select value={timeZone} onChange={e => setTimeZone(e.target.value)}>{zones.map(zone => <option key={zone} value={zone}>{zone.replace(/_/g, " ")}</option>)}</select></Field>
    <Field label="Start date" hint={startDate ? "No clip goes out on this account before this day." : "Empty: clips go out from the next free time."}>
      <div className="lookup-row"><input type="date" value={startDate} onChange={e => setStartDate(e.target.value)}/>{startDate && <Button onClick={() => setStartDate("")}>Clear</Button>}</div></Field>
    <Field label="Posting times" hint="One clip goes out at each time, every day. Leave it empty to publish each clip at once instead.">
      <div className="buffer-time-row">
        <select aria-label="Hour" value={hour} onChange={e => setHour(Number(e.target.value))}>{Array.from({ length: 12 }, (_, i) => <option key={i} value={i + 1}>{i + 1}</option>)}</select>
        <select aria-label="Minute" value={minute} onChange={e => setMinute(Number(e.target.value))}>{Array.from({ length: 12 }, (_, i) => <option key={i} value={i * 5}>{String(i * 5).padStart(2, "0")}</option>)}</select>
        <div className="segmented"><button type="button" className={period === "AM" ? "active" : ""} onClick={() => setPeriod("AM")}>AM</button><button type="button" className={period === "PM" ? "active" : ""} onClick={() => setPeriod("PM")}>PM</button></div>
        <Button disabled={times.includes(adding) || times.length >= MAX_TIMES} onClick={() => setTimes([...new Set([...times, adding])].sort())}>Add time</Button>
      </div>
      <div className="buffer-chips">
        {times.map(time => <span className="buffer-chip" key={time}>{to12Hour(time)}<button type="button" aria-label={`Remove ${to12Hour(time)}`} onClick={() => setTimes(times.filter(item => item !== time))}>×</button></span>)}
        {times.length === 0 && <span className="muted">No times: each clip is published at once when it is this account’s turn, up to the daily limit.</span>}
      </div>
    </Field>
    <Field label="Daily limit" hint="At most this many clips on one day. Any more go out on the next day.">
      <input type="number" min={1} max={50} value={limit} onChange={e => setLimit(e.target.value)}/></Field>
  </Modal>;
}

const PERIODS = [["today", "Today"], ["week", "Last 7 days"], ["month", "Last 30 days"], ["lifetime", "Lifetime"]] as const;
const CLIP_STATE = { scheduled: ["Waiting at Buffer", "warn"], published: ["Uploaded", "good"], failed: ["Failed", "bad"] } as const;

/** One Buffer account's live status: what is on its way, what was uploaded and what failed, over time. */
function ChannelStatusModal({ channel, onClose }: { channel: BufferChannel; onClose: () => void }) {
  const { data: status, error } = useQuery({ queryKey: ["buffer", "status", channel.id], queryFn: () => buffer.channelStatus(channel.id), refetchInterval: 10_000 });
  const when = (iso: string) => inZone(iso, status?.time_zone ?? channel.time_zone, false);
  return <Modal className="wide" title={`Live status · ${channel.name}`} onClose={onClose} footer={<Button onClick={onClose}>Close</Button>}>
    {error && <div className="form-error">{message(error)}</div>}
    {!status && !error && <Spinner/>}
    {status && <div className="buffer-status">
      <div className="buffer-status-now"><div><small>On its way to Buffer now</small><b>{status.sending}</b></div><div><small>At Buffer, waiting for its time</small><b>{status.waiting}</b></div></div>
      <div className="table-wrap"><table><thead><tr><th>Clips</th>{PERIODS.map(([key, label]) => <th key={key} style={{ textAlign: "right" }}>{label}</th>)}</tr></thead><tbody>
        <tr><td className="good">Uploaded</td>{PERIODS.map(([key]) => <td key={key} style={{ textAlign: "right" }}><strong>{status.uploaded[key]}</strong></td>)}</tr>
        <tr><td className="bad">Not uploaded (failed)</td>{PERIODS.map(([key]) => <td key={key} style={{ textAlign: "right" }}>{status.failed[key]}</td>)}</tr>
      </tbody></table></div>
      <div className="section-label" style={{ margin: 0 }}>Latest clips on this account</div>
      {status.recent.length === 0 ? <p className="note-row">No clip has been sent to this account yet.</p> : <ul className="buffer-recent">{status.recent.map(clip => <li key={clip.id}>
        <span><span title={clip.title}>{clip.title}</span><b className={CLIP_STATE[clip.state][1]}>{CLIP_STATE[clip.state][0]}</b></span>
        <small>{clip.state === "scheduled" && clip.due_at && `Goes out ${when(clip.due_at)}`}{clip.state === "published" && clip.done_at && `Uploaded ${when(clip.done_at)}`}{clip.state === "failed" && `${clip.done_at ? `${when(clip.done_at)} · ` : ""}${clip.error ?? "No reason given"}`}</small>
      </li>)}</ul>}
      <small className="muted">Updates every 10 seconds. Days are counted on this account’s clock ({status.time_zone.replace(/_/g, " ")}).</small>
    </div>}
  </Modal>;
}

/** The small mark of the network on an account's picture. */
function ServiceMark({ service }: { service: string }) {
  if (service === "tiktok") return <span className="acct-mark" title="TikTok"><svg viewBox="0 0 24 24" width="12" height="12" aria-hidden><path fill="currentColor" d="M16.6 5.8A4.3 4.3 0 0 1 15.5 3h-3.1v12.4a2.6 2.6 0 1 1-2.6-2.6c.3 0 .5 0 .8.1V9.7a5.7 5.7 0 1 0 4.9 5.7V9.1a7.3 7.3 0 0 0 4.3 1.4V7.4a4.3 4.3 0 0 1-3.2-1.6Z"/></svg></span>;
  return <span className="acct-mark" title={serviceName(service)}>{serviceName(service).slice(0, 1)}</span>;
}

/** One Buffer account as a card: its switch, today's limit at a glance, its numbers, and its schedule. */
function ChannelCard({ channel, upNext, onSave }: { channel: BufferChannel; upNext: boolean; onSave: (changes: BufferChannelChanges, done: string) => Promise<boolean> }) {
  const [scheduling, setScheduling] = useState(false);
  const [watching, setWatching] = useState(false);
  const left = Math.max(0, channel.daily_limit - channel.used_today);
  const share = Math.min(100, (channel.used_today / Math.max(1, channel.daily_limit)) * 100);
  const zone = channel.time_zone.replace(/_/g, " ");
  const schedule = channel.at_once ? "No schedule · clips are published right away" : `Posts at ${channel.times.map(to12Hour).join(", ")}`;
  const next = !channel.enabled ? "Switched off: no clips go to this account."
    : channel.at_once ? (channel.next_slot ? "Published at once, taking turns with your other accounts." : "Today’s limit is used, or its start date has not come: its next clip waits.")
      : channel.next_slot ? `Next free time: ${inZone(channel.next_slot, channel.time_zone)}.` : "No free time in the next two months.";
  return <Card className={`acct-card ${channel.enabled ? "" : "off"}`}>
    <div className="acct-head">
      <div className="acct-photo">{channel.avatar ? <img src={channel.avatar} alt="" referrerPolicy="no-referrer"/> : <Avatar label={initialsOf(channel.name)}/>}<ServiceMark service={channel.service}/></div>
      <div className="acct-name">
        <strong title={channel.name}>{channel.name}</strong>
        <span>{serviceName(channel.service)} · via Buffer</span>
        <span className={`acct-pill ${channel.enabled ? "on" : ""}`}><i/>{channel.enabled ? "Connected · receiving clips" : "Connected · switched off"}</span>
      </div>
      <label className="acct-switch"><Toggle checked={channel.enabled} label={`Send clips to ${channel.name}`} onChange={() => void onSave({ enabled: !channel.enabled }, channel.enabled ? `${channel.name} is off. No clips go to it.` : `${channel.name} is on.`)}/><span>{channel.enabled ? "On" : "Off"}</span></label>
    </div>
    <div className="acct-today">
      <div><small>Today’s limit</small><b className={left ? "good" : "bad"}>{left} left</b></div>
      <p><strong>{channel.used_today}</strong> of {channel.daily_limit} clips used</p>
      <div className="acct-bar"><i style={{ width: `${share}%` }} className={left ? "" : "full"}/></div>
    </div>
    <div className="acct-numbers">
      <div><small>Uploaded</small><b>{channel.uploaded}</b></div>
      <div><small>Waiting</small><b>{channel.waiting}</b></div>
      <div><small>Daily limit</small><b>{channel.daily_limit}</b></div>
    </div>
    <div className="acct-schedule">
      <span>{schedule}{upNext && channel.enabled ? <Badge tone="success">Next turn</Badge> : null}</span>
      <small>{next} · {zone}{channel.start_date ? ` · from ${longDay(channel.start_date)}` : ""}</small>
    </div>
    <div className="acct-actions"><Button onClick={() => setWatching(true)}>Live status</Button><Button variant="primary" onClick={() => setScheduling(true)}>Schedule</Button></div>
    {watching && <ChannelStatusModal channel={channel} onClose={() => setWatching(false)}/>}
    {scheduling && <ScheduleModal channel={channel} onSave={changes => onSave(changes, `Saved the schedule for ${channel.name}.`)} onClose={() => setScheduling(false)}/>}
  </Card>;
}

/** The four numbers above the cards: connected, receiving clips, used today and left today. */
function AccountsSummary({ channels }: { channels: BufferChannel[] }) {
  const on = channels.filter(c => c.enabled);
  const limit = on.reduce((sum, c) => sum + c.daily_limit, 0);
  const used = on.reduce((sum, c) => sum + Math.min(c.used_today, c.daily_limit), 0);
  return <div className="acct-summary">
    <div><small>Connected</small><b>{channels.length}</b><span>in Buffer</span></div>
    <div><small>Receiving clips</small><b>{on.length}</b><span>{on.length === channels.length ? "all accounts" : `${channels.length - on.length} switched off`}</span></div>
    <div><small>Used today</small><b>{used} / {limit}</b><span>clips across accounts that are on</span></div>
    <div><small>Left today</small><b>{Math.max(0, limit - used)}</b><span>clips that can still go out</span></div>
  </div>;
}

type Run = (work: () => Promise<BufferStatus>, done: string) => Promise<boolean>;

/** One saved key: its name and last four characters, how many accounts it reaches; rename, replace or remove it. */
function KeyRow({ item, busy, run }: { item: BufferKey; busy: boolean; run: Run }) {
  const [editing, setEditing] = useState<"" | "rename" | "replace">("");
  const [value, setValue] = useState("");
  const close = () => { setEditing(""); setValue(""); };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!value.trim() || busy) return;
    const saved = editing === "rename"
      ? await run(() => buffer.updateKey(item.id, { label: value.trim() }), `Renamed to “${value.trim()}”.`)
      : await run(() => buffer.updateKey(item.id, { api_key: value.trim() }), `Buffer accepted the new key for ${item.label}.`);
    if (saved) close();
  };
  const remove = () => {
    if (window.confirm(`Remove ${item.label}? Its ${item.accounts} account${item.accounts === 1 ? "" : "s"} will no longer get clips. Posts already scheduled in Buffer stay there.`))
      void run(() => buffer.removeKey(item.id), `${item.label} was removed.`);
  };
  return <div className="buffer-key">
    <div className="source-secret"><div>
      <span className="buffer-key-name"><b>{item.label}</b><code>••••••••{item.last4}</code></span>
      <small>{item.accounts} account{item.accounts === 1 ? "" : "s"} · {item.receiving} receiving clips · saved {savedDay(item.saved_at)}</small>
      {item.error && <small className="bad">{item.error}</small>}
    </div>
      <Button variant="ghost" onClick={() => { setEditing("rename"); setValue(item.label); }}>Rename</Button>
      <Button variant="ghost" onClick={() => { setEditing("replace"); setValue(""); }}>Replace</Button>
      <Button variant="danger" disabled={busy} onClick={remove}>Remove</Button></div>
    {editing && <form className="buffer-key-form" onSubmit={event => void submit(event)}>
      {editing === "rename"
        ? <Field label="Name"><input value={value} maxLength={40} onChange={e => setValue(e.target.value)} autoFocus/></Field>
        : <Field label={`New API key for ${item.label}`} hint="Checked with Buffer before it replaces the old one."><SecretInput value={value} onChange={setValue} placeholder="Paste the new Buffer API key"/></Field>}
      <div className="inline-form"><Button variant="primary" type="submit" disabled={!value.trim() || busy}>{busy ? "Saving…" : editing === "rename" ? "Save name" : "Save key"}</Button><Button onClick={close}>Cancel</Button></div>
    </form>}
  </div>;
}

/** Adds one more key. The name is optional: "Key 2", "Key 3", … otherwise. */
function AddKey({ first, busy, run }: { first: boolean; busy: boolean; run: Run }) {
  const [open, setOpen] = useState(first);
  const [key, setKey] = useState("");
  const [label, setLabel] = useState("");
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!key.trim() || busy) return;
    if (await run(() => buffer.addKey(key.trim(), label.trim()), "Buffer accepted the key. Its accounts are listed below.")) { setKey(""); setLabel(""); setOpen(first); }
  };
  if (!open) return <div><Button icon="plus" onClick={() => setOpen(true)}>Add another key</Button></div>;
  return <form className="buffer-key-form" onSubmit={event => void submit(event)}>
    <div className="buffer-key-fields">
      <Field label="Name (optional)" hint="For example the Buffer account it belongs to."><input value={label} maxLength={40} placeholder="Key name" onChange={e => setLabel(e.target.value)}/></Field>
      <Field label="API key" hint="The key is checked with Buffer before it is saved."><SecretInput value={key} onChange={setKey} placeholder="Paste a Buffer API key"/></Field>
    </div>
    <div className="inline-form"><Button variant="primary" type="submit" disabled={!key.trim() || busy}>{busy ? "Checking with Buffer…" : "Save key"}</Button>{!first && <Button onClick={() => { setOpen(false); setKey(""); setLabel(""); }}>Cancel</Button>}</div>
  </form>;
}

/**
 * The member's own Buffer connection: up to ten API keys, and for each account those keys reach in Buffer
 * whether clips go to it, and its schedule: timezone, start date, times of day and daily limit.
 * The switched-on accounts take turns, so every one of them gets clips.
 */
export default function BufferSettings() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { data: status, error: loadError } = useQuery({ queryKey: ["buffer"], queryFn: buffer.info });
  const [busy, setBusy] = useState(false);

  /** Runs one change, shows how it went, and lets the rest of the app see the new accounts. */
  const run: Run = async (work, done) => {
    setBusy(true);
    try {
      queryClient.setQueryData(["buffer"], await work());
      toast({ title: done });
      queryClient.invalidateQueries({ queryKey: ["publishing-route"] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      return true;
    } catch (reason) {
      toast({ title: "Not saved", message: message(reason), tone: "danger" });
      return false;
    } finally {
      setBusy(false);
    }
  };
  const connected = !!status?.connected;
  const groups = (status?.keys ?? []).map(item => ({ item, channels: status!.channels.filter(channel => channel.key_id === item.id) }));

  return <><PageHeader title="Buffer Settings" description={`Finished ${PODCASTS ? "clips" : "videos"} are sent to your Buffer accounts, which publish them to the accounts you connected there. These keys and settings are yours alone.`}>
    {connected && <Button icon="refresh" disabled={busy} onClick={() => void run(buffer.refresh, "Read your accounts from Buffer again.")}>Refresh accounts</Button>}</PageHeader>
    <div className="buffer-page">
      {loadError && <div className="form-error">{message(loadError)}</div>}
      {status && !status.public_url && <div className="form-note warn">The server has no public address yet, so Buffer cannot fetch clips from it. An admin sets the public base URL in Integrations → YouTube Push Notifications.</div>}

      {status && <Card><div className="card-title">Buffer API keys <span className="muted">· {status.keys.length} of {status.max_keys}</span></div>
        <div className="card-caption">Create a key in Buffer under Settings → API. It needs the permissions <b>account:read</b>, <b>posts:read</b> and <b>posts:write</b>. Add up to {status.max_keys} key{status.max_keys === 1 ? "" : "s"}, one per Buffer account; all their accounts get clips in turn.{status.max_accounts ? ` Your plan connects up to ${status.max_accounts} social accounts in all; any more in Buffer are left out.` : ""}</div>
        <div className="buffer-keys">
          {status.keys.map(item => <KeyRow key={item.id} item={item} busy={busy} run={run}/>)}
          {status.keys.length < status.max_keys
            ? <AddKey key={status.keys.length === 0 ? "first" : "more"} first={status.keys.length === 0} busy={busy} run={run}/>
            : <small className="muted">All {status.max_keys} keys are in use. Remove one to add another.</small>}
        </div>
      </Card>}

      {connected && <>
        <div><div className="card-title">Connected accounts{PODCASTS ? " · Podcasts workspace" : ""}</div>
          <div className="card-caption">Clips take turns across the accounts that are on, one account after another, each within its own daily limit.{status.max_accounts ? ` Your plan connects up to ${status.max_accounts} accounts.` : ""}</div></div>
        <AccountsSummary channels={status.channels}/>
        {groups.map(({ item, channels }) => <section className="buffer-group" key={item.id}>
          {groups.length > 1 && <div className="section-label">{item.label} <span className="muted">· <code>••••{item.last4}</code> · {channels.length} account{channels.length === 1 ? "" : "s"}</span></div>}
          {channels.length === 0
            ? <Card><Empty icon="plus" title="No accounts on this key yet">Connect an account in Buffer, then press “Refresh accounts”. An account another of your keys already reaches is listed under that key.</Empty></Card>
            : <div className="acct-grid">{channels.map(channel => <ChannelCard key={channel.id} channel={channel} upNext={status.up_next === channel.id} onSave={(changes, done) => run(() => buffer.updateChannel(channel.id, changes), done)}/>)}</div>}
        </section>)}
      </>}
    </div>
  </>;
}
