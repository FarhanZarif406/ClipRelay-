import { useEffect, useRef, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { source } from "@/api/endpoints";
import type { DiagnosisRow, SourceDiagnosis, SourceInfo } from "@/api/types";
import { Badge, Button, Card } from "@/components/ui";

const MAX_COOKIES_BYTES = 1_000_000;
const day = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
const message = (error: unknown) => (error instanceof Error ? error.message : String(error));
const clientName = (client: string) => client || "Default (yt-dlp chooses)";

function InfoBox({ label, children }: { label: string; children: ReactNode }) {
  return <div className="source-box"><span>{label}</span>{children}</div>;
}

function Metric({ label, value, danger }: { label: string; value: string; danger?: boolean }) {
  return <div className="source-metric"><span>{label}</span><strong className={danger ? "bad" : ""}>{value}</strong></div>;
}

/** Uploads the cookies.txt that lets yt-dlp pass YouTube's "sign in to confirm" check. */
function CookiesUpload({ file, onChange }: { file: SourceInfo["cookies_file"] | undefined; onChange: () => void }) {
  const picker = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (work: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await work();
      onChange();
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy(false);
      if (picker.current) picker.current.value = "";
    }
  };
  const upload = (chosen: File | undefined) => {
    if (!chosen) return;
    if (chosen.size > MAX_COOKIES_BYTES) return setError("That file is too large. The limit is 1 MB.");
    void run(() => source.uploadCookies(chosen));
  };
  const expired = !!file?.present && !!file.expired;
  return <InfoBox label="Cookies file">
    <input ref={picker} type="file" accept=".txt,text/plain" hidden onChange={event => upload(event.target.files?.[0])}/>
    <b>{!file?.present ? "Not uploaded" : expired ? `Expired on ${day(file.expires_at!)}` : file.expires_at ? `${file.count} cookies · first expires ${day(file.expires_at)}` : `${file.count} cookies`}</b>
    <div className="source-actions">
      <button type="button" className="link-button" disabled={busy} onClick={() => picker.current?.click()}>{busy ? "Working…" : file?.present ? "Replace cookies.txt" : "Upload cookies.txt"}</button>
      {file?.present && <button type="button" className="link-button danger" disabled={busy} onClick={() => void run(source.removeCookies)}>Remove</button>}
    </div>
    <small className={error || expired ? "bad" : ""}>{error ?? (file?.present
      ? `Uploaded ${day(file.updated_at!)}. Kept on the server only; its contents are never shown here.`
      : "Export it in Netscape format while signed in to youtube.com. Needed when YouTube answers “Sign in to confirm you’re not a bot”.")}</small>
  </InfoBox>;
}

/** Tries one video with every YouTube player client, with the cookies file and without it. Nothing is downloaded or changed. */
function Diagnosis({ url, current, onUse }: { url: string; current: string; onUse: (client: string) => void }) {
  const [run, setRun] = useState<SourceDiagnosis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const running = run?.status === "running";
  const runId = run?.id;
  useEffect(() => {
    if (!running || !runId) return;
    const timer = setInterval(() => void source.diagnosis(runId).then(setRun, reason => setError(message(reason))), 1500);
    return () => clearInterval(timer);
  }, [running, runId]);
  const start = async () => {
    setError(null);
    setCopied(false);
    try {
      setRun(await source.diagnose(url.trim()));
    } catch (reason) {
      setError(message(reason));
    }
  };
  const tone = (row: DiagnosisRow) => (!row.ok ? "bad" : row.low ? "warn" : "good");

  return <div className="source-diagnosis">
    <div className="source-diagnosis-head"><div><b>Diagnose failed downloads</b><p>Tries the video above with every YouTube player client, with your cookies and without them, and over IPv6. Nothing is downloaded and no setting is changed. Takes a few minutes.</p></div>
      <Button onClick={() => void start()} disabled={running || !url.trim()}>{running ? "Running…" : run ? "Run again" : "Run diagnosis"}</Button></div>
    {!url.trim() && !run && <small>Paste a YouTube video link in the field above first.</small>}
    {error && <div className="form-error">{error}</div>}
    {run && <>
      {running && <p role="status">{run.stage}… {run.total > 0 && `(${run.rows.length} of ${run.total})`}</p>}
      {run.verdict && <div className={run.rows.some(row => row.ok) ? "source-verdict" : "source-verdict bad"}>{run.verdict}</div>}
      {run.version !== undefined && <small>yt-dlp {run.version ?? "—"} · JavaScript runtime: {run.js_runtime ?? "none found"} · cookies file: {run.cookies ? "in use" : "none"} · proxy: {run.proxy ? "in use" : "none"}</small>}
      {run.rows.length > 0 && <div className="table-wrap source-table"><table><thead><tr><th>Player client</th><th>Cookies</th><th>Result</th><th/></tr></thead><tbody>
        {run.rows.map(row => <tr key={`${row.client}-${row.cookies}-${row.ipv6}`}>
          <td>{clientName(row.client)}{row.ipv6 && " · over IPv6"}</td>
          <td>{row.cookies ? "With" : "Without"}</td>
          <td className={tone(row)} style={{ whiteSpace: "normal" }}>{row.ok ? `${row.message} — ${row.format}` : row.message}</td>
          {/* Offered only where it matches how downloads would really run: with the cookies file if there is one. */}
          <td>{row.ok && !row.ipv6 && row.cookies === run.cookies && (row.client !== current
            ? <button type="button" className="link-button" onClick={() => onUse(row.client)}>Use this client</button>
            : <span className="muted">In use</span>)}</td>
        </tr>)}</tbody></table></div>}
      {run.verbose && <details><summary>Full yt-dlp output for the current settings</summary>
        <small>Command{run.proxy && " (proxy address hidden)"}</small><pre>{run.command}</pre>
        <small>Output</small><pre>{run.verbose}</pre>
        <button type="button" className="link-button" onClick={() => void navigator.clipboard.writeText(`${run.command}\n\n${run.verbose}`).then(() => setCopied(true), () => {})}>{copied ? "Copied ✓" : "Copy command and output"}</button>
      </details>}
    </>}
  </div>;
}

