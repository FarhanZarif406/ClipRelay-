import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { auth, editing, library as libraryApi } from "@/api/endpoints";
import type { EditingState, Library, Preset } from "@/api/types";
import { AudioCard, FrameCard, HookCard, MusicCard, QualityCard, SpeedCard, WatermarkCard } from "@/components/EditingCards";
import { EditingPreview, TestRenderModal } from "@/components/EditingPreview";
import { Field, Modal } from "@/components/Modal";
import { useToast } from "@/components/Toast";
import { Button, Card, PageHeader, Spinner, Toggle } from "@/components/ui";
import { capital, countChanges, type Look } from "@/lib/look";
import { PODCASTS } from "@/lib/mode";

/** The sections of the rules. One is open at a time, so the preview beside it stays in view. */
const SECTIONS = [
  { value: "frame", label: "Frame", part: (l: Look) => l.frame },
  { value: "speed", label: "Speed", part: (l: Look) => l.speed },
  { value: "quality", label: "Quality", part: (l: Look) => [l.encoding.resolution, l.encoding.fps, l.encoding.preset, l.encoding.crf] },
  { value: "audio", label: "Audio", part: (l: Look) => [l.encoding.keep_audio, l.encoding.loudnorm, l.encoding.audio_bitrate] },
  { value: "music", label: "Background music", part: (l: Look) => l.music },
  { value: "hook", label: "Hook text", part: (l: Look) => l.hook },
  { value: "watermark", label: "Watermark", part: (l: Look) => l.watermark },
] as const;
type Section = (typeof SECTIONS)[number]["value"];
const message = (reason: unknown) => (reason instanceof Error ? reason.message : String(reason));
const day = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });

function PresetModal({ currentName, onSave, onClose }: { currentName?: string; onSave: (name: string) => Promise<void>; onClose: () => void }) {
  const [name, setName] = useState(currentName ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ready = name.trim() !== "" && name.trim() !== currentName && !saving;
  const submit = async (event?: FormEvent) => {
    event?.preventDefault();
    if (!ready) return;
    setSaving(true);
    setError(null);
    try {
      await onSave(name.trim());
      onClose();
    } catch (reason) {
      setError(message(reason));
      setSaving(false);
    }
  };
  return <Modal title={currentName ? "Rename preset" : "Save as new preset"} caption={currentName ? undefined : "The rules on screen are saved under this name. Give it to channels in the table below."} onClose={onClose}
    footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!ready} onClick={() => void submit()}>{saving ? "Saving…" : currentName ? "Rename" : "Save preset"}</Button></>}>
    <form onSubmit={e => void submit(e)}><Field label="Preset name"><input autoFocus maxLength={60} value={name} placeholder="e.g. Product demos — left" onChange={e => setName(e.target.value)}/></Field></form>
    {error && <div className="form-error">{error}</div>}
  </Modal>;
}

