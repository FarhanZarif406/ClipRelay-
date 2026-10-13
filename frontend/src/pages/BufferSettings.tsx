import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { buffer } from "@/api/endpoints";
import type { BufferChannel, BufferChannelChanges, BufferStatus } from "@/api/types";
import { SecretInput } from "@/components/CredentialCard";
import { Field, Modal } from "@/components/Modal";
import { useToast } from "@/components/Toast";
import { Avatar, Button, Card, Empty, PageHeader, Spinner, Toggle } from "@/components/ui";
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
    <Field label="Posting times" hint="One clip goes out at each time, every day.">
      <div className="buffer-time-row">
        <select aria-label="Hour" value={hour} onChange={e => setHour(Number(e.target.value))}>{Array.from({ length: 12 }, (_, i) => <option key={i} value={i + 1}>{i + 1}</option>)}</select>
        <select aria-label="Minute" value={minute} onChange={e => setMinute(Number(e.target.value))}>{Array.from({ length: 12 }, (_, i) => <option key={i} value={i * 5}>{String(i * 5).padStart(2, "0")}</option>)}</select>
        <div className="segmented"><button type="button" className={period === "AM" ? "active" : ""} onClick={() => setPeriod("AM")}>AM</button><button type="button" className={period === "PM" ? "active" : ""} onClick={() => setPeriod("PM")}>PM</button></div>
        <Button disabled={times.includes(adding) || times.length >= MAX_TIMES} onClick={() => setTimes([...new Set([...times, adding])].sort())}>Add time</Button>
      </div>
      <div className="buffer-chips">
        {times.map(time => <span className="buffer-chip" key={time}>{to12Hour(time)}<button type="button" aria-label={`Remove ${to12Hour(time)}`} onClick={() => setTimes(times.filter(item => item !== time))}>×</button></span>)}
        {times.length === 0 && <span className="bad">No times yet: nothing can be scheduled on this account.</span>}
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

/** One Buffer account: whether clips go to it, and its schedule at a glance. The schedule is changed in a dialog. */
function ChannelCard({ channel, onSave }: { channel: BufferChannel; onSave: (changes: BufferChannelChanges, done: string) => Promise<boolean> }) {
  const [scheduling, setScheduling] = useState(false);
  const [watching, setWatching] = useState(false);
  return <Card className="buffer-card">
    <div className="buffer-card-head"><Avatar label={initialsOf(channel.name)}/>
      <div><strong>{channel.name}</strong><span>{serviceName(channel.service)} · {channel.used_today} of {channel.daily_limit} scheduled for today · {channel.uploaded} uploaded so far{channel.waiting > 0 ? ` · ${channel.waiting} waiting at Buffer` : ""}</span></div>
      <label><span>{channel.enabled ? "Clips go here" : "Off"}</span><Toggle checked={channel.enabled} label={`Send clips to ${channel.name}`} onChange={() => void onSave({ enabled: !channel.enabled }, channel.enabled ? `${channel.name} is off. No clips go to it.` : `${channel.name} is on.`)}/></label>
    </div>
    <div className="buffer-card-foot">
      <div>
        <div className="buffer-chips">{channel.times.map(time => <span className="buffer-chip" key={time}>{to12Hour(time)}</span>)}{channel.times.length === 0 && <span className="bad">No posting times yet.</span>}</div>
        <small>{channel.time_zone.replace(/_/g, " ")} · up to {channel.daily_limit} a day{channel.start_date ? ` · from ${longDay(channel.start_date)}` : ""}</small>
        <small>{!channel.enabled ? "Switched off." : channel.next_slot ? `Next clip: ${inZone(channel.next_slot, channel.time_zone)}.` : "Press Schedule and add at least one posting time."}</small>
      </div>
      <span><Button onClick={() => setWatching(true)}>Live status</Button><Button variant="primary" onClick={() => setScheduling(true)}>Schedule</Button></span>
    </div>
    {watching && <ChannelStatusModal channel={channel} onClose={() => setWatching(false)}/>}
    {scheduling && <ScheduleModal channel={channel} onSave={changes => onSave(changes, `Saved the schedule for ${channel.name}.`)} onClose={() => setScheduling(false)}/>}
  </Card>;
}

