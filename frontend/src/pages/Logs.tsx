import { Fragment, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { download } from "@/api/client";
import { logs } from "@/api/endpoints";
import { Icon } from "@/components/Icon";
import { FilterSelect } from "@/components/Menu";
import { useErrorToast } from "@/components/Toast";
import { Badge, Button, Card, Empty, PageHeader, Spinner } from "@/components/ui";
import { useDebounced } from "@/hooks/useDebounced";
import { clock } from "@/lib/format";

const PAGE_SIZE = 50;
const LEVEL_TONE = { info: "neutral", warning: "warning", error: "danger" } as const;

export default function Logs() {
  const [search, setSearch] = useState("");
  const [level, setLevel] = useState("");
  const [service, setService] = useState("");
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState<number | null>(null);
  const q = useDebounced(search);
  const onError = useErrorToast();
  useEffect(() => setPage(1), [q, level, service]);
  const { data, isLoading } = useQuery({ queryKey: ["logs", q, level, service, page], queryFn: () => logs.list({ q, level: level || undefined, service: service || undefined, page, page_size: PAGE_SIZE }), refetchInterval: 15_000 });
  const total = data?.total ?? 0;

  return <><PageHeader title="Logs" description="Inspect system events and API activity."><Button icon="download" onClick={() => download("/logs.csv", "cliprelay-logs.csv", { q, level: level || undefined, service: service || undefined }).catch(onError)}>Export CSV</Button></PageHeader>
    <div className="toolbar"><div className="search-field grow"><Icon name="search" size={16}/><input placeholder="Search messages or payloads…" value={search} onChange={e => setSearch(e.target.value)}/></div>
      <FilterSelect value={level} onChange={setLevel} options={[{ value: "", label: "All levels" }, { value: "info", label: "Info" }, { value: "warning", label: "Warning" }, { value: "error", label: "Error" }]}/>
      <FilterSelect value={service} onChange={setService} options={[{ value: "", label: "All services" }, ...(data?.services ?? []).map(s => ({ value: s, label: s }))]}/></div>
    <Card className="table-card"><div className="table-wrap"><table><thead><tr><th>Timestamp</th><th>Level</th><th>Service</th><th>Message</th><th>Request ID</th><th/></tr></thead><tbody>{data?.items.map(r => <Fragment key={r.id}><tr className="clickable" onClick={() => setExpanded(expanded === r.id ? null : r.id)}><td className="mono" title={new Date(r.created_at).toLocaleString()}>{clock(r.created_at)}</td><td><Badge tone={LEVEL_TONE[r.level] ?? "neutral"}>{r.level[0].toUpperCase() + r.level.slice(1)}</Badge></td><td><strong>{r.service}</strong></td><td style={{ whiteSpace: "normal" }}>{r.message}</td><td className="mono">{r.request_id}</td><td><span style={{ display: "inline-flex", transform: expanded === r.id ? "rotate(90deg)" : undefined }}><Icon name="chevron" size={15}/></span></td></tr>
      {expanded === r.id && <tr className="log-payload"><td colSpan={6}><pre>{JSON.stringify({ time: r.created_at, event: r.event, job_id: r.job_id, payload: r.payload }, null, 2)}</pre></td></tr>}</Fragment>)}</tbody></table></div>
      {isLoading && <Spinner/>}
      {!isLoading && data?.items.length === 0 && <Empty icon="logs" title="No log entries"/>}
      {total > PAGE_SIZE && <div className="pagination"><span>{(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)} of {total}</span><div><Button disabled={page === 1} onClick={() => setPage(p => p - 1)}>Previous</Button><Button disabled={page * PAGE_SIZE >= total} onClick={() => setPage(p => p + 1)}>Next</Button></div></div>}
    </Card></>;
}
