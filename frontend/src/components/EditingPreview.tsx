import { useEffect, useId, useRef, useState, type CSSProperties, type FormEvent } from "react";
import { PlanTag } from "@/components/PlanTag";
import { useQuery } from "@tanstack/react-query";
import { auth, editing, library as libraryApi } from "@/api/endpoints";
import type { Library, TestRender } from "@/api/types";
import { Field, Modal } from "@/components/Modal";
import { Button } from "@/components/ui";
import { adjustTables, aspectParts, formatBytes, hookBoxSize, hookFontSize, hookLineHeight, hookScale, lookChips, outputSize, wrapHookText, type Look } from "@/lib/look";

const PHOTOS = ["/assets/editing-sample-1.jpg", "/assets/editing-sample-2.jpg", "/assets/editing-sample-3.jpg"];
const PICKED_KEY = "cliprelay.editing.photo";
const OWN_KEY = "cliprelay.editing.own-photo";
const OWN_SIZE = 900;  // the viewer's own photo is shrunk to this width before it is kept in the browser
const CROP_X = { left: 0, centre: 50, right: 100 };
const SAMPLE_WORDS = { ai: "This one small habit changed everything", title: "The video’s title appears here" };

/** Loads a member's uploaded font into the page and returns the name to use it by, once it is ready. */
function useCustomFont(font: string, token?: string) {
  const id = /^custom:(\d+)$/.exec(font)?.[1];
  const [ready, setReady] = useState<string | null>(null);
  useEffect(() => {
    if (!id || !token) return;
    const family = `cliprelay-font-${id}`;
    let current = true;
    const face = new FontFace(family, `url(${libraryApi.fileUrl("fonts", Number(id), token)})`);
    face.load().then(() => { document.fonts.add(face); if (current) setReady(family); }, () => {});  // a font that cannot be read: the default is used, as in the render
    return () => { current = false; };
  }, [id, token]);
  return id && ready === `cliprelay-font-${id}` ? ready : null;
}

/** Where the watermark sits, with the same 40-pixel margin as the render, scaled to the frame. */
function watermarkStyle(look: Look): CSSProperties {
  const { position, size, opacity } = look.watermark;
  const [width, height] = outputSize(look);
  const x = `${(40 / width) * 100}%`;
  const y = `${(40 / height) * 100}%`;
  return {
    width: `${size}%`, opacity,
    ...(position[1] === "l" ? { left: x } : position[1] === "r" ? { right: x } : { left: "50%", translate: "-50% 0" }),
    ...(position[0] === "t" ? { top: y } : position[0] === "b" ? { bottom: y } : { top: "50%", translate: position[1] === "c" ? "-50% -50%" : "0 -50%" }),
  };
}

/** An illustration of the look on a sample photo: shape, crop, zoom, flip, hook text, its background and the watermark. */
export function LookFrame({ look, watermark, token, photo, className = "" }: { look: Look; watermark: Library | null; token?: string; photo: string; className?: string }) {
  const { aspect, position, zoom, flip } = look.frame;
  const { hook } = look;
  const [w, h] = aspectParts(aspect);
  const [width] = outputSize(look);
  // Sizes in pixels are drawn relative to the clip's width, so they scale with the frame.
  const scaled = (pixels: number) => `${(pixels / width) * 100}cqw`;
  const family = useCustomFont(hook.font, token);
  const box = hookBoxSize(look);
  const size = hookFontSize(look);
  const image = watermark?.items[0];
  const a = look.adjust;
  const tables = adjustTables(a);
  const filterId = `look-adjust-${useId().replace(/:/g, "")}`;
  return <div className={`look-frame ${className}`} style={{ aspectRatio: `${w} / ${h}`, ["--ar" as string]: w / h } as CSSProperties}>
    {/* The same tone curve, colour balance, saturation and hue as the render, as an SVG filter on the photo. */}
    <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true"><filter id={filterId} colorInterpolationFilters="sRGB">
      <feColorMatrix type="saturate" values={String(Math.max(0, 1 + a.saturation / 100))}/>
      <feComponentTransfer><feFuncR type="table" tableValues={tables.r}/><feFuncG type="table" tableValues={tables.g}/><feFuncB type="table" tableValues={tables.b}/></feComponentTransfer>
      <feColorMatrix type="hueRotate" values={String(a.hue)}/>
    </filter></svg>
    <i className="look-photo" style={{ backgroundImage: `url(${photo})`, backgroundPosition: `${CROP_X[position]}% 50%`, transform: `scale(${flip ? -zoom : zoom}, ${zoom})`, filter: `url(#${filterId})` }}/>
    {a.vignette > 0 && <i className="look-vignette" style={{ background: `radial-gradient(ellipse at center, transparent ${Math.round(70 - a.vignette * 0.35)}%, rgba(0, 0, 0, ${(a.vignette / 100) * 0.85}) 100%)` }}/>}
    {a.grain > 0 && <i className="look-grain" style={{ opacity: (a.grain / 100) * 0.45 }}/>}
    {hook.enabled && hook.box.enabled && <i className="look-box" style={{ left: `${hook.box.x}%`, top: `${hook.box.y}%`, width: `${hook.box.width}%`, height: `${hook.box.height}%`, backgroundColor: hook.box.color, opacity: hook.box.opacity, borderRadius: scaled(box.radius) }}/>}
    {hook.enabled && <span className="look-hook" style={{
      left: `${hook.x}%`, top: `${hook.y}%`, fontFamily: family ? `"${family}"` : undefined, fontWeight: family ? "normal" : undefined,
      fontSize: scaled(size), lineHeight: scaled(hookLineHeight(size)), color: hook.color,
      // The render draws the outline outside the letters; drawn first and twice as wide, it looks the same here.
      WebkitTextStroke: hook.stroke_width > 0 ? `${scaled(hook.stroke_width * hookScale(look) * 2)} ${hook.stroke_color}` : undefined, paintOrder: "stroke fill",
    }}>{wrapHookText(SAMPLE_WORDS[hook.source], look)}</span>}
    {look.watermark.enabled && image && token && <img className="look-mark" style={watermarkStyle(look)} src={libraryApi.fileUrl("watermark", image.id, token)} alt=""/>}
  </div>;
}

