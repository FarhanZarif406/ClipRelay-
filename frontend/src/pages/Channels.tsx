import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { channels } from "@/api/endpoints";
import type { Channel, Tone } from "@/api/types";
import { Icon } from "@/components/Icon";
import { Menu } from "@/components/Menu";
import { useErrorToast, useToast } from "@/components/Toast";
import { Badge, Button, Card, Empty, PageHeader, Spinner, Toggle } from "@/components/ui";
import { dayTime, relativeTime } from "@/lib/format";
import { PODCASTS } from "@/lib/mode";

function ChannelAvatar({ channel }: { channel: { thumbnail_url: string | null; display_name: string } }) {
  return channel.thumbnail_url ? <img src={channel.thumbnail_url} alt="" referrerPolicy="no-referrer"/> : <div className="channel-blank"><Icon name="play" size={13}/></div>;
}

/** Paste a link, press Add: the channel is looked up, saved and subscribed in one step. */
function AddChannelForm() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const add = useMutation({
    mutationFn: (submitted: string) => channels.create({ query: submitted }),
    onSuccess: (c, submitted) => {
      queryClient.invalidateQueries({ queryKey: ["channels"] });
      queryClient.invalidateQueries({ queryKey: ["nav"] });
      toast({ title: "Channel added", message: `${c.display_name} is now monitored for new uploads.` });
      setQuery(current => (current === submitted ? "" : current));  // what was typed meanwhile is kept
    },
    onError: e => setError(e instanceof Error ? e.message : String(e)),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); if (query.trim() && !add.isPending) { setError(null); add.mutate(query.trim()); } };

  return <Card className="add-channel"><form className="lookup-row" onSubmit={submit} noValidate>
    <input autoFocus value={query} className={error ? "invalid" : ""} onChange={e => { setQuery(e.target.value); setError(null); }} placeholder="Paste a YouTube channel URL or @handle" aria-label="YouTube channel URL or handle" aria-invalid={!!error}/>
    <Button type="submit" variant="primary" disabled={add.isPending || !query.trim()}>{add.isPending ? "Adding…" : "Add channel"}</Button>
  </form>
    {error ? <p role="alert" className="add-channel-note bad">{error}</p> : <p className="add-channel-note">{PODCASTS ? "Only podcasts uploaded after you add a channel are cut into clips." : "Only uploads made after you add a channel are republished."} Each video goes to the Buffer account whose next free time comes first.</p>}
  </Card>;
}

const PUSH: Record<Channel["push_status"], { label: string; tone: Tone }> = {
  subscribed: { label: "Push active", tone: "success" },
  pending: { label: "Push pending", tone: "warning" },
  expired: { label: "Push expired", tone: "danger" },
  failed: { label: "Push failed", tone: "danger" },
  unavailable: { label: "Checked", tone: "success" },
  off: { label: "Off", tone: "neutral" },
};

function PushStatus({ channel, pollMinutes }: { channel: Channel; pollMinutes: number }) {
  const status = PUSH[channel.push_status];
  const label = channel.push_status === "unavailable" ? `Checked every ${pollMinutes} min` : status.label;
  const detail = channel.push_status === "subscribed" && channel.push_expires_at ? `Renews before ${dayTime(channel.push_expires_at)}` : channel.push_detail;
  return <div title={detail ?? undefined}><Badge tone={status.tone}>{label}</Badge>{detail && <div className="cell-sub">{detail}</div>}</div>;
}

export default function Channels() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const list = useQuery({ queryKey: ["channels"], queryFn: channels.list, refetchInterval: 30_000 });
  const refresh = () => { queryClient.invalidateQueries({ queryKey: ["channels"] }); queryClient.invalidateQueries({ queryKey: ["nav"] }); };
  const update = useMutation({ mutationFn: ({ id, body }: { id: number; body: Parameters<typeof channels.update>[1] }) => channels.update(id, body), onSuccess: refresh, onError });
  const remove = useMutation({ mutationFn: (id: number) => channels.remove(id), onSuccess: () => { refresh(); toast({ title: "Channel removed" }); }, onError });
  const check = useMutation({
    mutationFn: (c: Channel) => channels.check(c.id),
    onSuccess: (r, c) => { refresh(); queryClient.invalidateQueries({ queryKey: ["jobs"] }); toast(r.error ? { title: "Check failed", message: r.error, tone: "danger" } : { title: r.found ? `${r.found} new video${r.found === 1 ? "" : "s"} found` : "No new uploads", message: r.found ? `${r.queued} queued, ${r.skipped} skipped · ${c.display_name}` : c.display_name }); },
    onError,
  });
  const items = list.data?.items ?? [];
  const askRemove = (c: Channel) => { if (window.confirm(`Stop monitoring ${c.display_name}? Its published history is kept.`)) remove.mutate(c.id); };

  return <><PageHeader title={PODCASTS ? "Podcast Channels" : "Channels"} description={PODCASTS ? "YouTube channels that publish long videos. Every new podcast is cut into short clips and published through Buffer." : "The YouTube channels being watched. Every new short-form upload is republished through Buffer."}></PageHeader>
    <AddChannelForm/>
    {list.data && !list.data.push_available && <p className="note-row">No public address is set for YouTube push notifications, so new uploads are found by checking each channel every {list.data.poll_minutes} minutes instead. An admin can set the address in Integrations → YouTube Push Notifications.</p>}
    <Card className="table-card"><div className="table-wrap"><table><thead><tr><th>Channel</th><th>Last upload</th><th>{PODCASTS ? "Clips published" : "Published"}</th><th>Skipped</th><th>Push status</th><th>Last checked</th><th>Active</th><th/></tr></thead><tbody>
      {items.map(c => <tr key={c.id}>
        <td><div className="channel-cell"><ChannelAvatar channel={c}/><div><strong>{c.display_name}</strong><span>{c.handle ?? c.youtube_channel_id}{c.override_count ? ` · ${c.override_count} override${c.override_count === 1 ? "" : "s"}` : ""}</span></div></div></td>
        <td>{c.last_upload_at ? relativeTime(c.last_upload_at, { suffix: true }) : "—"}</td>
        <td>{c.videos_published}</td><td>{c.videos_skipped}</td>
        <td><PushStatus channel={c} pollMinutes={list.data?.poll_minutes ?? 15}/></td>
        <td>{c.last_error ? <span className="cell-error" title={c.last_error}>{c.last_error}</span> : c.last_checked_at ? relativeTime(c.last_checked_at, { suffix: true }) : "Not yet"}</td>
        <td><Toggle checked={c.active} disabled={update.isPending} label={`Monitor ${c.display_name}`} onChange={() => { if (!update.isPending) update.mutate({ id: c.id, body: { active: !c.active } }); }}/></td>
        <td><Menu items={[{ label: "Check now", icon: "refresh", disabled: !c.active, onSelect: () => check.mutate(c) }, { label: "Open on YouTube", icon: "link", onSelect: () => window.open(c.url, "_blank", "noopener") }, { label: "Remove", icon: "close", danger: true, onSelect: () => askRemove(c) }]} trigger={t => <Button variant="ghost" icon="more" onClick={t}/>}/></td>
      </tr>)}</tbody></table></div>
      {list.isLoading && <Spinner/>}
      {!list.isLoading && items.length === 0 && <Empty icon="play" title="No channels yet">{PODCASTS ? "Paste the link of a YouTube channel that publishes podcasts or other long videos in the box above." : "Paste a YouTube channel link in the box above to start detecting new uploads."}</Empty>}
    </Card>
  </>;
}
