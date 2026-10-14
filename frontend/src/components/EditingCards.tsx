import { useRef, useState, type ReactNode } from "react";
import { library as libraryApi, type LibraryKind } from "@/api/endpoints";
import type { Library } from "@/api/types";
import { Field } from "@/components/Modal";
import { Button, Toggle } from "@/components/ui";
import {
  ADJUSTMENTS, ASPECTS, ASPECT_NAMES, AUDIO_BITRATES, ENCODER_PRESETS, FRAME_RATES, WATERMARK_PLACES, adjusted, aspectParts, estimateBytes, formatBytes, outputSize, patch, patchBox, sourceFit,
  type Look, type WatermarkPlace,
} from "@/lib/look";

/** What every card works with: the look being edited, a way to change it, and an undo for its own settings. */
export type CardProps = { look: Look; onChange: (look: Look) => void; onReset?: () => void };

export function RuleCard({ title, desc, onReset, children }: { title: string; desc: string; onReset?: () => void; children: ReactNode }) {
  return <section className="card rule-card">
    <header><div><div className="card-title">{title}</div><div className="card-caption">{desc}</div></div>
      {onReset && <button type="button" className="rule-undo" title="Undo changes to this card" aria-label={`Undo changes to ${title}`} onClick={onReset}>↺</button>}</header>
    {children}
  </section>;
}

export function Range({ min, max, value, onChange, readout, step = 1 }: { min: number; max: number; value: number; onChange: (value: number) => void; readout: string; step?: number }) {
  return <div className="range-row"><input type="range" min={min} max={max} step={step} value={value} onChange={e => onChange(Number(e.target.value))}/><b>{readout}</b></div>;
}

export function NumberInput({ value, onChange, min, max, step = 1, suffix }: { value: number; onChange: (value: number) => void; min: number; max: number; step?: number; suffix?: string }) {
  return <div className="number-input"><input type="number" min={min} max={max} step={step} value={Number.isNaN(value) ? "" : value} onChange={e => onChange(e.target.value === "" ? NaN : Number(e.target.value))}/>{suffix && <span>{suffix}</span>}</div>;
}

