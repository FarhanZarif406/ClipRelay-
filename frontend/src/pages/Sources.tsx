import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { sources, tiktok } from "@/api/endpoints";
import type { Source } from "@/api/types";
import { AddSourcesModal } from "@/components/AddSourcesModal";
import { Icon } from "@/components/Icon";
import { Menu } from "@/components/Menu";
import { CustomIntervalModal, INTERVAL_PRESETS, SourceEditModal } from "@/components/SourceEditModal";
import { useErrorToast, useToast } from "@/components/Toast";
import { Avatar, Button, Card, Empty, PageHeader, Spinner, Toggle } from "@/components/ui";
import { useDebounced } from "@/hooks/useDebounced";
import { intervalLabel, longAgo } from "@/lib/format";

const PAGE_SIZE = 50;

function LinkedPill({ source }: { source: Source }) {
  const [first, ...rest] = source.tiktok_accounts;
  if (!first) return <span className="muted">Not linked</span>;
  return <div className="account-pill"><Avatar label="T" color="dark"/>@{first.username}{rest.length > 0 && `, +${rest.length}`}</div>;
}

export default function Sources() {
  const [params, setParams] = useSearchParams();
  const [selected, setSelected] = useState<number[]>([]);
  const [modal, setModal] = useState<{ kind: "add" } | { kind: "edit" | "interval"; source: Source } | null>(null);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<"" | "active" | "paused" | "error">("");
  const [page, setPage] = useState(1);
  const q = useDebounced(search);
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();

  const list = useQuery({ queryKey: ["sources", q, status, page], queryFn: () => sources.list({ q, status: status || undefined, page, page_size: PAGE_SIZE }) });
  const accounts = useQuery({ queryKey: ["tiktok"], queryFn: tiktok.list });
  const items = list.data?.items ?? [];
  const total = list.data?.connected ?? 0;
  const capacity = list.data?.capacity ?? 7000;

  useEffect(() => {
    const connected = params.get("connected");
    const error = params.get("error");
    if (connected) toast({ title: "Instagram connected", message: `@${connected} is now available as a source.` });
    if (error) toast({ title: "Instagram connection failed", message: error, tone: "danger" });
    if (connected || error) setParams({}, { replace: true });
  }, [params, setParams, toast]);
  useEffect(() => setSelected([]), [q, status, page]);

  const refresh = () => { queryClient.invalidateQueries({ queryKey: ["sources"] }); queryClient.invalidateQueries({ queryKey: ["nav"] }); queryClient.invalidateQueries({ queryKey: ["dashboard"] }); };
  const update = useMutation({ mutationFn: ({ id, body }: { id: number; body: Parameters<typeof sources.update>[1] }) => sources.update(id, body), onSuccess: refresh, onError });
  const bulk = useMutation({
    mutationFn: ({ action, ids }: { action: "pause" | "resume" | "delete" | "assign"; ids?: number[] }) => sources.bulkUpdate(selected, action, ids),
    onSuccess: (r, v) => { toast({ title: "Sources updated", message: `${r.updated} source${r.updated === 1 ? "" : "s"} ${v.action === "delete" ? "deleted" : v.action === "assign" ? "assigned" : v.action + "d"}.` }); setSelected([]); refresh(); },
    onError,
  });
  const run = useMutation({ mutationFn: (s: Source) => sources.run(s.id), onSuccess: (_, s) => { toast({ title: "Run started", message: `Checking @${s.username} for new videos.` }); refresh(); }, onError });
  const remove = useMutation({ mutationFn: (s: Source) => sources.remove(s.id), onSuccess: refresh, onError });

  const toggleSel = (id: number) => setSelected(x => x.includes(id) ? x.filter(n => n !== id) : [...x, id]);
  const allSelected = items.length > 0 && items.every(s => selected.includes(s.id));
  const confirmDelete = (fn: () => void, what: string) => { if (window.confirm(`Delete ${what}? Fetched videos and jobs from it are removed too.`)) fn(); };

  const intervalMenu = (s: Source) => <Menu align="left" items={[...INTERVAL_PRESETS.map(m => ({ label: intervalLabel(m), active: s.refresh_interval_minutes === m, onSelect: () => update.mutate({ id: s.id, body: { refresh_interval_minutes: m } }) })), { label: INTERVAL_PRESETS.includes(s.refresh_interval_minutes) ? "Custom…" : `Custom (${intervalLabel(s.refresh_interval_minutes)})…`, active: !INTERVAL_PRESETS.includes(s.refresh_interval_minutes), onSelect: () => setModal({ kind: "interval", source: s }) }]}
    trigger={toggle => <button type="button" className="interval-select" onClick={toggle}>{intervalLabel(s.refresh_interval_minutes)}<Icon name="chevron" size={12}/></button>}/>;
  const rowMenu = (s: Source) => <Menu items={[
    { label: "Run now", icon: "play", onSelect: () => run.mutate(s) },
    { label: "Edit settings", icon: "settings", onSelect: () => setModal({ kind: "edit", source: s }) },
    { label: s.is_active ? "Pause" : "Resume", icon: s.is_active ? "clock" : "refresh", onSelect: () => update.mutate({ id: s.id, body: { is_active: !s.is_active } }) },
    { label: "Delete", icon: "close", danger: true, onSelect: () => confirmDelete(() => remove.mutate(s), `@${s.username}`) },
  ]} trigger={toggle => <Button variant="ghost" icon="more" onClick={toggle}/>}/>;

  return <><PageHeader title="Instagram Sources" description="Monitor up to 7,000 Instagram accounts by username or profile link."><div className="source-capacity-label"><strong>{total.toLocaleString()}</strong><span>/ {capacity.toLocaleString()} connected</span></div><Button icon="plus" variant="primary" onClick={() => setModal({ kind: "add" })}>Add accounts</Button></PageHeader>
    <Card className="source-capacity-card"><div className="source-capacity-icon"><Icon name="instagram" size={19}/></div><div><div className="card-title">Instagram source capacity</div><div className="card-caption">Username is the primary connection method. Use a profile link when an account has no available username.</div></div><div className="source-capacity-meter"><i style={{ width: `${(total / capacity) * 100}%` }}/></div><strong>{(capacity - total).toLocaleString()} slots available</strong><Button icon="plus" onClick={() => setModal({ kind: "add" })}>Bulk add up to 30</Button></Card>
    <div className="toolbar"><div className="search-field"><Icon name="search" size={16}/><input placeholder="Search sources…" value={search} onChange={e => { setSearch(e.target.value); setPage(1); }}/></div>
      <Menu align="left" items={[["", "All sources"], ["active", "Active"], ["paused", "Paused"], ["error", "With errors"]].map(([v, l]) => ({ label: l, active: status === v, onSelect: () => { setStatus(v as typeof status); setPage(1); } }))} trigger={toggle => <Button icon="filter" onClick={toggle}>{status ? `Filter: ${status}` : "Filters"}</Button>}/>
      <div className="spacer"/><span className="muted">{selected.length} selected</span>{selected.length > 0 && <><Button onClick={() => bulk.mutate({ action: "pause" })}>Pause</Button><Button onClick={() => bulk.mutate({ action: "resume" })}>Resume</Button>
        <Menu items={(accounts.data?.items ?? []).map(a => ({ label: `@${a.username}`, onSelect: () => bulk.mutate({ action: "assign", ids: [a.id] }) }))} trigger={toggle => <Button onClick={toggle} disabled={!accounts.data?.items.length}>Assign account</Button>}/>
        <Button variant="danger" onClick={() => confirmDelete(() => bulk.mutate({ action: "delete" }), `${selected.length} sources`)}>Delete</Button></>}</div>
    <Card className="table-card"><div className="table-wrap"><table><thead><tr><th><input type="checkbox" checked={allSelected} onChange={() => setSelected(allSelected ? [] : items.map(s => s.id))} aria-label="Select all"/></th><th>Instagram page</th><th>Last checked</th><th>Videos found</th><th>Status</th><th>Check interval</th><th>Linked TikTok</th><th/></tr></thead><tbody>
      {items.map(s => <tr key={s.id}><td><input type="checkbox" checked={selected.includes(s.id)} onChange={() => toggleSel(s.id)}/></td><td><div className="identity"><Avatar label={s.initials} color={s.color}/><div><strong>@{s.username}</strong><span>{s.approval_mode === "manual" ? "Manual approval" : "Instagram page"}</span>{s.last_error && <span className="row-error" title={s.last_error}>{s.last_error}</span>}</div></div></td><td>{longAgo(s.last_checked_at)}</td><td><strong>{s.videos_found}</strong></td><td><div className="toggle-label"><Toggle checked={s.is_active} onChange={() => update.mutate({ id: s.id, body: { is_active: !s.is_active } })}/>{s.is_active ? "Active" : "Paused"}</div></td><td>{intervalMenu(s)}</td><td><LinkedPill source={s}/></td><td>{rowMenu(s)}</td></tr>)}
    </tbody></table></div>
      {list.isLoading && <Spinner/>}
      {!list.isLoading && items.length === 0 && <Empty icon="instagram" title={q || status ? "No sources match" : "No Instagram sources yet"}>{!q && !status && <>Authorize an Instagram Business or Creator account to start monitoring it.<br/><br/><Button variant="primary" icon="plus" onClick={() => setModal({ kind: "add" })}>Add accounts</Button></>}</Empty>}
      {(list.data?.total ?? 0) > PAGE_SIZE && <div className="pagination"><span>Page {page} of {Math.ceil((list.data?.total ?? 0) / PAGE_SIZE)}</span><div><Button disabled={page === 1} onClick={() => setPage(p => p - 1)}>Previous</Button><Button disabled={page * PAGE_SIZE >= (list.data?.total ?? 0)} onClick={() => setPage(p => p + 1)}>Next</Button></div></div>}
    </Card>
    <div className="mobile-cards">{items.map(s => <Card key={s.id}><div className="mobile-source"><input type="checkbox" checked={selected.includes(s.id)} onChange={() => toggleSel(s.id)}/><Avatar label={s.initials} color={s.color}/><div><strong>@{s.username}</strong><span>{longAgo(s.last_checked_at)} · {s.videos_found} videos</span></div><Toggle checked={s.is_active} onChange={() => update.mutate({ id: s.id, body: { is_active: !s.is_active } })}/></div><div className="mobile-card-foot">{intervalMenu(s)}<LinkedPill source={s}/>{rowMenu(s)}</div></Card>)}</div>
    {modal?.kind === "add" && <AddSourcesModal close={() => setModal(null)} availableSlots={capacity - total}/>}
    {modal?.kind === "edit" && <SourceEditModal source={modal.source} close={() => setModal(null)}/>}
    {modal?.kind === "interval" && <CustomIntervalModal source={modal.source} close={() => setModal(null)}/>}
  </>;
}
