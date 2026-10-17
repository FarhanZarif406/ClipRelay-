import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { channels, jobs } from "@/api/endpoints";
import type { Video } from "@/api/types";
import { limitSource, untilReset, upgradeLine, useDailyLimit } from "@/components/LimitBanner";
import { useMyPlan } from "@/hooks/useMyPlan";
import { FilterSelect } from "@/components/Menu";
import { useErrorToast, useToast } from "@/components/Toast";
import { Badge, Button, Card, Empty, PageHeader, Spinner, VideoThumb } from "@/components/ui";
import { LIMIT_REASONS, SKIP_REASON, duration, relativeTime } from "@/lib/format";
import { PODCASTS } from "@/lib/mode";

/**
 * Uploads that were fine to use but came over a daily limit: detected and recorded, never downloaded or edited.
 * Any of them can be processed now, by hand.
 */
export default function NotProcessed() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const [channelId, setChannelId] = useState("");
  const [reason, setReason] = useState("");
  const { data: limit } = useDailyLimit();
  const { plan } = useMyPlan();
  const list = useQuery({ queryKey: ["videos", "not-processed", channelId], queryFn: () => jobs.videos("skipped", 500, channelId ? Number(channelId) : undefined, "limit"), refetchInterval: 30_000 });
  const channelList = useQuery({ queryKey: ["channels"], queryFn: channels.list });
  const process = useMutation({
    mutationFn: (v: Video) => jobs.processAnyway(v.id),
    onSuccess: (_job, v) => {
      toast({ title: "Processing", message: `“${v.original_title.slice(0, 50)}” is being downloaded and edited.` });
      for (const key of ["videos", "jobs", "nav", "daily-limit"]) queryClient.invalidateQueries({ queryKey: [key] });
    },
    onError,
  });
  const items = (list.data ?? []).filter(v => !reason || v.skip_reason === reason);
  const noun = PODCASTS ? "podcasts" : "videos";

  return <><PageHeader title="Not Processed" description={`Usable ${noun} that were detected but not ${PODCASTS ? "cut into clips" : "edited"}, because a daily limit was used up. Press Process now to send one on anyway.${plan && !plan.owner && plan.limits.skipped_keep_hours ? ` They are cleared after ${plan.limits.skipped_keep_hours} hours.` : ""}`}><Badge tone={items.length ? "warning" : "success"}>{items.length} waiting</Badge></PageHeader>
    {limit && <Card className="limit-meter">
      <div><small>Today’s daily limit</small><b>{limit.used} <span>of {limit.limit}</span></b></div>
      <div className="limit-meter-bar" aria-hidden><i style={{ width: `${Math.min(100, (limit.used / Math.max(1, limit.limit)) * 100)}%` }} className={limit.reached ? "full" : ""}/></div>
      {limit.reached && upgradeLine(plan?.plan, !!plan?.owner) && <div className="limit-upgrade-box"><b>{upgradeLine(plan?.plan, !!plan?.owner)}</b><span>Ask the manager to upgrade your plan.</span></div>}
      <p>{limit.reached ? `Used up: new ${noun} wait here.` : `${limit.remaining} more ${noun} can be taken today.`} The limit is {limitSource(limit)}. It starts again in {untilReset(limit)} (midnight, {limit.time_zone.replace(/_/g, " ")}). Change it under {PODCASTS ? "Clip Rules" : "Settings → Pipeline rules"} → Daily limit.</p>
    </Card>}
    <div className="toolbar">
      <FilterSelect value={channelId} onChange={setChannelId} options={[{ value: "", label: "All channels" }, ...(channelList.data?.items ?? []).map(c => ({ value: String(c.id), label: c.display_name }))]}/>
      <FilterSelect value={reason} onChange={setReason} options={[{ value: "", label: "All limits" }, ...LIMIT_REASONS.filter(value => value !== "skipped_account_cap").map(value => ({ value, label: SKIP_REASON[value] }))]}/></div>
    <Card className="table-card"><div className="table-wrap"><table><thead><tr><th/><th>Video</th><th>Channel</th><th>Duration</th><th>Limit</th><th>Detail</th><th>Detected</th><th/></tr></thead><tbody>
      {items.map(v => <tr key={v.id}>
        <td><VideoThumb index={v.id} image={v.thumbnail_url}/></td>
        <td className="truncate">{v.permalink ? <a href={v.permalink} target="_blank" rel="noreferrer" style={{ color: "inherit" }}>{v.original_title || v.youtube_video_id}</a> : v.original_title}</td>
        <td>{v.channel?.display_name ?? "—"}</td>
        <td>{duration(v.duration_sec)}</td>
        <td><Badge tone="warning">{SKIP_REASON[v.skip_reason ?? ""] ?? v.skip_reason ?? "Limit"}</Badge></td>
        <td style={{ whiteSpace: "normal", minWidth: 200 }}>{v.rejection_reason}</td>
        <td>{relativeTime(v.created_at, { suffix: true })}</td>
        <td><Button variant="primary" disabled={process.isPending} onClick={() => process.mutate(v)}>Process now</Button></td>
      </tr>)}</tbody></table></div>
      {list.isLoading && <Spinner/>}
      {!list.isLoading && items.length === 0 && <Empty icon="check" title="Nothing waiting">{`Once today’s daily limit (or a channel’s own daily limit) is used up, new usable ${noun} are listed here instead of being ${PODCASTS ? "cut" : "edited"}.`}</Empty>}
    </Card>
  </>;
}
