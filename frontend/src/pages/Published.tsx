import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { channels, jobs, tiktok } from "@/api/endpoints";
import { Icon } from "@/components/Icon";
import { JobDrawer } from "@/components/JobDrawer";
import { FilterSelect } from "@/components/Menu";
import { Badge, Button, Card, Empty, PageHeader, Spinner, VideoThumb } from "@/components/ui";
import { useDebounced } from "@/hooks/useDebounced";
import { JOB_STATUS, dayTime } from "@/lib/format";

const PAGE_SIZE = 25;

export default function Published() {
  const [search, setSearch] = useState("");
  const [channelId, setChannelId] = useState("");
  const [accountId, setAccountId] = useState("");
  const [page, setPage] = useState(1);
  const [openJob, setOpenJob] = useState<number | null>(null);
  const q = useDebounced(search);
  useEffect(() => setPage(1), [q, channelId, accountId]);
  const list = useQuery({
    queryKey: ["jobs", "published", q, channelId, accountId, page],
    queryFn: () => jobs.list({ status: "published", order: "posted", q, channel_id: channelId ? Number(channelId) : undefined, tiktok_account_id: accountId ? Number(accountId) : undefined, page, page_size: PAGE_SIZE }),
    refetchInterval: 30_000,
  });
  const channelList = useQuery({ queryKey: ["channels"], queryFn: channels.list });
  const accounts = useQuery({ queryKey: ["tiktok"], queryFn: tiktok.list });
  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;

  return <><PageHeader title="Published" description="Everything that went out to TikTok, newest first."><Badge tone="success">{total} total</Badge></PageHeader>
    <div className="toolbar"><div className="search-field"><Icon name="search" size={16}/><input placeholder="Search captions…" value={search} onChange={e => setSearch(e.target.value)}/></div>
      <FilterSelect value={channelId} onChange={setChannelId} options={[{ value: "", label: "All channels" }, ...(channelList.data?.items ?? []).map(c => ({ value: String(c.id), label: c.display_name }))]}/>
      <FilterSelect value={accountId} onChange={setAccountId} options={[{ value: "", label: "All accounts" }, ...(accounts.data?.items ?? []).map(a => ({ value: String(a.id), label: `@${a.username}` }))]}/></div>
    <Card className="table-card"><div className="table-wrap"><table><thead><tr><th/><th>Date</th><th>Channel</th><th>TikTok account</th><th>Caption</th><th>Mode</th><th>Status</th><th>TikTok post</th></tr></thead><tbody>
      {items.map(j => { const s = JOB_STATUS[j.status]; return <tr key={j.id} onClick={() => setOpenJob(j.id)}>
        <td><VideoThumb index={j.id} image={j.video.thumbnail_url}/></td>
        <td>{j.posted_at ? dayTime(j.posted_at) : "—"}</td>
        <td>{j.video.channel?.display_name ?? "—"}</td>
        <td>{j.tiktok_account ? `@${j.tiktok_account.username}` : "—"}</td>
        <td className="truncate">{j.rewritten_caption || j.video.original_title}</td>
        <td>{j.publish_mode === "inbox" ? "Inbox" : j.publish_mode === "direct" ? "Direct" : "—"}</td>
        <td><Badge tone={s.tone}>{s.label}</Badge></td>
        <td onClick={e => e.stopPropagation()}>{j.tiktok_url ? <a href={j.tiktok_url} target="_blank" rel="noreferrer" style={{ color: "var(--primary)" }}>Open post</a> : j.publish_mode === "inbox" ? "Finish in the TikTok app" : "Processing"}</td>
      </tr>; })}</tbody></table></div>
      {list.isLoading && <Spinner/>}
      {!list.isLoading && items.length === 0 && <Empty icon="arrow" title="Nothing published yet">Videos appear here after they are sent to TikTok.</Empty>}
      {total > PAGE_SIZE && <div className="pagination"><span>{(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)} of {total}</span><div><Button disabled={page === 1} onClick={() => setPage(p => p - 1)}>Previous</Button><Button disabled={page * PAGE_SIZE >= total} onClick={() => setPage(p => p + 1)}>Next</Button></div></div>}
    </Card>
    {openJob && <JobDrawer jobId={openJob} close={() => setOpenJob(null)}/>}
  </>;
}
