import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { auth, jobs, tiktok } from "@/api/endpoints";
import { apiUrl } from "@/api/client";
import type { Job } from "@/api/types";
import { useErrorToast, useToast } from "@/components/Toast";
import { Badge, Button, Card, Empty, PageHeader, Spinner, VideoThumb } from "@/components/ui";
import { duration, relativeTime } from "@/lib/format";

const tagText = (tags: string[]) => tags.map(t => `#${t}`).join(" ");
const parseTags = (text: string) => Array.from(new Set(text.split(/[\s,]+/).map(t => t.replace(/^#+/, "").trim()).filter(Boolean)));

export default function ReviewQueue() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const list = useQuery({ queryKey: ["jobs", "review"], queryFn: () => jobs.list({ status: "review", order: "oldest", page_size: 100 }), refetchInterval: 15_000 });
  const accounts = useQuery({ queryKey: ["tiktok"], queryFn: tiktok.list });
  const media = useQuery({ queryKey: ["media-token"], queryFn: auth.mediaToken, staleTime: 60 * 60_000 });
  const items = list.data?.items ?? [];
  const [currentId, setCurrentId] = useState<number | null>(null);
  const [handled, setHandled] = useState<number[]>([]);
  const queue = items.filter(j => !handled.includes(j.id));
  const job = queue.find(j => j.id === currentId) ?? queue[0] ?? null;

  const [caption, setCaption] = useState("");
  const [tags, setTags] = useState("");
  const [accountId, setAccountId] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const captionRef = useRef<HTMLTextAreaElement>(null);
  const reasonRef = useRef<HTMLTextAreaElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

  // Load the next item's text as soon as it becomes the current one.
  const jobId = job?.id ?? null;
  useEffect(() => {
    if (!job) return;
    setCaption(job.rewritten_caption ?? job.video.original_title);
    setTags(tagText(job.rewritten_tags));
    setAccountId(job.tiktok_account ? String(job.tiktok_account.id) : "");
    setRejecting(false);
    setReason("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  const done = (id: number) => {
    setHandled(h => [...h, id]);  // the next item shows immediately, before the list reloads
    queryClient.invalidateQueries({ queryKey: ["jobs"] });
    queryClient.invalidateQueries({ queryKey: ["nav"] });
  };
  const dirty = !!job && (caption !== (job.rewritten_caption ?? job.video.original_title) || tags !== tagText(job.rewritten_tags) || accountId !== (job.tiktok_account ? String(job.tiktok_account.id) : ""));
  const approve = useMutation({
    mutationFn: async (j: Job) => {
      if (dirty) await jobs.update(j.id, { rewritten_caption: caption, rewritten_tags: parseTags(tags), tiktok_account_id: accountId ? Number(accountId) : null });
      return jobs.approve(j.id);
    },
    onSuccess: j => { toast({ title: "Approved", message: `Publishing to ${j.tiktok_account ? `@${j.tiktok_account.username}` : "TikTok"}.` }); done(j.id); },
    onError,
  });
  const reject = useMutation({ mutationFn: (j: Job) => jobs.reject(j.id, reason.trim()), onSuccess: j => { toast({ title: "Rejected" }); done(j.id); }, onError });
  const busy = approve.isPending || reject.isPending;

  const move = useCallback((step: number) => {
    if (!job) return;
    const index = queue.findIndex(j => j.id === job.id);
    const next = queue[index + step];
    if (next) setCurrentId(next.id);
  }, [job, queue]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = ["TEXTAREA", "INPUT", "SELECT"].includes((e.target as HTMLElement).tagName);
      if (e.key === "Escape") { (e.target as HTMLElement).blur?.(); setRejecting(false); return; }
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && job && !busy) { e.preventDefault(); if (rejecting) { if (reason.trim()) reject.mutate(job); } else approve.mutate(job); return; }
      if (typing || e.ctrlKey || e.metaKey || e.altKey || !job || busy) return;
      const key = e.key.toLowerCase();
      if (key === "a") { e.preventDefault(); approve.mutate(job); }
      else if (key === "e") { e.preventDefault(); captionRef.current?.focus(); }
      else if (key === "r") { e.preventDefault(); setRejecting(true); setTimeout(() => reasonRef.current?.focus(), 0); }
      else if (key === "j" || e.key === "ArrowDown") { e.preventDefault(); move(1); }
      else if (key === "k" || e.key === "ArrowUp") { e.preventDefault(); move(-1); }
      else if (e.key === " ") { e.preventDefault(); const v = videoRef.current; if (v) { if (v.paused) void v.play(); else v.pause(); } }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [job, busy, rejecting, reason, approve, reject, move]);

  const src = job && job.video.has_file && media.data ? apiUrl(`/videos/${job.video.id}/file`, { token: media.data.token }) : null;

  return <><PageHeader title="Review Queue" description="Watch the edited video, fix the caption, and approve or reject. Nothing is published until you approve."><Badge tone={queue.length ? "warning" : "success"}>{queue.length} waiting</Badge></PageHeader>
    {list.isLoading && <Spinner/>}
    {!list.isLoading && !job && <Card><Empty icon="check" title="Nothing to review">New videos appear here once they are downloaded, edited and captioned. With approval switched off in Settings, videos are published without stopping here.</Empty></Card>}
    {job && <div className="review-layout">
      <Card className="review-list">{queue.map(j => <button key={j.id} className={j.id === job.id ? "active" : ""} onClick={() => setCurrentId(j.id)}><VideoThumb index={j.id} image={j.video.thumbnail_url}/><div><strong>{j.video.original_title || "Untitled"}</strong><span>{j.video.channel?.display_name ?? "—"} · {relativeTime(j.created_at, { suffix: true })}</span></div></button>)}</Card>
      <Card className="review-main">
        <div>{src
          ? <video key={job.id} ref={videoRef} className="review-player" src={src} controls autoPlay loop playsInline/>
          : <div className="review-player placeholder">{job.video.files_deleted_at ? "The file was deleted after the retention period." : "The rendered file is not available."}</div>}
        </div>
        <div className="review-form">
          <div className="review-meta">
            <span>Source channel</span><strong>{job.video.channel?.display_name ?? "—"}</strong>
            <span>Original title</span><div style={{ whiteSpace: "normal" }}>{job.video.original_title}</div>
            <span>YouTube</span><div>{job.video.permalink ? <a href={job.video.permalink} target="_blank" rel="noreferrer">Open the original video</a> : "—"} · {duration(job.video.duration_sec)}</div>
            <span>Post to</span><div><select className="cell-select" value={accountId} onChange={e => setAccountId(e.target.value)}><option value="">No account</option>{(accounts.data?.items ?? []).map(a => <option key={a.id} value={a.id}>@{a.username}</option>)}</select></div>
          </div>
          {job.caption_fallback && <div className="fallback-note"><strong>Caption fallback.</strong> The AI model failed for this video, so the original YouTube title and the default hashtags are shown. Edit them before publishing.</div>}
          <div className="field"><label>Caption</label><textarea ref={captionRef} value={caption} maxLength={2200} onChange={e => setCaption(e.target.value)}/><small>{caption.length} / 2200</small></div>
          <div className="field"><label>Hashtags</label><input value={tags} onChange={e => setTags(e.target.value)} placeholder="#fyp #shorts"/><small>{parseTags(tags).length} hashtags</small></div>
          {!rejecting && <div className="review-actions">
            <Button variant="primary" icon="check" disabled={busy || !accountId} onClick={() => approve.mutate(job)}>{dirty ? "Save edits and publish" : "Approve and publish"}<kbd>A</kbd></Button>
            <Button disabled={busy} onClick={() => captionRef.current?.focus()}>Edit caption<kbd>E</kbd></Button>
            <Button variant="danger" disabled={busy} onClick={() => { setRejecting(true); setTimeout(() => reasonRef.current?.focus(), 0); }}>Reject<kbd>R</kbd></Button>
            {!accountId && <span className="cell-error">Choose a TikTok account first.</span>}
          </div>}
          {rejecting && <div className="reject-box"><div className="field"><label>Reason for rejecting</label><textarea ref={reasonRef} value={reason} maxLength={1000} onChange={e => setReason(e.target.value)} placeholder="Why is this video not published?"/></div>
            <div className="review-actions"><Button variant="danger" disabled={busy || !reason.trim()} onClick={() => reject.mutate(job)}>Reject video</Button><Button disabled={busy} onClick={() => setRejecting(false)}>Back</Button></div></div>}
          <div className="shortcut-hints"><span><kbd>A</kbd>approve</span><span><kbd>E</kbd>edit caption</span><span><kbd>R</kbd>reject</span><span><kbd>J</kbd><kbd>K</kbd>next / previous</span><span><kbd>Space</kbd>play / pause</span><span><kbd>Ctrl</kbd><kbd>Enter</kbd>confirm while typing</span><span><kbd>Esc</kbd>leave a field</span></div>
        </div>
      </Card>
    </div>}
  </>;
}
