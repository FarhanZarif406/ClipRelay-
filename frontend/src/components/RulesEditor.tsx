import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { channels, rules, tiktok } from "@/api/endpoints";
import type { RuleDef, RuleValue, RuleValues } from "@/api/types";
import { useErrorToast, useToast } from "@/components/Toast";
import { Badge, Button, Card, Empty, Toggle } from "@/components/ui";
import { ACCOUNT_STATUS, dayTime } from "@/lib/format";

const show = (v: RuleValue | null | undefined) => (v === null || v === undefined ? "inherits" : typeof v === "boolean" ? (v ? "on" : "off") : v === "" ? "(empty)" : String(v));

function RuleInput({ def, value, onChange }: { def: RuleDef; value: RuleValue; onChange: (v: RuleValue) => void }) {
  if (def.kind === "bool") return <Toggle checked={!!value} label={def.label} onChange={() => onChange(!value)}/>;
  if (def.kind === "choice") return <select value={String(value)} onChange={e => onChange(e.target.value)}>{def.choices.map(c => <option key={c} value={c}>{c}</option>)}</select>;
  if (def.kind === "int" || def.kind === "float") return <input type="number" min={def.min ?? undefined} max={def.max ?? undefined} step={def.kind === "float" ? 0.01 : 1} value={Number.isNaN(value as number) ? "" : String(value)} onChange={e => onChange(e.target.value === "" ? NaN : Number(e.target.value))}/>;
  return <input type="text" value={String(value)} onChange={e => onChange(e.target.value)}/>;
}

const isLong = (def: RuleDef) => def.key === "caption_prompt";
const groupsOf = (defs: RuleDef[]) => Array.from(new Set(defs.map(d => d.group)));
const invalid = (v: RuleValue | null) => typeof v === "number" && Number.isNaN(v);

export function GlobalRules({ groups, title = "Pipeline rules", caption = "Global defaults. Nothing is hardcoded: a change applies to the next job, with no restart. A channel can override most of them under “Channel overrides”." , hideKeys = [] }: { groups?: string[]; title?: string; caption?: string; hideKeys?: string[] } = {}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const { data } = useQuery({ queryKey: ["rules"], queryFn: rules.get });
  const [draft, setDraft] = useState<RuleValues | null>(null);
  useEffect(() => { if (data) setDraft(data.values); }, [data]);
  const definitions = (data?.definitions ?? []).filter(d => (!groups || groups.includes(d.group)) && !hideKeys.includes(d.key));
  const headings = new Set(definitions.map(d => d.group)).size > 1;
  const changed = data && draft ? definitions.map(d => d.key).filter(k => draft[k] !== data.values[k]) : [];
  const save = useMutation({
    mutationFn: () => rules.save(Object.fromEntries(changed.map(k => [k, draft![k]]))),
    onSuccess: d => { queryClient.setQueryData(["rules"], d); queryClient.invalidateQueries({ queryKey: ["rules-history"] }); toast({ title: "Rules saved", message: "They apply to the next job." }); },
    onError,
  });
  if (!data || !draft) return null;
  return <Card><div className="card-title">{title}</div><div className="card-caption">{caption}</div>
    {groupsOf(definitions).map(group => <div className="rule-group" key={group}>{headings && <h4>{group}</h4>}
      {definitions.filter(d => d.group === group).map(def => <div className={`rule-row ${isLong(def) ? "wide" : ""}`} key={def.key}>
        <div><strong>{def.label}{draft[def.key] !== def.default && <> <Badge tone="primary" dot={false}>changed</Badge></>}</strong><small>{def.help}{def.kind !== "bool" && def.kind !== "text" ? ` Default: ${show(def.default)}.` : ""}{def.min !== null && def.max !== null && def.kind !== "text" ? ` Range ${def.min}–${def.max}.` : ""}{!def.per_channel ? " Global only." : ""}</small></div>
        {isLong(def)
          ? <textarea value={String(draft[def.key])} placeholder="Empty: the default template from Prompt Studio is used." onChange={e => setDraft({ ...draft, [def.key]: e.target.value })}/>
          : <div className="rule-control"><RuleInput def={def} value={draft[def.key]} onChange={v => setDraft({ ...draft, [def.key]: v })}/></div>}
      </div>)}</div>)}
    <div className="modal-foot"><Button disabled={!changed.length} onClick={() => setDraft(data.values)}>Discard</Button><Button variant="primary" disabled={!changed.length || save.isPending || changed.some(k => invalid(draft[k]))} onClick={() => save.mutate()}>{save.isPending ? "Saving…" : changed.length ? `Save ${changed.length} change${changed.length === 1 ? "" : "s"}` : "Saved"}</Button></div>
  </Card>;
}

