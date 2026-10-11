import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { channels, jobs, tiktok } from "@/api/endpoints";
import type { Job, Tone } from "@/api/types";
import { Icon } from "@/components/Icon";
import { JobDrawer } from "@/components/JobDrawer";
import { FilterSelect } from "@/components/Menu";
import { useErrorToast, useToast } from "@/components/Toast";
import { Badge, Button, Card, Empty, PageHeader, Spinner, VideoThumb } from "@/components/ui";
import { useDebounced } from "@/hooks/useDebounced";
import { JOB_STATUS, dayTime } from "@/lib/format";

const PAGE_SIZE = 25;
const STATUS_OPTIONS = [
  { value: "outbox", label: "All statuses" },
  { value: "published", label: "Published" },
  { value: "failed", label: "Failed" },
  { value: "waiting", label: "Waiting for account" },
];

function statusOf(j: Job): { label: string; tone: Tone } {
  if (j.waiting_for_account) return { label: "Waiting for account", tone: "warning" };
  if (j.status === "ready") return { label: "Waiting to upload", tone: "primary" };
  return JOB_STATUS[j.status];
}

export default function Published() {
  const [params] = useSearchParams();
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const [status, setStatus] = useState(params.get("status") ?? "outbox");
  const [channelId, setChannelId] = useState("");
  const [accountId, setAccountId] = useState("");
  const [page, setPage] = useState(1);
  const [openJob, setOpenJob] = useState<number | null>(null);
  const q = useDebounced(search);
  useEffect(() => { const next = params.get("q"); if (next !== null) setSearch(next); }, [params]);
  useEffect(() => setPage(1), [q, status, channelId, accountId]);
  const list = useQuery({
    queryKey: ["jobs", "published", q, status, channelId, accountId, page],
    queryFn: () => jobs.list({ status, order: "posted", q, channel_id: channelId ? Number(channelId) : undefined, tiktok_account_id: accountId ? Number(accountId) : undefined, page, page_size: PAGE_SIZE }),
    refetchInterval: 20_000,
  });
  const channelList = useQuery({ queryKey: ["channels"], queryFn: channels.list });
  const accounts = useQuery({ queryKey: ["tiktok"], queryFn: tiktok.list });
  const retry = useMutation({
    mutationFn: (j: Job) => jobs.retry(j.id),
    onSuccess: () => { toast({ title: "Retrying", message: "The video is back in the pipeline." }); queryClient.invalidateQueries({ queryKey: ["jobs"] }); queryClient.invalidateQueries({ queryKey: ["nav"] }); },
    onError,
  });
  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;
  const noAccounts = accounts.data && accounts.data.items.length === 0;

  return <><PageHeader title="Published" description="Everything past the review step: published, waiting to go out, and failed."><Badge tone="neutral">{total} videos</Badge></PageHeader>
    {noAccounts && <p className="note-row">No TikTok account is connected yet. Approved and automatic videos wait here as “Waiting for account” and are sent as soon as one is connected in TikTok Accounts.</p>}
    <div className="toolbar"><div className="search-field"><Icon name="search" size={16}/><input placeholder="Search videos…" value={search} onChange={e => setSearch(e.target.value)}/></div>
      <FilterSelect value={status} onChange={setStatus} options={STATUS_OPTIONS}/>
      <FilterSelect value={channelId} onChange={setChannelId} options={[{ value: "", label: "All channels" }, ...(channelList.data?.items ?? []).map(c => ({ value: String(c.id), label: c.display_name }))]}/>
      <FilterSelect value={accountId} onChange={setAccountId} options={[{ value: "", label: "All accounts" }, ...(accounts.data?.items ?? []).map(a => ({ value: String(a.id), label: `@${a.username}` }))]}/></div>
    <Card className="table-card"><div className="table-wrap"><table><thead><tr><th/><th>Date</th><th>Channel</th><th>TikTok account</th><th>Caption</th><th>Status</th><th>Detail</th><th/></tr></thead><tbody>
      {items.map(j => { const s = statusOf(j); return <tr key={j.id} onClick={() => setOpenJob(j.id)}>
        <td><VideoThumb index={j.id} image={j.video.thumbnail_url}/></td>
        <td>{dayTime(j.posted_at ?? j.updated_at)}</td>
        <td>{j.video.channel?.display_name ?? "—"}</td>
        <td>{j.tiktok_account ? `@${j.tiktok_account.username}` : "—"}</td>
        <td className="truncate">{j.rewritten_caption || j.video.original_title}</td>
        <td><Badge tone={s.tone}>{s.label}</Badge></td>
        <td style={{ whiteSpace: "normal", minWidth: 180, maxWidth: 320 }} onClick={e => j.tiktok_url && e.stopPropagation()}>
          {j.status === "failed" ? <span className="cell-error" style={{ maxWidth: "none" }}>{j.error}</span>
            : j.tiktok_url ? <a href={j.tiktok_url} target="_blank" rel="noreferrer" style={{ color: "var(--primary)" }}>Open TikTok post</a>
            : j.status === "ready" ? j.error ?? "Next in line"
            : j.publish_mode === "inbox" ? "In the TikTok inbox — finish the post in the app" : "Processing on TikTok"}</td>
        <td onClick={e => e.stopPropagation()}>{j.status === "failed" && <Button icon="refresh" disabled={retry.isPending} onClick={() => retry.mutate(j)}>Retry</Button>}</td>
      </tr>; })}</tbody></table></div>
      {list.isLoading && <Spinner/>}
      {!list.isLoading && items.length === 0 && <Empty icon="arrow" title="Nothing here yet">Videos appear here once they are approved, or straight away when approval is switched off.</Empty>}
      {total > PAGE_SIZE && <div className="pagination"><span>{(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)} of {total}</span><div><Button disabled={page === 1} onClick={() => setPage(p => p - 1)}>Previous</Button><Button disabled={page * PAGE_SIZE >= total} onClick={() => setPage(p => p + 1)}>Next</Button></div></div>}
    </Card>
    {openJob && <JobDrawer jobId={openJob} close={() => setOpenJob(null)}/>}
  </>;
}