const read = (key: string) => {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
};
const keep = (key: string, value: string | null) => {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
    return true;
  } catch {
    return false;  // storage blocked or full: the photo still shows until the page is left
  }
};

/** A picked image shrunk to OWN_SIZE wide, as a JPEG data URL small enough to keep in the browser. */
function shrink(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const scale = Math.min(1, OWN_SIZE / img.naturalWidth);
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(img.naturalWidth * scale);
      canvas.height = Math.round(img.naturalHeight * scale);
      canvas.getContext("2d")!.drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      resolve(canvas.toDataURL("image/jpeg", 0.85));
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("That file could not be opened as an image.")); };
    img.src = url;
  });
}

/** The sample photos, plus the viewer's own; the choice is remembered in this browser only. */
function usePreviewPhoto() {
  const [own, setOwn] = useState<string | null>(() => read(OWN_KEY));
  const [picked, setPicked] = useState<string>(() => read(PICKED_KEY) ?? "0");
  const choose = (value: string) => { setPicked(value); keep(PICKED_KEY, value); };
  const upload = async (file: File) => {
    const data = await shrink(file);
    setOwn(data);
    keep(OWN_KEY, data);
    choose("own");
  };
  const removeOwn = () => { setOwn(null); keep(OWN_KEY, null); choose("0"); };
  const photo = picked === "own" && own ? own : PHOTOS[Number(picked)] ?? PHOTOS[0];
  return { photo, picked: picked === "own" && !own ? "0" : picked, own, choose, upload, removeOwn };
}

/** The panel beside the rules: the illustrated look, its summary, an estimate and the real test. */
export function EditingPreview({ look, watermark, token, rendered, onTest }: { look: Look; watermark: Library | null; token?: string; rendered: number; onTest: () => void }) {
  const [w, h] = outputSize(look);
  const { photo, picked, own, choose, upload, removeOwn } = usePreviewPhoto();
  const picker = useRef<HTMLInputElement>(null);
  const [photoError, setPhotoError] = useState<string | null>(null);
  const pick = (file: File | undefined) => {
    if (picker.current) picker.current.value = "";
    if (!file) return;
    if (!file.type.startsWith("image/")) return setPhotoError("Choose a picture file (JPG, PNG or WebP).");
    setPhotoError(null);
    upload(file).catch(reason => setPhotoError(reason instanceof Error ? reason.message : String(reason)));
  };
  return <aside className="card editing-preview">
    <LookFrame look={look} watermark={watermark} token={token} photo={photo} className={w < h ? "narrow" : ""}/>
    <div className="preview-photos" role="radiogroup" aria-label="Preview photo">
      {PHOTOS.map((src, i) => <button type="button" role="radio" key={src} aria-checked={picked === String(i)} aria-label={`Sample photo ${i + 1}`} className={picked === String(i) ? "active" : ""} style={{ backgroundImage: `url(${src})` }} onClick={() => choose(String(i))}/>)}
      {own && <button type="button" role="radio" aria-checked={picked === "own"} aria-label="Your photo" className={picked === "own" ? "active" : ""} style={{ backgroundImage: `url(${own})` }} onClick={() => choose("own")}/>}
      <input ref={picker} type="file" accept="image/*" hidden onChange={e => pick(e.target.files?.[0])}/>
      <button type="button" className="add" title="Use your own photo for the preview" aria-label="Use your own photo" onClick={() => picker.current?.click()}>+</button>
    </div>
    <div className="preview-photo-actions">
      <button type="button" className="link-button" onClick={() => picker.current?.click()}>{own ? "Use another photo of your own" : "Use your own photo"}</button>
      {own && <button type="button" className="link-button danger" onClick={removeOwn}>Remove it</button>}
    </div>
    {photoError && <small className="bad">{photoError}</small>}
    <small className="muted">Illustration on a photo; your own stays in this browser only. Use the test below to see a real clip.</small>
    <div className="spec-chips">{lookChips(look).map(item => <span key={item}>{item}</span>)}</div>
    <div className="preview-estimate"><span className="muted">Output</span><b>{w} × {h} · {look.encoding.fps} fps · CRF {look.encoding.crf}</b>
      <small className="muted">{rendered ? `${rendered} clip${rendered === 1 ? " was" : "s were"} rendered in the last 24 hours.` : "No clips have been rendered in the last 24 hours yet."}</small></div>
    <Button variant="primary" onClick={onTest}>Test on a real video <PlanTag feature="test_render"/></Button>
  </aside>;
}