export function ChannelOverrides() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const channelList = useQuery({ queryKey: ["channels"], queryFn: channels.list });
  const defs = useQuery({ queryKey: ["rules"], queryFn: rules.get });
  const [channelId, setChannelId] = useState<number | null>(null);
  const items = channelList.data?.items ?? [];
  const selected = channelId ?? items[0]?.id ?? null;
  const current = useQuery({ queryKey: ["channel-rules", selected], queryFn: () => channels.rules(selected!), enabled: selected !== null });
  const [draft, setDraft] = useState<Record<string, RuleValue | null>>({});
  useEffect(() => { setDraft({}); }, [selected, current.data]);
  const save = useMutation({
    mutationFn: () => channels.saveRules(selected!, draft),
    onSuccess: d => { queryClient.setQueryData(["channel-rules", selected], d); queryClient.invalidateQueries({ queryKey: ["channels"] }); queryClient.invalidateQueries({ queryKey: ["rules-history"] }); toast({ title: "Channel overrides saved" }); },
    onError,
  });
  if (!items.length) return <Card><Empty icon="play" title="No channels yet">Add a channel first; then any rule can be overridden for it here.</Empty></Card>;
  const perChannel = (defs.data?.definitions ?? []).filter(d => d.per_channel);
  const overrides = current.data?.overrides ?? {};
  const globals = current.data?.global ?? {};
  // What the row shows: the unsaved edit, else the saved override, else nothing (inherits).
  const valueOf = (key: string): RuleValue | null => (key in draft ? draft[key] : key in overrides ? overrides[key] : null);
  const keys = Object.keys(draft);
  return <Card><div className="card-title">Channel overrides</div><div className="card-caption">A channel with no override inherits the global value. Switch a rule on here to give this channel its own value — for example, keep a new channel on manual approval while trusted channels publish automatically.</div>
    <div className="field" style={{ marginTop: 14 }}><label>Channel</label><select value={selected ?? ""} onChange={e => setChannelId(Number(e.target.value))}>{items.map(c => <option key={c.id} value={c.id}>{c.display_name}{c.override_count ? ` (${c.override_count})` : ""}</option>)}</select></div>
    {current.data && groupsOf(perChannel).map(group => <div className="rule-group" key={group}><h4>{group}</h4>
      {perChannel.filter(d => d.group === group).map(def => { const value = valueOf(def.key); const on = value !== null; return <div className={`rule-row ${isLong(def) && on ? "wide" : ""}`} key={def.key}>
        <div><strong>{def.label} {on && <Badge tone="primary" dot={false}>override</Badge>}</strong><small>{def.help}</small></div>
        <div className="rule-control">
          {!on && <span className="inherit">Global: {show(globals[def.key])}</span>}
          {on && (isLong(def) ? <textarea value={String(value)} onChange={e => setDraft({ ...draft, [def.key]: e.target.value })}/> : <RuleInput def={def} value={value} onChange={v => setDraft({ ...draft, [def.key]: v })}/>)}
          <Button onClick={() => setDraft({ ...draft, [def.key]: on ? null : globals[def.key] })}>{on ? "Use global" : "Override"}</Button>
        </div>
      </div>; })}</div>)}
    <div className="modal-foot"><Button disabled={!keys.length} onClick={() => setDraft({})}>Discard</Button><Button variant="primary" disabled={!keys.length || save.isPending || keys.some(k => invalid(draft[k]))} onClick={() => save.mutate()}>{save.isPending ? "Saving…" : "Save overrides"}</Button></div>
  </Card>;
}

export function RuleHistory() {
  const { data } = useQuery({ queryKey: ["rules-history"], queryFn: () => rules.history() });
  return <Card className="table-card"><div style={{ padding: 20, paddingBottom: 8 }}><div className="card-title">Change history</div><div className="card-caption">Who changed which rule, and when. A wrong speed value or a flip left on by accident can be traced here.</div></div>
    <div className="table-wrap"><table className="history-table"><thead><tr><th>When</th><th>Who</th><th>Rule</th><th>Scope</th><th>From</th><th>To</th></tr></thead><tbody>
      {(data ?? []).map(c => <tr key={c.id}><td style={{ whiteSpace: "nowrap" }}>{dayTime(c.changed_at)}</td><td>{c.changed_by ?? "—"}</td><td>{c.label}</td><td>{c.channel_id ? c.channel_name ?? `Channel #${c.channel_id}` : "Global"}</td><td><code>{show(c.old_value).slice(0, 80)}</code></td><td><code>{show(c.new_value).slice(0, 80)}</code></td></tr>)}
    </tbody></table></div>
    {data && data.length === 0 && <Empty icon="logs" title="No changes yet">Every rule is at its default.</Empty>}
  </Card>;
}

export function TikTokSummary() {
  const navigate = useNavigate();
  const { data } = useQuery({ queryKey: ["tiktok"], queryFn: tiktok.list });
  const items = data?.items ?? [];
  return <Card><div className="card-title">Connected TikTok accounts</div><div className="card-caption">Each channel posts to its default account. Daily caps count per account and reset at midnight in the cap reset timezone.</div>
    <div style={{ marginTop: 10 }}>{items.map(a => { const s = ACCOUNT_STATUS[a.status] ?? { label: a.status, tone: "neutral" as const }; return <div className="api-row" key={a.id}><div><strong>@{a.username}</strong><span>{a.posts_today} / {a.daily_cap} uploads today{a.daily_cap_override ? " (own cap)" : " (global rule)"}</span></div><Badge tone={s.tone}>{s.label}</Badge></div>; })}</div>
    {items.length === 0 && <Empty icon="tiktok" title="No TikTok account connected">Connect one to start publishing.</Empty>}
    <div className="modal-foot"><Button variant="primary" onClick={() => navigate("/tiktok")}>Manage TikTok accounts</Button></div>
  </Card>;
}