/**
 * The member's own Buffer connection: their API key, and for each account connected in Buffer
 * whether clips go to it, and its schedule: timezone, start date, times of day and daily limit.
 */
export default function BufferSettings() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { data: status, error: loadError } = useQuery({ queryKey: ["buffer"], queryFn: buffer.info });
  const [key, setKey] = useState("");
  const [replacing, setReplacing] = useState(false);
  const [busy, setBusy] = useState(false);

  /** Runs one change, shows how it went, and lets the rest of the app see the new accounts. */
  const run = async (work: () => Promise<BufferStatus>, done: string) => {
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
  const saveKey = async (event: FormEvent) => {
    event.preventDefault();
    if (!key.trim() || busy) return;
    if (await run(() => buffer.saveKey(key.trim()), "Buffer accepted the key. Your accounts are listed below.")) { setKey(""); setReplacing(false); }
  };
  const removeKey = () => {
    if (window.confirm("Remove your Buffer API key? Clips will no longer be sent to Buffer. Posts already scheduled in Buffer stay there.")) void run(buffer.removeKey, "Your Buffer API key was removed.");
  };
  const connected = !!status?.connected;
  const active = status?.channels.filter(channel => channel.enabled).length ?? 0;

  return <><PageHeader title="Buffer Settings" description={`Finished ${PODCASTS ? "clips" : "videos"} are sent to your Buffer account, which publishes them to the accounts you connected there. This key and these settings are yours alone.`}>
    {connected && <Button icon="refresh" disabled={busy} onClick={() => void run(buffer.refresh, "Read your accounts from Buffer again.")}>Refresh accounts</Button>}</PageHeader>
    <div className="buffer-page">
      {loadError && <div className="form-error">{message(loadError)}</div>}
      {status && !status.public_url && <div className="form-note warn">The server has no public address yet, so Buffer cannot fetch clips from it. An admin sets the public base URL in Integrations → YouTube Push Notifications.</div>}
      {status?.error && <div className="form-error">{status.error}</div>}

      <Card><div className="card-title">Buffer API key</div>
        <div className="card-caption">Create it in Buffer under Settings → API. It needs the permissions <b>account:read</b>, <b>posts:read</b> and <b>posts:write</b>.</div>
        {connected && !replacing
          ? <div className="source-secret" style={{ marginTop: 12 }}><div><code>••••••••••••{status.last4}</code><small>Saved {status.saved_at ? savedDay(status.saved_at) : ""} · kept on the server, never shown again</small></div>
            <Button variant="ghost" onClick={() => setReplacing(true)}>Replace</Button><Button variant="danger" disabled={busy} onClick={removeKey}>Remove</Button></div>
          : <form onSubmit={event => void saveKey(event)} style={{ marginTop: 12 }}>
            <Field label={connected ? "New API key" : "API key"} hint="The key is checked with Buffer before it is saved."><SecretInput value={key} onChange={setKey} placeholder="Paste your Buffer API key"/></Field>
            <div className="inline-form"><Button variant="primary" type="submit" disabled={!key.trim() || busy}>{busy ? "Checking with Buffer…" : "Save key"}</Button>{replacing && <Button onClick={() => { setReplacing(false); setKey(""); }}>Cancel</Button>}</div>
          </form>}
      </Card>

      {connected && <>
        <div><div className="card-title">Your accounts{PODCASTS ? " · Podcasts workspace" : ""}</div>
          <div className="card-caption">{status.channels.length} connected in Buffer · {active} receiving clips. “Auto” sends each clip to the account whose next time comes first.</div></div>
        {status.channels.length === 0
          ? <Card><Empty icon="plus" title="No accounts are connected in Buffer yet">Connect an account in Buffer, then press “Refresh accounts”.</Empty></Card>
          : status.channels.map(channel => <ChannelCard key={channel.id} channel={channel} onSave={(changes, done) => run(() => buffer.updateChannel(channel.id, changes), done)}/>)}
      </>}
    </div>
  </>;
}
