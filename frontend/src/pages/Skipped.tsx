import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { channels, jobs } from "@/api/endpoints";
import type { Video } from "@/api/types";
import { FilterSelect } from "@/components/Menu";
import { useErrorToast, useToast } from "@/components/Toast";
import { Badge, Button, Card, Empty, PageHeader, Spinner, VideoThumb } from "@/components/ui";
import { SKIP_REASON, duration, relativeTime } from "@/lib/format";

export default function Skipped() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const [channelId, setChannelId] = useState("");
  const [reason, setReason] = useState("");
  const list = useQuery({ queryKey: ["videos", "skipped", channelId], queryFn: () => jobs.videos("skipped", 500, channelId ? Number(channelId) : undefined), refetchInterval: 30_000 });
  const channelList = useQuery({ queryKey: ["channels"], queryFn: channels.list });
  const process = useMutation({
    mutationFn: (v: Video) => jobs.processAnyway(v.id),
    onSuccess: (_job, v) => { toast({ title: "Processing", message: `“${v.original_title.slice(0, 50)}” is being downloaded and edited.` }); queryClient.invalidateQueries({ queryKey: ["videos"] }); queryClient.invalidateQueries({ queryKey: ["jobs"] }); queryClient.invalidateQueries({ queryKey: ["nav"] }); },
    onError,
  });
  const items = (list.data ?? []).filter(v => !reason || v.skip_reason === reason);

  return <><PageHeader title="Skipped" description="Videos that were detected but held back. Nothing is discarded: any of them can still be processed by hand."><Badge tone="neutral">{items.length} held</Badge></PageHeader>
    <div className="toolbar">
      <FilterSelect value={channelId} onChange={setChannelId} options={[{ value: "", label: "All channels" }, ...(channelList.data?.items ?? []).map(c => ({ value: String(c.id), label: c.display_name }))]}/>
      <FilterSelect value={reason} onChange={setReason} options={[{ value: "", label: "All reasons" }, ...Object.entries(SKIP_REASON).map(([value, label]) => ({ value, label }))]}/></div>
    <Card className="table-card"><div className="table-wrap"><table><thead><tr><th/><th>Video</th><th>Channel</th><th>Duration</th><th>Reason</th><th>Detail</th><th>Detected</th><th/></tr></thead><tbody>
      {items.map(v => <tr key={v.id}>
        <td><VideoThumb index={v.id} image={v.thumbnail_url}/></td>
        <td className="truncate">{v.permalink ? <a href={v.permalink} target="_blank" rel="noreferrer" style={{ color: "inherit" }}>{v.original_title || v.youtube_video_id}</a> : v.original_title}</td>
        <td>{v.channel?.display_name ?? "—"}</td>
        <td>{duration(v.duration_sec)}</td>
        <td><Badge tone="warning">{SKIP_REASON[v.skip_reason ?? ""] ?? v.skip_reason ?? "Skipped"}</Badge></td>
        <td style={{ whiteSpace: "normal", minWidth: 200 }}>{v.rejection_reason}</td>
        <td>{relativeTime(v.created_at, { suffix: true })}</td>
        <td><Button disabled={process.isPending} onClick={() => process.mutate(v)}>Process anyway</Button></td>
      </tr>)}</tbody></table></div>
      {list.isLoading && <Spinner/>}
      {!list.isLoading && items.length === 0 && <Empty icon="check" title="Nothing skipped">Videos that are too long, too short, or over a daily cap are listed here with the reason.</Empty>}
    </Card>
  </>;
}
