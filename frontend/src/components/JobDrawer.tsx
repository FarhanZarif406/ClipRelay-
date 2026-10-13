import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { jobs } from "@/api/endpoints";
import type { Job } from "@/api/types";
import { JOB_STATUS, dayTime, duration } from "@/lib/format";
import { Icon } from "./Icon";
import { useErrorToast, useToast } from "./Toast";
import { Badge, Button } from "./ui";

const EDITABLE = new Set(["fetched", "awaiting_approval", "ready", "failed"]);
const CANCELLABLE = new Set(["fetched", "rewriting", "awaiting_approval", "ready", "failed"]);

export function JobDrawer({ jobId, close }: { jobId: number; close: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const { data: job } = useQuery({ queryKey: ["job", jobId], queryFn: () => jobs.get(jobId), refetchInterval: 15_000 });
  const [edit, setEdit] = useState({ title: "", caption: "", tags: "" });
  useEffect(() => {
    if (job) setEdit({ title: job.rewritten_title ?? "", caption: job.rewritten_caption ?? "", tags: job.rewritten_tags.map(t => `#${t}`).join(" ") });
  }, [job?.id, job?.updated_at]);  // eslint-disable-line react-hooks/exhaustive-deps

  const done = (title: string) => (j: Job) => { queryClient.setQueryData(["job", jobId], j); queryClient.invalidateQueries({ queryKey: ["jobs"] }); queryClient.invalidateQueries({ queryKey: ["nav"] }); toast({ title }); };
  const saveEdits = () => jobs.update(jobId, {
    rewritten_title: edit.title, rewritten_caption: edit.caption, rewritten_tags: edit.tags.split(/[\s,]+/).filter(Boolean),
  });
  const save = useMutation({ mutationFn: saveEdits, onSuccess: done("Changes saved"), onError });
  const approve = useMutation({ mutationFn: async () => { await saveEdits(); return jobs.approve(jobId); }, onSuccess: done("Approved — uploading shortly"), onError });
  const retry = useMutation({ mutationFn: () => jobs.retry(jobId), onSuccess: done("Retry queued"), onError });
  const cancel = useMutation({ mutationFn: () => jobs.cancel(jobId), onSuccess: done("Job cancelled"), onError });

  const status = job ? JOB_STATUS[job.status] : null;
  const editable = job && EDITABLE.has(job.status);
  return <div className="drawer-overlay" onMouseDown={close}><aside className="drawer" onMouseDown={e => e.stopPropagation()}>
    <div className="drawer-head"><div>{status && <Badge tone={status.tone}>{status.label}</Badge>}<div className="card-title">Job #CR-{String(jobId).padStart(5, "0")}</div></div><Button variant="ghost" icon="close" onClick={close}/></div>
    {job && <>
      <div className="video-preview" style={job.video.thumbnail_url ? { backgroundImage: `url(${job.video.thumbnail_url})`, backgroundSize: "cover", backgroundPosition: "center" } : undefined}>{job.video.permalink ? <a className="play-big" href={job.video.permalink} target="_blank" rel="noreferrer" aria-label="Open original video"><Icon name="play" size={24}/></a> : <div className="play-big"><Icon name="play" size={24}/></div>}<span>{duration(job.video.duration_sec)}</span></div>
      {job.error && <div className="error-note">{job.error}</div>}
      <div className="drawer-section"><div className="section-label">CONTENT TRANSFORMATION</div>
        <div className="before-after"><div><span>ORIGINAL</span><p>{job.video.original_caption || job.video.original_title || "—"}</p></div><Icon name="arrow"/><div><span>REWRITTEN</span>
          {editable ? <><input className="edit" value={edit.title} onChange={e => setEdit({ ...edit, title: e.target.value })} placeholder="Title" aria-label="Title"/><textarea className="edit" rows={4} value={edit.caption} onChange={e => setEdit({ ...edit, caption: e.target.value })} placeholder="Caption" aria-label="Caption"/><input className="edit" value={edit.tags} onChange={e => setEdit({ ...edit, tags: e.target.value })} placeholder="#hashtags" aria-label="Hashtags"/></>
            : <p>{job.rewritten_caption || job.rewritten_title || "Not rewritten yet"}{job.rewritten_tags.length > 0 && <><br/><span style={{ color: "#a99fff", fontWeight: 400 }}>{job.rewritten_tags.map(t => `#${t}`).join(" ")}</span></>}</p>}
        </div></div>
      </div>
      <div className="drawer-section"><div className="section-label">PUBLISHING</div>
        <div className="drawer-meta">
          <div><span>Account</span><strong>{job.buffer_channel?.name ?? "Next free time (auto)"}</strong></div>
          {job.buffer_due_at && <div><span>{job.posted_at ? "Went out" : "Goes out"}</span><strong>{dayTime(job.posted_at ?? job.buffer_due_at)}</strong></div>}
          {job.post_url && <div><span>Post</span><strong><a href={job.post_url} target="_blank" rel="noreferrer" style={{ color: "var(--primary)" }}>Open</a></strong></div>}
</div>
      </div>
      <div className="drawer-section"><div className="section-label">PROCESS TIMELINE</div><div className="timeline">{job.events?.map(ev => <div className={`timeline-item ${ev.status}`} key={ev.id}><i><Icon name={ev.status === "failed" || ev.status === "cancelled" ? "close" : "check"} size={11}/></i><div><strong>{ev.message}</strong><span>{dayTime(ev.created_at)}</span></div></div>)}</div></div>
      <div className="drawer-actions">
        {CANCELLABLE.has(job.status) && <Button onClick={() => cancel.mutate()} disabled={cancel.isPending}>Cancel job</Button>}
        {editable && job.status !== "awaiting_approval" && <Button onClick={() => save.mutate()} disabled={save.isPending}>Save changes</Button>}
        {job.status === "awaiting_approval" && <Button variant="primary" icon="check" onClick={() => approve.mutate()} disabled={approve.isPending}>Approve &amp; post</Button>}
        {(job.status === "failed" || job.status === "cancelled") && <Button variant="primary" icon="refresh" onClick={() => retry.mutate()} disabled={retry.isPending}>Retry job</Button>}
      </div>
    </>}
  </aside></div>;
}