/** Integrations → Video Source: the downloader (yt-dlp), its cookies file, proxy, player client, test and diagnosis. */
export function VideoSource() {
  const queryClient = useQueryClient();
  const { data: info } = useQuery({ queryKey: ["source"], queryFn: source.info, refetchInterval: 30_000 });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["source"] });
  const [url, setUrl] = useState("");
  const [proxy, setProxy] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (changes: { proxy?: string; player_client?: string }) => source.save(changes),
    onSuccess: data => { queryClient.setQueryData(["source"], data); setProxy(null); setSaveError(null); },
    onError: reason => setSaveError(message(reason)),
  });
  const update = useMutation({ mutationFn: source.update, onSuccess: refresh });
  const test = useMutation({ mutationFn: () => source.test(url.trim()) });
  const failed = test.data ? !test.data.ok : test.isError;
  const state = !info ? "Checking…" : !info.installed ? "Binary not found" : failed || info.stats.failed_downloads > 0 ? "Error" : "Connected";
  const proxyValue = proxy ?? info?.options.proxy ?? "";
  const cookies = info?.cookies_file;

  return <Card className="source-card">
    <div className="source-head"><div className="source-icon">DL</div><div><div className="card-title">Video Source</div><div className="card-caption">Downloads the source video after a new upload is detected.</div></div>
      <Badge tone={state === "Connected" ? "success" : state === "Checking…" ? "neutral" : "danger"}>{state}</Badge></div>

    {info && !info.installed
      ? <div className="form-error">yt-dlp is not installed or could not be found. Videos cannot be downloaded.</div>
      : <div className="source-grid">
        <InfoBox label="yt-dlp version">
          <b>{info?.version ?? "—"}</b>
          <div className="source-actions"><button type="button" className="link-button" disabled={update.isPending} onClick={() => update.mutate()}>{update.isPending ? "Updating…" : "Update now"}</button></div>
          <small className={update.data && !update.data.ok ? "bad" : ""}>{update.data ? update.data.message : update.isError ? message(update.error) : "Keep it current: YouTube changes often and old versions stop working."}</small>
        </InfoBox>
        <CookiesUpload file={cookies} onChange={refresh}/>
        <div className="source-field">
          <label htmlFor="source-proxy">Proxy</label>
          <form className="lookup-row" onSubmit={event => { event.preventDefault(); save.mutate({ proxy: proxyValue }); }}>
            <input id="source-proxy" value={proxyValue} placeholder="http://user:pass@proxy:port" autoComplete="off" spellCheck={false} onChange={event => setProxy(event.target.value)}/>
            <Button type="submit" disabled={proxy === null || save.isPending}>{save.isPending ? "Saving…" : "Save"}</Button>
          </form>
          <small className={saveError ? "bad" : ""}>{saveError ?? "Type the address and press Save. Leave it empty to use the server’s own IP."}</small>
        </div>
        <div className="source-field">
          <label htmlFor="source-client">Player client</label>
          <select id="source-client" value={info?.options.player_client ?? ""} disabled={save.isPending} onChange={event => save.mutate({ player_client: event.target.value })}>
            {(info?.player_clients ?? [""]).map(client => <option key={client} value={client}>{clientName(client)}</option>)}
          </select>
          <small>Which YouTube app yt-dlp pretends to be. Tried first; when YouTube refuses it, ClipRelay tries the other clients, no cookies and IPv6 by itself.</small>
        </div>
        <InfoBox label="Download format">
          <b>Full HD (1080p) first</b>
          <small>When a video has no 1080p, the best quality it does have is downloaded instead.</small>
        </InfoBox>
      </div>}

    <input className="source-url" value={url} placeholder="Paste a YouTube video URL to test the downloader" aria-label="Video URL to test" onChange={event => setUrl(event.target.value)}/>
    <Diagnosis url={url} current={info?.options.player_client ?? ""} onUse={client => save.mutate({ player_client: client })}/>

    <div className="source-metrics">
      <Metric label="Clips made, last 24h" value={String(info?.stats.completed ?? 0)}/>
      <Metric label="Failed downloads" value={String(info?.stats.failed_downloads ?? 0)} danger={!!info?.stats.failed_downloads}/>
      <Metric label="Cookies file" value={cookies?.present && cookies.expired ? "Expired" : info?.cookies ? "In use" : "Not set"} danger={!!cookies?.present && !!cookies.expired}/>
      <Metric label="Proxy" value={info?.options.proxy_set ? "In use" : "Direct"}/>
      <Metric label="Route that last worked" value={info?.working_route ?? "None yet"}/>
    </div>
    <div className="source-test">
      <Button disabled={test.isPending || !url.trim()} onClick={() => test.mutate()}>{test.isPending ? "Testing…" : "Test download"}</Button>
      <span className={failed ? "bad" : ""}>{test.isPending ? "Asking YouTube…" : test.data ? test.data.message : test.isError ? message(test.error) : url.trim() ? "Ready to test." : "Paste a YouTube video link above, then test."}</span>
    </div>
  </Card>;
}