export function ColorInput({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return <div className="color-input"><input type="color" value={value} onChange={e => onChange(e.target.value)}/><input value={value} maxLength={7} spellCheck={false} onChange={e => /^#[0-9a-fA-F]{0,6}$/.test(e.target.value) && onChange(e.target.value)}/></div>;
}

function Readout({ children }: { children: ReactNode }) {
  return <div className="rule-readout">{children}</div>;
}

const grid = (children: ReactNode) => <div className="rule-grid">{children}</div>;

// ---------------------------------------------------------------- Frame

const POSITIONS = [{ value: "left", label: "Left", x: 0 }, { value: "centre", label: "Centre", x: 0.5 }, { value: "right", label: "Right", x: 1 }] as const;
const FIT_HELP = {
  sides: "The outlined part of a widescreen video is kept. A source that is already this shape, such as a Short, is never cropped.",
  ends: "A widescreen video is a little too tall for this shape, so a strip is cropped from its top and bottom.",
  whole: "A widescreen video already has this shape, so nothing is cropped.",
};

export function FrameCard({ look, onChange, onReset }: CardProps) {
  const { aspect, position, zoom, flip } = look.frame;
  const [w, h] = aspectParts(aspect);
  const fit = sourceFit(16, 9, aspect);
  const source = 16 / 9;
  // The kept part of a widescreen picture, as shares of its width and height.
  const width = (fit === "sides" ? w / h / source : 1) * (fit === "whole" ? 1 : 1 / zoom) * 100;
  const height = (fit === "ends" ? source / (w / h) : 1) * (fit === "whole" ? 1 : 1 / zoom) * 100;
  const x = POSITIONS.find(p => p.value === position)!.x;
  return <RuleCard title="Frame" desc="Choose the clip’s shape and how the widescreen source is fitted into it." onReset={onReset}>
    {grid(<>
      <Field label="Aspect ratio" hint="Vertical 9:16 suits TikTok, Reels and Shorts.">
        <select value={aspect} onChange={e => onChange(patch(look, "frame", { aspect: e.target.value as Look["frame"]["aspect"] }))}>{ASPECTS.map(a => <option key={a} value={a}>{a} — {ASPECT_NAMES[a]}</option>)}</select></Field>
      <Field label="Horizontal flip"><Toggle checked={flip} label="Horizontal flip" onChange={() => onChange(patch(look, "frame", { flip: !flip }))}/></Field>
    </>)}
    <Field label="Crop position" hint={FIT_HELP[fit]}>
      <div className="crop-source"><i style={{ width: `${width}%`, height: `${height}%`, left: `${(100 - width) * (fit === "sides" ? x : 0.5)}%`, top: `${(100 - height) / 2}%` }}/></div>
      <div className="segmented crop-buttons">{POSITIONS.map(p => <button type="button" key={p.value} className={position === p.value ? "active" : ""} disabled={fit !== "sides"} aria-pressed={position === p.value}
        onClick={() => onChange(patch(look, "frame", { position: p.value }))}>{p.label}</button>)}</div>
    </Field>
    <Field label="Zoom" hint="Crops in tighter when the subject is small."><Range min={100} max={130} value={Math.round(zoom * 100)} readout={`${Math.round(zoom * 100)}%`} onChange={v => onChange(patch(look, "frame", { zoom: v / 100 }))}/></Field>
  </RuleCard>;
}

// ---------------------------------------------------------------- Adjust

const ADJUST_HELP: Record<string, string> = {
  Light: "How bright the picture is, and how far apart its dark and bright parts are.",
  Colour: "How strong the colours are, and which way they lean.",
  Detail: "Crisper edges, darker corners and film grain. Sharpness shows in the test render, not on the photo.",
};

export function AdjustCard({ look, onChange, onReset }: CardProps) {
  const a = look.adjust;
  const signed = (v: number, unit = "") => `${v > 0 ? "+" : ""}${v}${unit}`;
  return <RuleCard title="Adjust" desc="Light, colour and detail of the picture. Everything at 0 leaves it as it is." onReset={onReset}>
    {(["Light", "Colour", "Detail"] as const).map((group, i) => <div key={group} className="adjust-group">
      <h3 className={i ? "rule-heading" : "rule-heading first"}>{group}</h3>
      <small className="muted">{ADJUST_HELP[group]}</small>
      {grid(ADJUSTMENTS.filter(x => x.group === group).map(x => <Field key={x.key} label={x.label}>
        <div onDoubleClick={() => onChange(patch(look, "adjust", { [x.key]: 0 }))} title="Double-click to put it back to 0">
          <Range min={x.min} max={x.max} value={a[x.key]} readout={x.min < 0 ? signed(a[x.key], x.key === "hue" ? "°" : "") : String(a[x.key])} onChange={v => onChange(patch(look, "adjust", { [x.key]: v }))}/>
        </div></Field>))}
    </div>)}
    {adjusted(a) && <button type="button" className="link-button" style={{ justifySelf: "start" }} onClick={() => onChange(patch(look, "adjust", Object.fromEntries(ADJUSTMENTS.map(x => [x.key, 0]))))}>Put every adjustment back to 0</button>}
  </RuleCard>;
}

// ---------------------------------------------------------------- Speed

export function SpeedCard({ look, onChange, onReset }: CardProps) {
  const { speed, keep_pitch } = look.speed;
  return <RuleCard title="Speed" desc="Adjust pacing while keeping speech natural." onReset={onReset}>
    <Field label="Playback speed"><Range min={100} max={150} value={Math.round(speed * 100)} readout={`${speed.toFixed(2)}×`} onChange={v => onChange(patch(look, "speed", { speed: v / 100 }))}/></Field>
    <Field label="Match audio pitch" hint={keep_pitch ? "Keeps voices sounding normal at higher speed." : "Off: voices rise in pitch with the speed, like a record played faster."}>
      <Toggle checked={keep_pitch} label="Match audio pitch" onChange={() => onChange(patch(look, "speed", { keep_pitch: !keep_pitch }))}/></Field>
    <Readout>A 60-second video becomes <b>{(60 / speed).toFixed(1)} seconds</b>.</Readout>
  </RuleCard>;
}

// ---------------------------------------------------------------- Quality

export function QualityCard({ look, onChange, onReset, seconds }: CardProps & { seconds: number }) {
  const e = look.encoding;
  return <RuleCard title="Quality" desc="Balance clarity, file size, and rendering time." onReset={onReset}>
    {grid(<>
      <Field label="Resolution" hint={`Clips come out at ${outputSize(look).join(" × ")} pixels.`}>
        <select value={e.resolution} onChange={x => onChange(patch(look, "encoding", { resolution: x.target.value as Look["encoding"]["resolution"] }))}><option value="1080x1920">Full HD · 1080p</option><option value="720x1280">HD · 720p</option></select></Field>
      <Field label="Frame rate"><select value={e.fps} onChange={x => onChange(patch(look, "encoding", { fps: Number(x.target.value) as Look["encoding"]["fps"] }))}>{FRAME_RATES.map(f => <option key={f} value={f}>{f} fps</option>)}</select></Field>
      <Field label="Encoder preset" hint="Slower takes longer but produces a smaller file."><select value={e.preset} onChange={x => onChange(patch(look, "encoding", { preset: x.target.value as Look["encoding"]["preset"] }))}>{ENCODER_PRESETS.map(p => <option key={p} value={p}>{p[0].toUpperCase() + p.slice(1)}</option>)}</select></Field>
      <Field label="Quality (CRF)" hint="Lower is sharper and larger. 23 is a good balance."><Range min={18} max={28} value={e.crf} readout={String(e.crf)} onChange={crf => onChange(patch(look, "encoding", { crf }))}/>
        <div className="range-labels"><span>Higher quality</span><span>Smaller file</span></div></Field>
    </>)}
    <Readout>Estimated output size: <b>about {formatBytes(estimateBytes(look, seconds))}</b> for a {Math.round(seconds)}-second clip</Readout>
  </RuleCard>;
}

// ---------------------------------------------------------------- Audio

export function AudioCard({ look, onChange, onReset }: CardProps) {
  const e = look.encoding;
  return <RuleCard title="Audio" desc="Keep output loudness and clarity consistent." onReset={onReset}>
    {grid(<>
      <Field label="Keep the original sound" hint={e.keep_audio ? "The video’s own sound stays." : "Off: the video’s own sound is removed. Background music, if on, is the only sound."}>
        <Toggle checked={e.keep_audio} label="Keep the original sound" onChange={() => onChange(patch(look, "encoding", { keep_audio: !e.keep_audio }))}/></Field>
      <Field label="Normalise loudness" hint="Matches TikTok’s loudness so clips are not quieter than other videos.">
        <Toggle checked={e.loudnorm} label="Normalise loudness" onChange={() => onChange(patch(look, "encoding", { loudnorm: !e.loudnorm }))}/></Field>
      <Field label="Audio bitrate"><select value={e.audio_bitrate} onChange={x => onChange(patch(look, "encoding", { audio_bitrate: Number(x.target.value) as Look["encoding"]["audio_bitrate"] }))}>{AUDIO_BITRATES.map(b => <option key={b} value={b}>{b} kbps</option>)}</select></Field>
    </>)}
  </RuleCard>;
}

// ---------------------------------------------------------------- the member's files

/** A member's own files of one kind: add, listen to (music) and delete. */
export function LibraryFiles({ kind, library, onChange, onError, accept, noun, token }: {
  kind: LibraryKind; library: Library | null; onChange: (library: Library) => void; onError: (reason: unknown) => void; accept: string; noun: string; token?: string;
}) {
  const picker = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [playing, setPlaying] = useState<number | null>(null);
  const items = library?.items ?? [];
  const full = !!library && items.length >= library.limit;
  const upload = async (chosen: File[]) => {
    if (!library || chosen.length === 0) return;
    const room = library.limit - items.length;
    try {
      for (const [i, file] of chosen.slice(0, room).entries()) {
        if (file.size > library.max_bytes) throw new Error(`“${file.name}” is too large. The limit is ${Math.round(library.max_bytes / 1_000_000)} MB a file.`);
        setBusy(chosen.length > 1 ? `${i + 1} of ${Math.min(chosen.length, room)}` : "…");
        onChange(await libraryApi.upload(kind, file));
      }
      if (chosen.length > room) throw new Error(`Only ${room} more ${noun}${room === 1 ? "" : "s"} fitted: your library holds ${library.limit} at most.`);
    } catch (reason) {
      onError(reason);
    } finally {
      setBusy(null);
      if (picker.current) picker.current.value = "";
    }
  };
  const remove = async (id: number, name: string) => {
    if (!window.confirm(`Delete “${name}” from your library?`)) return;
    try {
      if (playing === id) setPlaying(null);
      onChange(await libraryApi.remove(kind, id));
    } catch (reason) {
      onError(reason);
    }
  };
  return <div className="library">
    <div className="library-head"><input ref={picker} type="file" accept={accept} multiple hidden onChange={e => void upload([...(e.target.files ?? [])])}/>
      <Button disabled={!library || full || busy !== null} onClick={() => picker.current?.click()}>{busy ? `Uploading ${busy}` : `Upload ${noun}s`}</Button>
      <span>{library ? `${items.length} of ${library.limit} ${noun}s · up to ${Math.round(library.max_bytes / 1_000_000)} MB each` : "Loading…"}</span></div>
    {items.length > 0 && <ul className="library-list">{items.map((item, i) => <li key={item.id}>
      <span className="muted">{i + 1}</span><span className="library-name" title={item.name}>{item.name}</span>
      {library?.next_id === item.id && <span className="library-next">Next</span>}
      <span className="muted">{item.type.toUpperCase()} · {formatBytes(item.bytes)}</span>
      {kind === "music" && token && <button type="button" className="link-button" onClick={() => setPlaying(playing === item.id ? null : item.id)}>{playing === item.id ? "Stop" : "Play"}</button>}
      <button type="button" className="link-button danger" onClick={() => void remove(item.id, item.name)}>Delete</button>
    </li>)}</ul>}
    {playing !== null && token && <audio src={libraryApi.fileUrl("music", playing, token)} controls autoPlay onEnded={() => setPlaying(null)}/>}
  </div>;
}

// ---------------------------------------------------------------- Background music

export function MusicCard({ look, onChange, onReset, library, onLibrary, onError, token }: CardProps & { library: Library | null; onLibrary: (l: Library) => void; onError: (reason: unknown) => void; token?: string }) {
  const { music } = look;
  return <RuleCard title="Background music" desc="Add a track from your own library under every clip." onReset={onReset}>
    <Field label="Add background music" hint="Each clip gets the next track in your library: 1, 2, 3 and so on, then back to the first.">
      <Toggle checked={music.enabled} label="Add background music" onChange={() => onChange(patch(look, "music", { enabled: !music.enabled }))}/></Field>
    {music.enabled && <Field label="Music volume" hint="How loud the music is under the video’s own sound. Around 20–30% keeps voices clear.">
      <Range min={2} max={100} value={Math.round(music.volume * 100)} readout={`${Math.round(music.volume * 100)}%`} onChange={v => onChange(patch(look, "music", { volume: v / 100 }))}/></Field>}
    {music.enabled && library && library.items.length === 0 && <div className="form-note warn">Your library has no tracks yet, so clips are made without music. Upload some below.</div>}
    <Field label="Your music library" hint="MP3, M4A, WAV or OGG. Use music you have the right to post: a network can mute or remove a clip with copyrighted music.">
      <LibraryFiles kind="music" library={library} onChange={onLibrary} onError={onError} accept=".mp3,.m4a,.wav,.ogg,audio/*" noun="track" token={token}/></Field>
  </RuleCard>;
}

// ---------------------------------------------------------------- Hook text

export function HookCard({ look, onChange, onReset, fonts, onFonts, onError, fontAvailable }: CardProps & { fonts: Library | null; onFonts: (l: Library) => void; onError: (reason: unknown) => void; fontAvailable: boolean }) {
  const { hook } = look;
  const { box } = hook;
  const set = (changes: Partial<Look["hook"]>) => onChange(patch(look, "hook", changes));
  const setBox = (changes: Partial<Look["hook"]["box"]>) => onChange(patchBox(look, changes));
  const percent = (label: string, value: number, change: (v: number) => void, min = 0, max = 100) =>
    <Field label={label}><Range min={min} max={max} value={Math.round(value)} readout={`${Math.round(value)}%`} onChange={change}/></Field>;
  const fontOptions = [
    { value: "default", label: "Default (bold)" },
    ...(fonts?.items ?? []).map(f => ({ value: `custom:${f.id}`, label: f.name })),
    ...(hook.font !== "default" && fonts && !fonts.items.some(f => `custom:${f.id}` === hook.font) ? [{ value: hook.font, label: "Deleted font — default is used" }] : []),
  ];
  return <RuleCard title="Hook text" desc="A short line on screen at the start of the clip, to stop people scrolling." onReset={onReset}>
    <Field label="Show hook text"><Toggle checked={hook.enabled} label="Show hook text" onChange={() => set({ enabled: !hook.enabled })}/></Field>
    {hook.enabled && <>
      {!fontAvailable && hook.font === "default" && <div className="form-note warn">No bold font was found on the server, so the hook text is left out of clips. Upload a font below, or set FONT_FILE on the server.</div>}
      {grid(<>
        <Field label="Words" hint="The AI hook needs an AI model (Settings → AI models). Without one, the title is shown.">
          <select value={hook.source} onChange={e => set({ source: e.target.value as Look["hook"]["source"] })}><option value="ai">Hook written by AI from the title</option><option value="title">The video’s own title</option></select></Field>
        <Field label="Stays on screen for"><NumberInput min={1} max={10} step={0.5} suffix="sec" value={hook.duration} onChange={duration => set({ duration })}/></Field>
      </>)}
      <h3 className="rule-heading">Text</h3>
      {grid(<>
        <Field label="Font"><select value={hook.font} onChange={e => set({ font: e.target.value })}>{fontOptions.map(f => <option key={f.value} value={f.value}>{f.label}</option>)}</select></Field>
        <Field label="Font size" hint="Measured on a Full HD clip; it keeps the same share of the picture at HD."><NumberInput min={16} max={160} suffix="px" value={hook.font_size} onChange={font_size => set({ font_size })}/></Field>
        <Field label="Text colour"><ColorInput value={hook.color} onChange={color => set({ color })}/></Field>
        <Field label="Outline colour"><ColorInput value={hook.stroke_color} onChange={stroke_color => set({ stroke_color })}/></Field>
        <Field label="Outline width" hint="0 for no outline."><NumberInput min={0} max={12} suffix="px" value={hook.stroke_width} onChange={stroke_width => set({ stroke_width })}/></Field>
      </>)}
      {grid(<>
        {percent("Text position · left to right", hook.x, x => set({ x }))}
        {percent("Text position · top to bottom", hook.y, y => set({ y }))}
      </>)}
      <h3 className="rule-heading">Background behind the text</h3>
      <Field label="Show a background"><Toggle checked={box.enabled} label="Show a background" onChange={() => setBox({ enabled: !box.enabled })}/></Field>
      {box.enabled && <>
        {grid(<>
          <Field label="Background colour"><ColorInput value={box.color} onChange={color => setBox({ color })}/></Field>
          {percent("Opacity", box.opacity * 100, v => setBox({ opacity: v / 100 }))}
          {percent("Width", box.width, width => setBox({ width }), 10)}
          {percent("Height", box.height, height => setBox({ height }), 3, 60)}
          {percent("Roundness", box.radius, radius => setBox({ radius }))}
        </>)}
        {grid(<>
          {percent("Background position · left to right", box.x, x => setBox({ x }))}
          {percent("Background position · top to bottom", box.y, y => setBox({ y }))}
        </>)}
        <button type="button" className="link-button" style={{ justifySelf: "start" }} onClick={() => setBox({ x: hook.x, y: hook.y })}>Centre the background on the text</button>
      </>}
      <h3 className="rule-heading">Your fonts</h3>
      <LibraryFiles kind="fonts" library={fonts} onChange={onFonts} onError={onError} accept=".ttf,.otf" noun="font"/>
      <small className="muted">TTF or OTF. An uploaded font appears in the Font list above.</small>
    </>}
  </RuleCard>;
}

// ---------------------------------------------------------------- Watermark

const PLACE_NAMES: Record<WatermarkPlace, string> = {
  tl: "Top left", tc: "Top centre", tr: "Top right", ml: "Middle left", mc: "Centre", mr: "Middle right", bl: "Bottom left", bc: "Bottom centre", br: "Bottom right",
};

export function WatermarkCard({ look, onChange, onReset, file, onFile, onError, token }: CardProps & { file: Library | null; onFile: (l: Library) => void; onError: (reason: unknown) => void; token?: string }) {
  const picker = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const wm = look.watermark;
  const image = file?.items[0];
  const set = (changes: Partial<Look["watermark"]>) => onChange(patch(look, "watermark", changes));
  const run = async (work: () => Promise<Library>) => {
    setBusy(true);
    try {
      onFile(await work());
    } catch (reason) {
      onError(reason);
    } finally {
      setBusy(false);
      if (picker.current) picker.current.value = "";
    }
  };
  const upload = (chosen: File | undefined) => {
    if (!chosen) return;
    if (chosen.type !== "image/png") return onError(new Error("Upload a PNG image."));
    if (chosen.size > 2_000_000) return onError(new Error("That file is too large. The limit is 2 MB."));
    void run(() => libraryApi.upload("watermark", chosen));
  };
  return <RuleCard title="Watermark (optional)" desc="Add consistent branding to every clip." onReset={onReset}>
    <div className="watermark-grid">
      <div><input ref={picker} type="file" accept="image/png" hidden onChange={e => upload(e.target.files?.[0])}/>
        <button type="button" className={`watermark-slot${image ? " filled" : ""}`} disabled={busy} onClick={() => picker.current?.click()}>
          {image ? <>{token && <img src={libraryApi.fileUrl("watermark", image.id, token)} alt="Watermark"/>}<b>{image.width && image.height ? `${image.width} × ${image.height} · ` : ""}{formatBytes(image.bytes)}</b><small>{busy ? "Working…" : "Replace PNG"}</small></>
            : <><b>{busy ? "Uploading…" : "Upload PNG"}</b><small>Transparent background recommended · up to 2 MB</small></>}
        </button>
        {image && <button type="button" className="link-button danger" disabled={busy} onClick={() => { set({ enabled: false }); void run(() => libraryApi.remove("watermark", image.id)); }}>Remove image</button>}
      </div>
      {image && <div className="watermark-settings">
        <Field label="Show on clips"><Toggle checked={wm.enabled} label="Show the watermark on clips" onChange={() => set({ enabled: !wm.enabled })}/></Field>
        {wm.enabled && <div className="watermark-controls">
          <div className="place-grid" role="radiogroup" aria-label="Watermark position">{WATERMARK_PLACES.map(p => <button type="button" role="radio" key={p} aria-checked={wm.position === p} title={PLACE_NAMES[p]} aria-label={PLACE_NAMES[p]} className={wm.position === p ? "active" : ""} onClick={() => set({ position: p })}/>)}</div>
          <div>
            <Field label="Opacity"><Range min={10} max={100} value={Math.round(wm.opacity * 100)} readout={`${Math.round(wm.opacity * 100)}%`} onChange={v => set({ opacity: v / 100 })}/></Field>
            <Field label="Size" hint="Width, as a share of the clip’s width."><NumberInput min={5} max={40} suffix="%" value={wm.size} onChange={size => set({ size })}/></Field>
          </div>
        </div>}
      </div>}
    </div>
  </RuleCard>;
}
