import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { channels, tiktok } from "@/api/endpoints";
import type { Channel, ChannelCard, Tone } from "@/api/types";
import { Icon } from "@/components/Icon";
import { Menu } from "@/components/Menu";
import { Field, Modal } from "@/components/Modal";
import { useErrorToast, useToast } from "@/components/Toast";
import { Badge, Button, Card, Empty, PageHeader, Spinner, Toggle } from "@/components/ui";
import { dayTime, relativeTime } from "@/lib/format";

function ChannelAvatar({ channel }: { channel: { thumbnail_url: string | null; display_name: string } }) {
  return channel.thumbnail_url ? <img src={channel.thumbnail_url} alt="" referrerPolicy="no-referrer"/> : <div className="channel-blank"><Icon name="play" size={13}/></div>;
}

function AddChannelModal({ close }: { close: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [query, setQuery] = useState("");
  const [card, setCard] = useState<ChannelCard | null>(null);
  const [accountId, setAccountId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const accounts = useQuery({ queryKey: ["tiktok"], queryFn: tiktok.list });
  const fail = (e: unknown) => setError(e instanceof Error ? e.message : String(e));
  const lookup = useMutation({ mutationFn: () => channels.resolve(query.trim()), onSuccess: c => { setCard(c); setError(null); }, onError: fail });
  const save = useMutation({
    mutationFn: () => channels.create({ query: card!.youtube_channel_id, default_tiktok_account_id: accountId ? Number(accountId) : null }),
    onSuccess: c => { queryClient.invalidateQueries({ queryKey: ["channels"] }); queryClient.invalidateQueries({ queryKey: ["nav"] }); toast({ title: "Channel added", message: `${c.display_name} is now monitored for new uploads.` }); close(); },
    onError: fail,
  });
  const submit = (e: FormEvent) => { e.preventDefault(); setCard(null); if (query.trim()) lookup.mutate(); };

  return <Modal title="Add channel" caption="One channel at a time, by URL or @handle. Only uploads made after you add it are republished." onClose={close}
    footer={<><Button onClick={close}>Cancel</Button><Button variant="primary" disabled={!card || card.already_added || save.isPending} onClick={() => save.mutate()}>{save.isPending ? "Adding…" : "Add channel"}</Button></>}>
    <form onSubmit={submit}><Field label="YouTube channel URL or handle"><div className="lookup-row"><input autoFocus value={query} onChange={e => setQuery(e.target.value)} placeholder="https://www.youtube.com/@yourchannel"/><Button type="submit" disabled={!query.trim() || lookup.isPending}>{lookup.isPending ? "Looking up…" : "Find channel"}</Button></div></Field></form>
    {error && <div className="form-error">{error}</div>}
    {card && <>
      <div className="channel-confirm">{card.thumbnail_url && <img src={card.thumbnail_url} alt="" referrerPolicy="no-referrer"/>}<div><strong>{card.display_name}</strong><span>{card.handle ?? card.youtube_channel_id}</span><span><a href={card.url} target="_blank" rel="noreferrer" style={{ color: "var(--primary)" }}>Open on YouTube</a></span></div></div>
      {card.already_added ? <div className="form-error">This channel is already being monitored.</div> : <>
        <Field label="Default TikTok account" hint="Where this channel's videos are posted. It can be changed per post in the review queue.">
          <select value={accountId} onChange={e => setAccountId(e.target.value)}><option value="">Least-busy connected account</option>{(accounts.data?.items ?? []).map(a => <option key={a.id} value={a.id}>@{a.username}</option>)}</select></Field>
      </>}
    </>}
  </Modal>;
}

const PUSH: Record<Channel["push_status"], { label: string; tone: Tone }> = {
  subscribed: { label: "Subscribed", tone: "success" },
  pending: { label: "Pending", tone: "warning" },
  expired: { label: "Expired", tone: "danger" },
  failed: { label: "Failed", tone: "danger" },
  unavailable: { label: "Polling only", tone: "neutral" },
  off: { label: "Off", tone: "neutral" },
};

function PushStatus({ channel }: { channel: Channel }) {
  const status = PUSH[channel.push_status];
  const detail = channel.push_status === "failed" ? channel.push_error
    : channel.push_status === "unavailable" ? "Needs a public HTTPS address (PUBLIC_BASE_URL)"
    : channel.push_expires_at ? `${channel.push_status === "expired" ? "Expired" : "Renews before"} ${dayTime(channel.push_expires_at)}`
    : channel.push_status === "pending" ? "Waiting for YouTube to confirm" : null;
  return <div title={detail ?? undefined}><Badge tone={status.tone}>{status.label}</Badge>{detail && <div className="cell-sub">{detail}</div>}</div>;
}

export default function Channels() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const [adding, setAdding] = useState(false);
  const list = useQuery({ queryKey: ["channels"], queryFn: channels.list, refetchInterval: 30_000 });
  const accounts = useQuery({ queryKey: ["tiktok"], queryFn: tiktok.list });
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

  return <><PageHeader title="Channels" description="The YouTube channels being watched. Every new short-form upload is republished to TikTok."><Button icon="plus" variant="primary" onClick={() => setAdding(true)}>Add channel</Button></PageHeader>
    {list.data && !list.data.push_available && <p className="note-row">YouTube can only push notifications to a public HTTPS address (PUBLIC_BASE_URL in .env). On this install it is not public, so new uploads are found by checking each channel every few minutes instead.</p>}
    <Card className="table-card"><div className="table-wrap"><table><thead><tr><th>Channel</th><th>Last upload</th><th>Published</th><th>Skipped</th><th>TikTok account</th><th>Push status</th><th>Last checked</th><th>Active</th><th/></tr></thead><tbody>
      {items.map(c => <tr key={c.id}>
        <td><div className="channel-cell"><ChannelAvatar channel={c}/><div><strong>{c.display_name}</strong><span>{c.handle ?? c.youtube_channel_id}{c.override_count ? ` · ${c.override_count} override${c.override_count === 1 ? "" : "s"}` : ""}</span></div></div></td>
        <td>{c.last_upload_at ? relativeTime(c.last_upload_at, { suffix: true }) : "—"}</td>
        <td>{c.videos_published}</td><td>{c.videos_skipped}</td>
        <td><select className="cell-select" value={c.default_tiktok_account?.id ?? ""} onChange={e => update.mutate({ id: c.id, body: { default_tiktok_account_id: e.target.value ? Number(e.target.value) : null } })}><option value="">Least-busy account</option>{(accounts.data?.items ?? []).map(a => <option key={a.id} value={a.id}>@{a.username}</option>)}</select></td>
        <td><PushStatus channel={c}/></td>
        <td>{c.last_error ? <span className="cell-error" title={c.last_error}>{c.last_error}</span> : c.last_checked_at ? relativeTime(c.last_checked_at, { suffix: true }) : "Not yet"}</td>
        <td><Toggle checked={c.active} disabled={update.isPending} label={`Monitor ${c.display_name}`} onChange={() => { if (!update.isPending) update.mutate({ id: c.id, body: { active: !c.active } }); }}/></td>
        <td><Menu items={[{ label: "Check now", icon: "refresh", disabled: !c.active, onSelect: () => check.mutate(c) }, { label: "Open on YouTube", icon: "link", onSelect: () => window.open(c.url, "_blank", "noopener") }, { label: "Remove", icon: "close", danger: true, onSelect: () => askRemove(c) }]} trigger={t => <Button variant="ghost" icon="more" onClick={t}/>}/></td>
      </tr>)}</tbody></table></div>
      {list.isLoading && <Spinner/>}
      {!list.isLoading && items.length === 0 && <Empty icon="play" title="No channels yet">Add a YouTube channel to start detecting new uploads.</Empty>}
    </Card>
    {adding && <AddChannelModal close={() => setAdding(false)}/>}
  </>;
}
