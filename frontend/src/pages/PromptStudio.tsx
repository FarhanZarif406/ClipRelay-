import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { jobs, prompts, type PromptBody } from "@/api/endpoints";
import type { Prompt } from "@/api/types";
import { Icon } from "@/components/Icon";
import { Menu } from "@/components/Menu";
import { Modal } from "@/components/Modal";
import { useErrorToast, useToast } from "@/components/Toast";
import { Badge, Button, Card, Empty, PageHeader, Toggle } from "@/components/ui";
import { dayTime, relativeTime } from "@/lib/format";

type Tab = "Title" | "Caption" | "Hashtags";
const FIELD: Record<Tab, "title_prompt" | "caption_prompt" | "hashtags_prompt"> = { Title: "title_prompt", Caption: "caption_prompt", Hashtags: "hashtags_prompt" };
const SAMPLE = "We found this amazing hidden beach on our trip around Crete. It took 40 minutes to hike down but was so worth it! #crete #travel";

const toBody = (p: Prompt | PromptBody): PromptBody => ({ name: p.name, description: p.description, niche: p.niche, title_prompt: p.title_prompt, caption_prompt: p.caption_prompt, hashtags_prompt: p.hashtags_prompt, is_enabled: p.is_enabled });

function VersionHistory({ prompt, close }: { prompt: Prompt; close: () => void }) {
  const queryClient = useQueryClient();
  const onError = useErrorToast();
  const { data } = useQuery({ queryKey: ["prompts", prompt.id, "versions"], queryFn: () => prompts.versions(prompt.id) });
  const restore = useMutation({ mutationFn: (v: number) => prompts.restore(prompt.id, v), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["prompts"] }); close(); }, onError });
  return <Modal title="Version history" caption={`Every save of “${prompt.name}” is kept. Restoring creates a new version.`} onClose={close}>
    <div className="check-list" style={{ maxHeight: 360 }}>{data?.map((v, i) => <label key={v.version} style={{ cursor: "default" }}><strong>v{v.version}</strong><span style={{ color: "var(--muted)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{dayTime(v.created_at)} · {v.snapshot.caption_prompt.slice(0, 60)}</span>{i === 0 ? <Badge tone="primary" dot={false}>Current</Badge> : <Button onClick={() => restore.mutate(v.version)} disabled={restore.isPending}>Restore</Button>}</label>)}</div>
    {data?.length === 0 && <Empty title="No versions yet"/>}
  </Modal>;
}

export default function PromptStudio() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const list = useQuery({ queryKey: ["prompts"], queryFn: prompts.list });
  const meta = useQuery({ queryKey: ["prompts", "meta"], queryFn: prompts.meta });
  const sample = useQuery({ queryKey: ["jobs", "sample-video"], queryFn: () => jobs.videos("accepted", 1) });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [draft, setDraft] = useState<PromptBody | null>(null);
  const [tab, setTab] = useState<Tab>("Caption");
  const [original, setOriginal] = useState(SAMPLE);
  const [preview, setPreview] = useState<{ title: string; caption: string; tags: string[] } | null>(null);
  const [history, setHistory] = useState(false);
  const editor = useRef<HTMLTextAreaElement>(null);
  const selected = list.data?.find(p => p.id === selectedId) ?? null;

  useEffect(() => { if (list.data?.length && !list.data.some(p => p.id === selectedId)) setSelectedId(list.data[0].id); }, [list.data, selectedId]);
  useEffect(() => { if (selected) { setDraft(toBody(selected)); setPreview(null); } }, [selected?.id, selected?.updated_at]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const v = sample.data?.[0]; if (v?.original_caption) setOriginal(v.original_caption); }, [sample.data]);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["prompts"] });
  const save = useMutation({ mutationFn: () => prompts.update(selectedId!, draft!), onSuccess: () => { invalidate(); toast({ title: "Prompt saved", message: "A new version was added to the history." }); }, onError });
  const create = useMutation({
    mutationFn: () => prompts.create({ name: "Untitled prompt", description: "Describe what this prompt is for", niche: "", title_prompt: "Write a short, punchy TikTok title (max 80 characters) for:\n{title}", caption_prompt: "Rewrite the {caption} into a concise, engaging TikTok caption.\n\nLead with a strong hook, keep it authentic, avoid clickbait. Maximum 160 characters.", hashtags_prompt: "Suggest 4-6 relevant TikTok hashtags for: {caption}\nOriginal tags: {tags}", is_enabled: true }),
    onSuccess: p => { invalidate(); setSelectedId(p.id); }, onError,
  });
  const makeDefault = useMutation({ mutationFn: (id: number) => prompts.makeDefault(id), onSuccess: invalidate, onError });
  const remove = useMutation({ mutationFn: (id: number) => prompts.remove(id), onSuccess: () => { setSelectedId(null); invalidate(); }, onError });
  const test = useMutation({
    mutationFn: () => prompts.test({ ...draft!, caption: original, tags: (original.match(/#(\w+)/g) ?? []).map(t => t.slice(1)) }),
    onSuccess: setPreview, onError,
  });

  const field = FIELD[tab];
  const insert = (variable: string) => {
    if (!draft) return;
    const el = editor.current;
    const text = draft[field];
    const start = el?.selectionStart ?? text.length;
    const end = el?.selectionEnd ?? text.length;
    setDraft({ ...draft, [field]: text.slice(0, start) + variable + text.slice(end) });
    requestAnimationFrame(() => { el?.focus(); el?.setSelectionRange(start + variable.length, start + variable.length); });
  };
  const words = draft ? draft[field].trim().split(/\s+/).filter(Boolean).length : 0;
  const dirty = !!(draft && selected && JSON.stringify(draft) !== JSON.stringify(toBody(selected)));

  return <><PageHeader title="Prompt Studio" description="Shape how AI rewrites your content for each channel."><Button onClick={() => setHistory(true)} disabled={!selected}>Version history</Button><Button variant="primary" onClick={() => save.mutate()} disabled={!dirty || save.isPending}>Save prompt</Button></PageHeader>
    <div className="studio"><Card className="prompt-list"><div className="list-title">Your prompts <Button variant="ghost" icon="plus" onClick={() => create.mutate()}/></div>{list.data?.map(p => <button key={p.id} className={p.id === selectedId ? "active" : ""} onClick={() => { if (!dirty || window.confirm("Discard unsaved changes?")) setSelectedId(p.id); }}><span><Icon name="sparkles" size={15}/></span><div><strong>{p.name}</strong><small>{p.is_default ? "Default · " : ""}{p.is_enabled ? "" : "Disabled · "}edited {relativeTime(p.updated_at, { suffix: true })}</small></div>{p.is_default && <Badge tone="primary" dot={false}>Default</Badge>}</button>)}</Card>
      {draft && selected ? <Card className="editor-card"><div className="editor-top"><div style={{ flex: 1 }}><input className="prompt-name-input" value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })} aria-label="Prompt name"/><input className="prompt-desc-input" value={draft.description} onChange={e => setDraft({ ...draft, description: e.target.value })} aria-label="Description"/></div><div style={{ display: "flex", alignItems: "center", gap: 6 }}><Toggle checked={draft.is_enabled} onChange={() => setDraft({ ...draft, is_enabled: !draft.is_enabled })} label="Enabled"/>
          <Menu items={[{ label: "Set as default", icon: "check", disabled: selected.is_default, onSelect: () => makeDefault.mutate(selected.id) }, { label: "Delete prompt", icon: "close", danger: true, disabled: selected.is_default, onSelect: () => window.confirm(`Delete “${selected.name}”?`) && remove.mutate(selected.id) }]} trigger={t => <Button variant="ghost" icon="more" onClick={t}/>}/></div></div>
        <div className="tabs">{(["Title", "Caption", "Hashtags"] as Tab[]).map(t => <button key={t} onClick={() => setTab(t)} className={tab === t ? "active" : ""}>{t}</button>)}</div>
        <div className="variable-row"><span>Insert variable</span>{(meta.data?.variables ?? ["{title}", "{caption}", "{tags}", "{source}", "{niche}"]).map(v => <button key={v} type="button" onClick={() => insert(v)}>{v}</button>)}</div>
        <textarea ref={editor} className="prompt-editor" value={draft[field]} onChange={e => setDraft({ ...draft, [field]: e.target.value })} placeholder={`Leave empty to keep the original ${tab.toLowerCase()}.`}/>
        <div className="editor-foot"><span><Icon name="code" size={15}/> {words} words · {meta.data?.model ?? "LLM"}{meta.data && !meta.data.configured ? " (not configured)" : ""}</span><Button variant="primary" icon="play" onClick={() => test.mutate()} disabled={test.isPending}>{test.isPending ? "Testing…" : "Test prompt"}</Button></div></Card>
        : <Card className="editor-card"><Empty title="No prompt selected">Create a prompt with the + button.</Empty></Card>}
      <Card className="preview-card"><div className="card-title">Live preview</div><div className="preview-label">ORIGINAL</div><textarea className="preview-text editable" value={original} onChange={e => setOriginal(e.target.value)} aria-label="Original caption"/><Icon name="arrow"/><div className="preview-label purple">REWRITTEN</div>
        <div className="preview-text output">{preview ? (tab === "Title" ? preview.title : preview.caption) : <span style={{ color: "var(--muted)" }}>Run “Test prompt” to preview the rewrite.</span>}</div>
        {preview && <div className="hashtags">{preview.tags.map(t => `#${t}`).join(" ")}</div>}</Card></div>
    {history && selected && <VersionHistory prompt={selected} close={() => setHistory(false)}/>}
  </>;
}
