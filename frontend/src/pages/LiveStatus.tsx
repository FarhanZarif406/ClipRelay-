import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { dashboard, jobs } from "@/api/endpoints";
import type { StatusItem } from "@/api/types";
import { Icon, type IconName } from "@/components/Icon";
import { useErrorToast, useToast } from "@/components/Toast";
import { Badge, Button, Card, PageHeader, Spinner, VideoThumb } from "@/components/ui";
import { duration, relativeTime, timecode } from "@/lib/format";
import { PODCASTS } from "@/lib/mode";

/** What each stage looks like, and where to go to act on it. */
const STAGE: Record<string, { icon: IconName; empty: string; bar: boolean; link?: [string, string]; stop?: [string, string] }> = {
  waiting: { icon: "clock", empty: "Nothing is waiting to be downloaded.", bar: false, stop: ["Cancel", "Cancel this video before it is downloaded?"] },
  downloading: { icon: "download", empty: "Nothing is downloading right now.", bar: true, stop: ["Stop download", "Stop this download and cancel the video?"] },
  editing: { icon: "code", empty: "Nothing is being edited right now.", bar: true, stop: ["Stop editing", "Stop the editing and cancel the video?"] },
  caption: { icon: "sparkles", empty: "No video is waiting for its caption.", bar: false, stop: ["Cancel", "Cancel this video?"] },
  review: { icon: "check", empty: "Nothing is waiting for approval.", bar: false, link: ["Open review queue", "/review"] },
  upload_wait: { icon: "arrow", empty: "Nothing is waiting to be uploaded.", bar: false, link: ["Open published", "/published?status=waiting"], stop: ["Cancel upload", "Cancel this video so it is not uploaded?"] },
  uploading: { icon: "tiktok", empty: "Nothing is uploading right now.", bar: false },
};

function Tile({ label, done, left, of, tone }: { label: string; done: number; left: number; of: number; tone: string }) {
  const percent = of ? Math.round((done / of) * 100) : 0;
  return <Card className="status-tile"><span>{label}</span><strong>{done}<small> / {of}</small></strong>
    <div className="status-bar"><i className={tone} style={{ width: `${percent}%` }}/></div>
    <small>{of === 0 ? "No videos yet today" : done >= of ? "All done" : left > 0 ? `${left} still to go` : "Waiting for the step before"}</small></Card>;
}

function Row({ item, bar, showNote, stop, onStop, stopping }: { item: StatusItem; bar: boolean; showNote: boolean; stop?: [string, string]; onStop: (item: StatusItem, question: string) => void; stopping: boolean }) {
  const percent = item.progress ?? 0;
  const retrying = item.retry_at && new Date(item.retry_at).getTime() > Date.now();
  return <div className="status-row">
    <VideoThumb index={item.id} image={item.thumbnail_url}/>
    <div className="status-row-main">
      <strong>{item.title}</strong>
      <span>{item.podcast ? "Podcast · reading the transcript and choosing clips" : item.clip ? `Clip ${timecode(item.clip.start)}–${timecode(item.clip.end)} of “${item.clip.podcast_title}”` : item.channel ?? "—"}{!item.clip && !item.podcast && item.duration_sec ? ` · ${duration(item.duration_sec)}` : ""}</span>
      {bar && !item.podcast && <div className="status-bar"><i className="primary" style={{ width: `${Math.max(2, percent)}%` }}/></div>}
      {item.note && (showNote || item.attempts > 0) && <span className={item.attempts ? "status-note warn" : "status-note"}>{item.attempts ? `Attempt ${item.attempts} failed${retrying ? `, retrying ${relativeTime(item.retry_at, { suffix: true })}` : ""}: ` : ""}{item.note}</span>}
    </div>
    <div className="status-row-side">
      {bar && !item.podcast && <strong>{percent}%</strong>}
      <span>{relativeTime(item.since, { suffix: true })}</span>
    </div>
    {stop && <Button variant="danger" icon="close" disabled={stopping} title="It can be started again from Published → Cancelled" onClick={() => onStop(item, stop[1])}>{stopping ? "Stopping…" : stop[0]}</Button>}
  </div>;
}

