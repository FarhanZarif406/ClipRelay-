import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { jobs, tiktok } from "@/api/endpoints";
import type { Job } from "@/api/types";
import { Icon } from "@/components/Icon";
import { JobDrawer } from "@/components/JobDrawer";
import { FilterSelect, Menu } from "@/components/Menu";
import { useErrorToast, useToast } from "@/components/Toast";
import { Badge, Button, Card, Empty, PageHeader, Spinner, VideoThumb } from "@/components/ui";
import { useDebounced } from "@/hooks/useDebounced";
import { JOB_STATUS, duration, relativeTime } from "@/lib/format";

const PAGE_SIZE = 25;

export default function JobsQueue() {
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const [status, setStatus] = useState(params.get("status") ?? "");
  const [accountId, setAccountId] = useState("");
  const [period, setPeriod] = useState("");
  const [page, setPage] = useState(1);
  const [openJob, setOpenJob] = useState<number | null>(params.get("job") ? Number(params.get("job")) : null);
  const q = useDebounced(search);
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();

  useEffect(() => { const next = params.get("q"); if (next !== null) setSearch(next); }, [params]);
  useEffect(() => setPage(1), [q, status, accountId, period]);

  const list = useQuery({
    queryKey: ["jobs", q, status, accountId, period, page],
    queryFn: () => jobs.list({ q, status: status || undefined, tiktok_account_id: accountId ? Number(accountId) : undefined, period: period || undefined, page, page_size: PAGE_SIZE }),
    refetchInterval: 20_000,
  });
  const accounts = useQuery({ queryKey: ["tiktok"], queryFn: tiktok.list });
  const processNext = useMutation({
    mutationFn: jobs.processNext,
    onSuccess: r => { toast({ title: r.action === "upload" ? "Uploading next video" : "Processing next video", message: `Job #CR-${String(r.job_id).padStart(5, "0")} is being processed.` }); queryClient.invalidateQueries({ queryKey: ["jobs"] }); },
    onError,
  });
  const action = useMutation({
    mutationFn: ({ job, kind }: { job: Job; kind: "retry" | "cancel" }) => (kind === "retry" ? jobs.retry(job.id) : jobs.cancel(job.id)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["jobs"] }),
    onError,
  });
  const open = (id: number | null) => { setOpenJob(id); const next = new URLSearchParams(params); if (id) next.set("job", String(id)); else next.delete("job"); setParams(next, { replace: true }); };
  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;

  const statusOptions = [{ value: "", label: "All statuses" }, { value: "pending", label: "Pending (all)" }, { value: "published", label: "Published (all)" }, ...Object.entries(JOB_STATUS).map(([value, s]) => ({ value, label: s.label }))];
  const rowMenu = (j: Job) => <Menu items={[{ label: "Details", icon: "chevron", onSelect: () => open(j.id) }, { label: "Retry", icon: "refresh", disabled: !["failed", "cancelled"].includes(j.status), onSelect: () => action.mutate({ job: j, kind: "retry" }) }, { label: "Cancel", icon: "close", danger: true, disabled: !["fetched", "downloading", "rendering", "rewriting", "awaiting_approval", "ready", "failed"].includes(j.status), onSelect: () => action.mutate({ job: j, kind: "cancel" }) }]} trigger={t => <Button variant="ghost" icon="more" onClick={t}/>}/>;

  return <><PageHeader title="Jobs Queue" description="Track every video from discovery to publication."><Button icon="play" variant="primary" onClick={() => processNext.mutate()} disabled={processNext.isPending}>Process next</Button></PageHeader>
    <div className="toolbar"><div className="search-field"><Icon name="search" size={16}/><input placeholder="Search jobs…" value={search} onChange={e => setSearch(e.target.value)}/></div>
      <FilterSelect value={status} onChange={setStatus} options={statusOptions}/>
      <FilterSelect value={accountId} onChange={setAccountId} options={[{ value: "", label: "All accounts" }, ...(accounts.data?.items ?? []).map(a => ({ value: String(a.id), label: `@${a.username}` }))]}/>
      <FilterSelect value={period} onChange={setPeriod} options={[{ value: "", label: "All time" }, { value: "today", label: "Today" }, { value: "7d", label: "Last 7 days" }, { value: "30d", label: "Last 30 days" }]}/></div>
    <Card className="table-card jobs-table"><div className="table-wrap"><table><thead><tr><th>Video</th><th>Original caption</th><th>Rewritten caption</th><th>Duration</th><th>Target</th><th>Status</th><th>Time</th><th/></tr></thead><tbody>{items.map(j => { const s = JOB_STATUS[j.status]; return <tr key={j.id} onClick={() => open(j.id)}><td><VideoThumb index={j.id} image={j.video.thumbnail_url} label={String(j.id).slice(-2).padStart(2, "0")}/></td><td className="truncate">{j.video.original_caption || j.video.original_title}</td><td className="truncate">{j.rewritten_caption || (j.status === "rewriting" ? "Rewriting…" : "—")}</td><td>{duration(j.video.duration_sec)}</td><td>{j.tiktok_account ? `@${j.tiktok_account.username}` : "—"}</td><td><Badge tone={s.tone}>{s.label}</Badge></td><td>{relativeTime(j.updated_at)}</td><td>{rowMenu(j)}</td></tr>; })}</tbody></table></div>
      {list.isLoading && <Spinner/>}
      {!list.isLoading && items.length === 0 && <Empty icon="queue" title="No jobs found">Jobs appear here as soon as new videos come in.</Empty>}
      {total > PAGE_SIZE && <div className="pagination"><span>{(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)} of {total}</span><div><Button disabled={page === 1} onClick={() => setPage(p => p - 1)}>Previous</Button><Button disabled={page * PAGE_SIZE >= total} onClick={() => setPage(p => p + 1)}>Next</Button></div></div>}
    </Card>
    <div className="mobile-cards job-mobile">{items.map(j => { const s = JOB_STATUS[j.status]; return <Card key={j.id}><div className="job-card-top"><VideoThumb index={j.id} image={j.video.thumbnail_url}/><div><strong>{j.rewritten_caption || j.video.original_caption}</strong><span>→ {j.tiktok_account ? `@${j.tiktok_account.username}` : "No account"}</span></div><Badge tone={s.tone}>{s.label}</Badge></div><div className="mobile-card-foot"><span>{duration(j.video.duration_sec)}</span><span>{relativeTime(j.updated_at, { suffix: true })}</span><Button onClick={() => open(j.id)}>Details</Button></div></Card>; })}</div>
    {openJob && <JobDrawer jobId={openJob} close={() => open(null)}/>}
  </>;
}