const NOTES: Record<string, string> = { hook_font_missing: "The hook text was left out: no bold font was found on the server. Upload a font in Hook text, or set FONT_FILE on the server." };

/** Renders the first 20 seconds of a real YouTube video with the rules on screen, and plays the result. */
export function TestRenderModal({ look, onSave, onClose }: { look: Look; onSave?: () => void; onClose: () => void }) {
  const [url, setUrl] = useState("");
  const [test, setTest] = useState<TestRender | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [copied, setCopied] = useState(false);
  const token = useQuery({ queryKey: ["media-token"], queryFn: auth.mediaToken, staleTime: 60 * 60_000 }).data?.token;
  const running = test?.status === "running";
  const testId = test?.id;
  useEffect(() => {
    if (!running || !testId) return;
    const started = Date.now();
    const timer = setInterval(() => {
      setElapsed(Math.round((Date.now() - started) / 1000));
      void editing.test(testId).then(setTest, reason => { setTest(null); setError(reason instanceof Error ? reason.message : String(reason)); });
    }, 1500);
    return () => clearInterval(timer);
  }, [running, testId]);
  const start = async (event?: FormEvent) => {
    event?.preventDefault();
    if (running || !url.trim()) return;
    setError(null);
    setElapsed(0);
    setCopied(false);
    try {
      setTest(await editing.startTest(url.trim(), look));
    } catch (reason) {
      setTest(null);
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };
  const failure = test?.status === "failed" ? test.message ?? "The test render failed." : error;
  const copy = (text: string) => void navigator.clipboard.writeText(text).then(() => setCopied(true), () => {});
  return <Modal className="wide" title="Test on a real video" caption="Renders the start of a real YouTube video with the rules on screen, saved or not." onClose={onClose}
    footer={<><Button onClick={onClose}>{test?.status === "done" ? "Close" : "Cancel"}</Button>
      {test?.status === "done" && onSave && <Button onClick={() => { onSave(); onClose(); }}>Save these rules</Button>}
      <Button variant="primary" disabled={running || !url.trim()} onClick={() => void start()}>{running ? "Rendering…" : test ? "Render again" : "Render now"}</Button></>}>
    <form onSubmit={e => void start(e)}><Field label="YouTube video link" hint="Only the first 20 seconds of the clip are rendered, so the test stays quick.">
      <input autoFocus value={url} placeholder="https://www.youtube.com/watch?v=…" spellCheck={false} disabled={running} onChange={e => setUrl(e.target.value)}/></Field></form>
    <div className="spec-chips">{lookChips(look).map(item => <span key={item}>{item}</span>)}</div>
    {running && <div className="test-running" role="status"><div><span>{test.stage ?? "Working"}…</span><b>{elapsed}s</b></div><div className="status-bar"><i className="primary pulse" style={{ width: "40%" }}/></div>{test.title && <small className="muted">{test.title}</small>}</div>}
    {test?.status === "done" && token && <>
      <video className="test-video" src={editing.previewUrl(test.id, token)} controls autoPlay loop playsInline/>
      <div className="spec-chips">{[`${(test.seconds ?? 0).toFixed(1)}s clip`, formatBytes(test.bytes ?? 0), `rendered in ${test.render_seconds ?? 0}s`, ...(test.vertical ? ["vertical source — not cropped"] : []), ...(test.music ? [`music: ${test.music}`] : []), ...(test.hook ? [`hook: “${test.hook}”`] : [])].map(item => <span key={item}>{item}</span>)}</div>
      {test.note && <div className="form-note warn">{NOTES[test.note] ?? test.note}</div>}
      {test.command && <details className="test-command"><summary>FFmpeg command used</summary><code>{test.command}</code>
        <button type="button" className="link-button" onClick={() => copy(test.command!)}>{copied ? "Copied" : "Copy command"}</button></details>}
    </>}
    {failure && <div className="form-error test-failure"><code>{failure}</code><button type="button" className="link-button" onClick={() => copy(failure)}>{copied ? "Copied" : "Copy error"}</button></div>}
  </Modal>;
}