export default function LiveStatus() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const { data, isLoading } = useQuery({ queryKey: ["pipeline-status"], queryFn: dashboard.status, refetchInterval: 3000 });
  // Stop = cancel the job. A download or an edit that is already running halts within a few seconds.
  const stop = useMutation({
    mutationFn: (item: StatusItem) => jobs.cancel(item.id),
    onSuccess: (_job, item) => { toast({ title: "Stopped", message: `“${item.title.slice(0, 50)}” was cancelled. You can start it again from Published → Cancelled.` }); queryClient.invalidateQueries({ queryKey: ["pipeline-status"] }); queryClient.invalidateQueries({ queryKey: ["jobs"] }); queryClient.invalidateQueries({ queryKey: ["nav"] }); },
    onError,
  });
  const askStop = (item: StatusItem, question: string) => { if (window.confirm(`${question}

“${item.title}”`)) stop.mutate(item); };
  const today = data?.today;
  const active = (data?.stages ?? []).reduce((sum, stage) => sum + stage.total, 0);
  const noun = PODCASTS ? "clips" : "videos";

  return <><PageHeader title="Live Status" description={`Where every ${PODCASTS ? "clip" : "video"} is right now: waiting, downloading, being edited, or waiting to upload. Updates every few seconds.`}><Badge tone={active ? "primary" : "success"}>{active ? `${active} in progress` : "Nothing in progress"}</Badge></PageHeader>
    {isLoading && <Spinner/>}
    {today && <>
      <div className="section-label" style={{ margin: "0 0 8px" }}>Today’s {noun}{data?.timezone ? ` · ${data.timezone}` : ""}</div>
      <div className="status-tiles">
        <Tile label="Downloaded" done={today.downloaded} left={today.download_left} of={today.total} tone="primary"/>
        <Tile label="Edited" done={today.edited} left={today.edit_left} of={today.total} tone="primary"/>
        <Tile label="Uploaded to TikTok" done={today.uploaded} left={today.upload_left} of={today.total} tone="success"/>
        <Card className="status-tile"><span>Failed</span><strong className={today.failed ? "bad" : ""}>{today.failed}</strong><div className="status-bar"/><small>{today.failed ? <button type="button" className="link-button" onClick={() => navigate("/published?status=failed")}>See why and retry</button> : "Nothing failed today"}</small></Card>
      </div>
      {PODCASTS && !!data?.podcasts_analysing && <p className="note-row">{data.podcasts_analysing} podcast{data.podcasts_analysing === 1 ? " is" : "s are"} being analysed. Its clips appear below once the moments are chosen.</p>}
    </>}
    <div className="status-stages">{(data?.stages ?? []).map(stage => { const look = STAGE[stage.key]; return <Card className="status-stage" key={stage.key}>
      <div className="status-stage-head"><div className="status-stage-icon"><Icon name={look.icon} size={15}/></div><div className="card-title">{stage.label}</div><Badge tone={stage.total ? "primary" : "neutral"} dot={false}>{stage.total}</Badge>
        {look.link && stage.total > 0 && <Button variant="ghost" onClick={() => navigate(look.link![1])}>{look.link[0]} <Icon name="arrow" size={13}/></Button>}</div>
      {stage.items.length === 0 ? <div className="status-empty">{look.empty}</div> : stage.items.map(item => <Row key={item.id} item={item} bar={look.bar} showNote={stage.key === "upload_wait"} stop={look.stop} onStop={askStop} stopping={stop.isPending && stop.variables?.id === item.id}/>)}
      {stage.total > stage.items.length && <div className="status-empty">and {stage.total - stage.items.length} more</div>}
    </Card>; })}</div>
  </>;
}