function PerChannelRules({ state, onAssign }: { state: EditingState; onAssign: (channelId: number, presetId: number | null) => void }) {
  const [showAll, setShowAll] = useState(false);
  const rows = showAll ? state.channels : state.channels.filter(c => c.preset_id !== null);
  return <Card className="table-card per-channel">
    <div className="card-header"><div><div className="card-title">Per-channel rules</div><div className="card-caption">Channels not listed here use the Default rules.</div></div>
      <label className="inline-toggle"><Toggle checked={showAll} label="Show all channels" onChange={() => setShowAll(v => !v)}/><span>Show all channels</span></label></div>
    <div className="table-wrap"><table><thead><tr><th>Channel</th><th>Preset</th><th>Shape</th><th>Crop</th><th>Speed</th><th>Preset changed</th><th/></tr></thead><tbody>
      {rows.map(c => { const preset = state.presets.find(p => p.id === c.preset_id); const look = preset?.look ?? state.default; return <tr key={c.id}>
        <td><div className="channel-cell">{c.thumbnail_url ? <img src={c.thumbnail_url} alt="" referrerPolicy="no-referrer"/> : <div className="channel-blank"/>}<div><strong>{c.display_name}</strong></div></div></td>
        <td><select className="cell-select" aria-label={`Preset for ${c.display_name}`} value={preset?.id ?? 0} onChange={e => onAssign(c.id, Number(e.target.value) || null)}>
          <option value={0}>Default</option>{state.presets.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></td>
        <td>{look.frame.aspect}</td><td>{capital(look.frame.position)}</td><td>{look.speed.speed.toFixed(2)}x</td>
        <td>{preset ? day(preset.updated_at) : "—"}</td>
        <td>{preset && <button type="button" className="link-button danger" onClick={() => onAssign(c.id, null)}>Clear</button>}</td>
      </tr>; })}</tbody></table></div>
    {rows.length === 0 && <p className="note-row" style={{ padding: "14px 18px", margin: 0 }}>{state.channels.length === 0 ? "No channels are being monitored yet." : state.presets.length === 0 ? "Every channel uses the Default rules. Save a preset above to give a channel its own." : "Every channel uses the Default rules. Turn on “Show all channels” to give one a preset."}</p>}
  </Card>;
}

export default function EditingRules() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { data: state, error: loadError } = useQuery({ queryKey: ["editing"], queryFn: editing.get });
  const token = useQuery({ queryKey: ["media-token"], queryFn: auth.mediaToken, staleTime: 60 * 60_000 }).data?.token;
  const [music, setMusic] = useState<Library | null>(null);
  const [fonts, setFonts] = useState<Library | null>(null);
  const [watermark, setWatermark] = useState<Library | null>(null);
  const [selected, setSelected] = useState<number | null>(null);  // the preset being edited, or null for the default rules
  const [draft, setDraft] = useState<Look | null>(null);
  const [saving, setSaving] = useState(false);
  const [modal, setModal] = useState<"new" | "rename" | "test" | null>(null);
  const [tab, setTab] = useState<Section>("frame");

  useEffect(() => {
    void libraryApi.list("music").then(setMusic, () => {});
    void libraryApi.list("fonts").then(setFonts, () => {});
    void libraryApi.list("watermark").then(setWatermark, () => {});
  }, []);
  const preset = state?.presets.find(p => p.id === selected) ?? null;
  const saved = preset?.look ?? state?.default ?? null;
  useEffect(() => { if (saved && !draft) setDraft(saved); }, [saved, draft]);
  const changes = draft && saved ? countChanges(draft, saved) : 0;
  const fail = (reason: unknown) => toast({ title: "Not saved", message: message(reason), tone: "danger" });

  const save = useCallback(async () => {
    if (!draft || saving) return;
    setSaving(true);
    try {
      if (preset) {
        const updated = await editing.updatePreset(preset.id, { look: draft });
        queryClient.setQueryData<EditingState>(["editing"], s => s && { ...s, presets: s.presets.map(p => (p.id === updated.id ? updated : p)) });
        setDraft(updated.look);
        toast({ title: `Saved preset “${updated.name}”` });
      } else {
        const next = await editing.saveDefault(draft);
        queryClient.setQueryData(["editing"], next);
        setDraft(next.default);
        toast({ title: "Editing rules saved", message: "They apply to new videos." });
      }
    } catch (reason) {
      fail(reason);
    } finally {
      setSaving(false);
    }
  }, [draft, saving, preset, queryClient, toast]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Ctrl+S / ⌘S saves.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s" && changes > 0) { e.preventDefault(); void save(); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [changes, save]);

  if (loadError) return <div className="form-error">{message(loadError)}</div>;
  if (!state || !draft || !saved) return <><PageHeader title="Editing Rules" description="How your clips are edited."/><Spinner/></>;

  const open = (id: number | null) => {
    if (id === selected) return;
    if (changes > 0 && !window.confirm("Discard your unsaved changes?")) return;
    setSelected(id);
    setDraft(state.presets.find(p => p.id === id)?.look ?? state.default);
  };
  /** `onReset` for a card: puts its part of the look back to the saved values, offered only while they differ. */
  const reset = <K extends keyof Look>(...sections: K[]) => (sections.some(s => countChanges(draft[s], saved[s]) > 0) ? () => setDraft({ ...draft, ...Object.fromEntries(sections.map(s => [s, saved[s]])) }) : undefined);
  const resetEncoding = (...keys: (keyof Look["encoding"])[]) =>
    keys.some(k => draft.encoding[k] !== saved.encoding[k]) ? () => setDraft({ ...draft, encoding: { ...draft.encoding, ...Object.fromEntries(keys.map(k => [k, saved.encoding[k]])) } }) : undefined;
  const refresh = (next: EditingState) => queryClient.setQueryData(["editing"], next);

  const saveNewPreset = async (name: string) => {
    const created = await editing.createPreset(name, draft);
    queryClient.setQueryData<EditingState>(["editing"], s => s && { ...s, presets: [...s.presets, created].sort((a, b) => a.name.localeCompare(b.name)) });
    setSelected(created.id);
    setDraft(created.look);
    toast({ title: `Saved preset “${created.name}”` });
  };
  const renamePreset = async (name: string) => {
    if (!preset) return;
    const updated = await editing.updatePreset(preset.id, { name });
    queryClient.setQueryData<EditingState>(["editing"], s => s && { ...s, presets: s.presets.map(p => (p.id === updated.id ? updated : p)) });
    toast({ title: `Renamed to “${updated.name}”` });
  };
  const removePreset = async (p: Preset) => {
    const used = p.channels ? ` ${p.channels} ${p.channels === 1 ? "channel goes" : "channels go"} back to the Default rules.` : "";
    if (!window.confirm(`Delete the preset “${p.name}”?${used}`)) return;
    try {
      await editing.deletePreset(p.id);
      refresh(await editing.get());
      setSelected(null);
      setDraft(state.default);
      toast({ title: `Deleted preset “${p.name}”` });
    } catch (reason) {
      fail(reason);
    }
  };
  const assign = async (channelId: number, presetId: number | null) => {
    try {
      refresh(await editing.assign(channelId, presetId));
      toast({ title: presetId === null ? "Channel is back on the Default rules" : "Preset given to the channel", message: "It applies to this channel’s new videos." });
    } catch (reason) {
      fail(reason);
    }
  };

  return <><PageHeader title="Editing Rules" description={`How your ${PODCASTS ? "clips" : "videos"} are edited. These rules are your own; changes apply to new ${PODCASTS ? "clips" : "videos"} only.`}/>
    <div className="preset-bar">
      <button type="button" className={selected === null ? "active" : ""} aria-pressed={selected === null} onClick={() => open(null)}>Default{selected === null && " ✓"}</button>
      {state.presets.map(p => <button type="button" key={p.id} className={selected === p.id ? "active" : ""} aria-pressed={selected === p.id} title={`Used by ${p.channels} ${p.channels === 1 ? "channel" : "channels"}`} onClick={() => open(p.id)}>{p.name}{selected === p.id && " ✓"}</button>)}
      <button type="button" className="new" title="Saves the rules on screen as a new preset" onClick={() => setModal("new")}>+ New preset</button>
      {preset && <span className="preset-actions"><button type="button" className="link-button" onClick={() => setModal("rename")}>Rename</button><button type="button" className="link-button danger" onClick={() => void removePreset(preset)}>Delete preset</button></span>}
    </div>
    <div className="section-tabs" role="tablist" aria-label="Sections of the rules">{SECTIONS.map(s => <button type="button" role="tab" key={s.value} aria-selected={tab === s.value} className={tab === s.value ? "active" : ""} onClick={() => setTab(s.value)}>
      {s.label}{countChanges(s.part(draft), s.part(saved)) > 0 && <i title="Unsaved changes"/>}</button>)}</div>
    <div className="editing-layout">
      <div className="editing-cards">
        {tab === "frame" && <FrameCard look={draft} onChange={setDraft} onReset={reset("frame")}/>}
        {tab === "speed" && <SpeedCard look={draft} onChange={setDraft} onReset={reset("speed")}/>}
        {tab === "quality" && <QualityCard look={draft} onChange={setDraft} seconds={PODCASTS ? 45 : 40} onReset={resetEncoding("resolution", "fps", "preset", "crf")}/>}
        {tab === "audio" && <AudioCard look={draft} onChange={setDraft} onReset={resetEncoding("keep_audio", "loudnorm", "audio_bitrate")}/>}
        {tab === "music" && <MusicCard look={draft} onChange={setDraft} onReset={reset("music")} library={music} onLibrary={setMusic} onError={fail} token={token}/>}
        {tab === "hook" && <HookCard look={draft} onChange={setDraft} onReset={reset("hook")} fonts={fonts} onFonts={setFonts} onError={fail} fontAvailable={state.font_available}/>}
        {tab === "watermark" && <WatermarkCard look={draft} onChange={setDraft} onReset={reset("watermark")} file={watermark} onFile={next => { setWatermark(next); toast({ title: next.items.length ? "Watermark image saved" : "Watermark image removed" }); }} onError={fail} token={token}/>}
      </div>
      <EditingPreview look={draft} watermark={watermark} token={token} rendered={state.rendered_last_day} onTest={() => setModal("test")}/>
    </div>
    <PerChannelRules state={state} onAssign={(id, presetId) => void assign(id, presetId)}/>
    <div className={`save-bar${changes ? " dirty" : ""}`}>
      <div><b>{changes ? `${changes} unsaved ${changes === 1 ? "change" : "changes"}${preset ? ` to “${preset.name}”` : ""}` : "All changes saved"}</b>
        <small className="muted">Applies to new {PODCASTS ? "clips" : "videos"} only.{changes ? " Ctrl+S saves." : ""}</small></div>
      {changes > 0 && <div className="save-actions"><Button disabled={saving} onClick={() => setDraft(saved)}>Discard</Button><Button variant="primary" disabled={saving} onClick={() => void save()}>{saving ? "Saving…" : preset ? "Save preset" : "Save rules"}</Button></div>}
    </div>
    {modal === "new" && <PresetModal onSave={saveNewPreset} onClose={() => setModal(null)}/>}
    {modal === "rename" && preset && <PresetModal currentName={preset.name} onSave={renamePreset} onClose={() => setModal(null)}/>}
    {modal === "test" && <TestRenderModal look={draft} onSave={changes > 0 ? () => void save() : undefined} onClose={() => setModal(null)}/>}
  </>;
}
