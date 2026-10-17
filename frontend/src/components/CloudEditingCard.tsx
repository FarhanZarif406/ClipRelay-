import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { cloudEditing } from "@/api/endpoints";
import type { CloudEditing } from "@/api/types";
import { Field } from "./Modal";
import { useErrorToast, useToast } from "./Toast";
import { Badge, Button, Card, Toggle } from "./ui";

/**
 * Integrations → Cloud editing (owner only): Google Cloud Run edits a video when the member's PC Helper is off.
 * The service account key goes up once and is never shown again.
 */
export function CloudEditingCard() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const { data } = useQuery({ queryKey: ["cloud-editing"], queryFn: cloudEditing.info });
  const [url, setUrl] = useState("");
  const file = useRef<HTMLInputElement>(null);
  useEffect(() => { if (data) setUrl(data.url); }, [data?.url]); // eslint-disable-line react-hooks/exhaustive-deps
  const done = (value: CloudEditing, title: string) => { queryClient.setQueryData(["cloud-editing"], value); toast({ title }); };
  const save = useMutation({ mutationFn: (body: Parameters<typeof cloudEditing.save>[0]) => cloudEditing.save(body), onSuccess: d => done(d, "Saved"), onError });
  const upload = useMutation({ mutationFn: (f: File) => cloudEditing.uploadKey(f), onSuccess: d => { done(d, "Key saved"); if (file.current) file.current.value = ""; }, onError });
  const removeKey = useMutation({ mutationFn: cloudEditing.removeKey, onSuccess: d => done(d, "Key removed"), onError });
  const test = useMutation({
    mutationFn: cloudEditing.test,
    onSuccess: result => { queryClient.invalidateQueries({ queryKey: ["cloud-editing"] }); toast({ title: result.ok ? "Cloud Run is ready" : "Cloud Run is not ready", message: result.message, tone: result.ok ? undefined : "danger" }); },
    onError,
  });
  if (!data) return null;
  const last = data.last_test;

  return <Card>
    <div className="credential-head"><div><div className="card-title">Cloud editing (Google Cloud Run)</div>
      <div className="card-caption">When a member's PC Helper is off for 3 minutes, this server downloads the video and Google Cloud Run edits it, many at a time. You pay Google per second of editing; about 1,000 short videos a month are inside Google's free allowance.</div></div>
      <Badge tone={data.ready && data.enabled ? (last?.ok ? "success" : "warning") : "neutral"}>{data.ready && data.enabled ? (last?.ok ? "Ready" : "Saved · not tested") : data.ready ? "Off" : "Not set up"}</Badge></div>

    {!data.public_url && <div className="form-note warn">This server has no public HTTPS address yet (Integrations → YouTube push). Cloud Run fetches videos from it, so cloud editing needs one.</div>}

    <form style={{ marginTop: 12 }} onSubmit={e => { e.preventDefault(); save.mutate({ url }); }}>
      <Field label="Cloud Run address" hint="Printed at the end of cloud-editor/deploy.ps1, and shown at the top of the service in Google Cloud.">
        <input value={url} onChange={e => setUrl(e.target.value)} placeholder="https://cliprelay-editor-abc123-uc.a.run.app"/></Field>
      <div className="inline-form" style={{ marginBottom: 12 }}><Button variant="primary" type="submit" disabled={save.isPending || url === data.url}>Save address</Button></div>
    </form>

    <Field label="Service account key">
      {data.has_key
        ? <div className="source-secret"><div><code>{data.client_email}</code><small>{data.project_id ? `Project ${data.project_id} · ` : ""}kept encrypted on the server, never shown again</small></div>
          <Button variant="danger" disabled={removeKey.isPending} onClick={() => window.confirm("Remove the service account key? Cloud editing stops until a new one is saved.") && removeKey.mutate()}>Remove</Button></div>
        : <div className="inline-form"><input ref={file} type="file" accept=".json,application/json" onChange={e => { const f = e.target.files?.[0]; if (f) upload.mutate(f); }}/>
          <small className="muted">The .json key file deploy.ps1 wrote (cliprelay-cloud-key.json). Delete it from your computer once saved.</small></div>}
    </Field>

    <Field label="When neither the PC nor the cloud can edit a video" hint="For example a member without the PC Helper while cloud editing is not set up, or not in their plan.">
      <select value={data.fallback} onChange={e => save.mutate({ fallback: e.target.value as "fail" | "server" })}>
        <option value="fail">Show it as failed (the member presses Retry later)</option>
        <option value="server">Edit it on this server (3 at a time)</option>
      </select></Field>

    <div className="switch-row" style={{ marginTop: 12 }}><Toggle checked={data.enabled} label="Cloud editing on" onChange={() => save.mutate({ enabled: !data.enabled })}/><span>Cloud editing on</span></div>

    <div className="inline-form" style={{ marginTop: 14 }}>
      <Button icon="refresh" disabled={!data.ready || test.isPending} onClick={() => test.mutate()}>{test.isPending ? "Testing…" : "Test Cloud Run"}</Button>
      {last && <span className={last.ok ? "muted" : "row-error"}>{last.ok ? "✓ " : ""}{last.message}</span>}
    </div>
  </Card>;
}
