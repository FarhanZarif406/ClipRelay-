/** Editing look: everything that decides how a clip looks and sounds. Mirrors app/services/looks.py and media.py. */

export const ASPECTS = ["9:16", "4:5", "3:4", "2:3", "1:1", "4:3", "3:2", "16:9", "21:9"] as const;
export type Aspect = (typeof ASPECTS)[number];
export const ASPECT_NAMES: Record<Aspect, string> = {
  "9:16": "Vertical · TikTok, Reels, Shorts",
  "4:5": "Portrait · Instagram feed",
  "3:4": "Portrait",
  "2:3": "Portrait · Pinterest",
  "1:1": "Square",
  "4:3": "Classic landscape",
  "3:2": "Landscape",
  "16:9": "Widescreen · YouTube",
  "21:9": "Cinema wide",
};
export const ENCODER_PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"] as const;
export const FRAME_RATES = [24, 25, 30, 60] as const;
export const AUDIO_BITRATES = [96, 128, 192] as const;
export const WATERMARK_PLACES = ["tl", "tc", "tr", "ml", "mc", "mr", "bl", "bc", "br"] as const;
export type WatermarkPlace = (typeof WATERMARK_PLACES)[number];

export type Look = {
  frame: { aspect: Aspect; position: "left" | "centre" | "right"; zoom: number; flip: boolean };
  speed: { speed: number; keep_pitch: boolean };
  encoding: { resolution: "1080x1920" | "720x1280"; fps: (typeof FRAME_RATES)[number]; preset: (typeof ENCODER_PRESETS)[number]; crf: number; loudnorm: boolean; audio_bitrate: (typeof AUDIO_BITRATES)[number]; keep_audio: boolean };
  music: { enabled: boolean; volume: number };
  hook: {
    enabled: boolean; source: "ai" | "title"; duration: number; font: string; font_size: number;
    color: string; stroke_color: string; stroke_width: number; x: number; y: number;
    box: { enabled: boolean; color: string; opacity: number; width: number; height: number; radius: number; x: number; y: number };
  };
  watermark: { enabled: boolean; position: WatermarkPlace; opacity: number; size: number };
  /** Light, colour and detail. 0 leaves the picture as it is. */
  adjust: Record<AdjustKey, number>;
};

/** Every adjustment: its range, and which group of the Adjust card it is in. */
export const ADJUSTMENTS = [
  { key: "brightness", label: "Brightness", min: -100, max: 100, group: "Light" },
  { key: "contrast", label: "Contrast", min: -100, max: 100, group: "Light" },
  { key: "highlights", label: "Highlights", min: -100, max: 100, group: "Light" },
  { key: "shadows", label: "Shadows", min: -100, max: 100, group: "Light" },
  { key: "saturation", label: "Saturation", min: -100, max: 100, group: "Colour" },
  { key: "warmth", label: "Warmth", min: -100, max: 100, group: "Colour" },
  { key: "tint", label: "Tint", min: -100, max: 100, group: "Colour" },
  { key: "hue", label: "Hue", min: -180, max: 180, group: "Colour" },
  { key: "sharpness", label: "Sharpness", min: 0, max: 100, group: "Detail" },
  { key: "vignette", label: "Vignette", min: 0, max: 100, group: "Detail" },
  { key: "grain", label: "Grain", min: 0, max: 100, group: "Detail" },
] as const;
export type AdjustKey = (typeof ADJUSTMENTS)[number]["key"];

/**
 * The tone curve the render applies (eq brightness and contrast, then the shadows and highlights curve),
 * sampled for the preview, with warmth and tint as the colour balance shifts of the midtones.
 */
export function adjustTables(a: Look["adjust"]) {
  const brightness = (a.brightness / 100) * 0.3;
  const contrast = 1 + (a.contrast / 100) * 0.5;
  const low = Math.min(1, Math.max(0, 0.25 + (a.shadows / 100) * 0.15));
  const high = Math.min(1, Math.max(0, 0.75 + (a.highlights / 100) * 0.15));
  const curve = (x: number) => (x < 0.25 ? (x / 0.25) * low : x < 0.75 ? low + ((x - 0.25) / 0.5) * (high - low) : high + ((x - 0.75) / 0.25) * (1 - high));
  const warm = (a.warmth / 100) * 0.3;
  const tint = (a.tint / 100) * 0.3;
  const clamp = (v: number) => Math.min(1, Math.max(0, v));
  const steps = Array.from({ length: 17 }, (_, i) => i / 16);
  const tone = (x: number) => clamp(curve(clamp((x - 0.5) * contrast + 0.5 + brightness)));
  const mid = (x: number) => 4 * x * (1 - x);  // colour balance moves the midtones most
  const table = (shift: number) => steps.map(x => clamp(tone(x) + shift * mid(tone(x))).toFixed(3)).join(" ");
  return { r: table(warm), g: table(-tint), b: table(-warm) };
}
export const adjusted = (a: Look["adjust"]) => Object.values(a).some(v => v !== 0);

/** Change one section of a look. */
export function patch<K extends keyof Look>(look: Look, section: K, changes: Partial<Look[K]>): Look {
  return { ...look, [section]: { ...look[section], ...changes } };
}
export const patchBox = (look: Look, changes: Partial<Look["hook"]["box"]>): Look => patch(look, "hook", { box: { ...look.hook.box, ...changes } });

const even = (value: number) => Math.max(2, Math.round(value / 2) * 2);

export function aspectParts(aspect: string): [number, number] {
  const [w, h] = aspect.split(":").map(Number);
  return w > 0 && h > 0 ? [w, h] : [9, 16];
}

/** The finished clip's size: the quality sets the shorter side (1080 or 720), the aspect ratio the other. */
export function outputSize(look: Look): [number, number] {
  const short = Number(look.encoding.resolution.split("x")[0]) || 1080;
  const [w, h] = aspectParts(look.frame.aspect);
  return w <= h ? [short, even((short * h) / w)] : [even((short * w) / h), short];
}

/** How a source picture fits the clip's shape: its sides cropped, its ends cropped, or kept whole with bars. */
export function sourceFit(width: number, height: number, aspect: string): "sides" | "ends" | "whole" {
  const [w, h] = aspectParts(aspect);
  const ratio = width / height / (w / h);
  if (ratio > 1.01) return "sides";
  return ratio < 0.99 && ratio >= 0.7 ? "ends" : "whole";
}

export const hookScale = (look: Look) => (Number(look.encoding.resolution.split("x")[0]) || 1080) / 1080;
export const hookFontSize = (look: Look) => Math.max(8, Math.round(look.hook.font_size * hookScale(look)));
export const hookLineHeight = (size: number) => Math.round(size * 1.3);

export function hookBoxSize(look: Look) {
  const [width, height] = outputSize(look);
  const { box } = look.hook;
  const w = even((width * box.width) / 100);
  const h = even((height * box.height) / 100);
  return { w, h, radius: Math.round((Math.min(w, h) / 2) * (Math.min(100, Math.max(0, box.radius)) / 100)) };
}

/** Hook text in lines that fit, exactly as the render wraps it. */
export function wrapHookText(text: string, look: Look) {
  const [width] = outputSize(look);
  const size = hookFontSize(look);
  const room = look.hook.box.enabled ? (width * look.hook.box.width) / 100 - size : width * 0.86;
  const perLine = Math.max(6, Math.floor(room / (size * 0.56)));
  const lines: string[] = [];
  let line = "";
  for (const word of text.trim().split(/\s+/)) {
    if (line && `${line} ${word}`.length > perLine) {
      lines.push(line);
      line = word;
    } else line = line ? `${line} ${word}` : word;
  }
  if (line) lines.push(line);
  return lines.slice(0, 4).join("\n");
}

/** How many individual settings differ between two values of the same shape. */
export function countChanges(a: unknown, b: unknown): number {
  if (a && b && typeof a === "object" && typeof b === "object" && !Array.isArray(a) && !Array.isArray(b)) {
    const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
    let total = 0;
    for (const key of keys) total += countChanges((a as Record<string, unknown>)[key], (b as Record<string, unknown>)[key]);
    return total;
  }
  return JSON.stringify(a) === JSON.stringify(b) && !(typeof a === "number" && Number.isNaN(a)) ? 0 : 1;
}

export function formatBytes(bytes: number) {
  if (bytes >= 1_000_000) return `${Math.round(bytes / 100_000) / 10} MB`;
  return `${Math.max(1, Math.round(bytes / 1000))} KB`;
}

/** Rough file size of a clip: video bitrate from picture size, CRF and frame rate, plus audio. */
export function estimateBytes(look: Look, seconds: number) {
  const [width, height] = outputSize(look);
  const base = 3500 * ((width * height) / (1080 * 1920));
  const video = base * 2 ** ((23 - look.encoding.crf) / 6) * Math.sqrt(look.encoding.fps / 30);
  const audible = look.encoding.keep_audio || look.music.enabled;
  return Math.round(((video + (audible ? look.encoding.audio_bitrate : 64)) * 1000 * seconds) / 8);
}

/** One-line summary of a look, as chips. */
export function lookChips(look: Look): string[] {
  const { frame, speed, encoding } = look;
  return [
    frame.aspect,
    `crop ${frame.position}`,
    ...(frame.zoom > 1 ? [`zoom ${Math.round(frame.zoom * 100)}%`] : []),
    `${speed.speed.toFixed(2)}x`,
    ...(frame.flip ? ["flipped"] : []),
    outputSize(look).join("×"),
    `${encoding.fps}fps`,
    `CRF ${encoding.crf}`,
    ...(encoding.keep_audio ? [] : ["no original sound"]),
    ...(look.watermark.enabled ? ["watermark"] : []),
    ...(look.hook.enabled ? ["hook text"] : []),
    ...(look.music.enabled ? [`music ${Math.round(look.music.volume * 100)}%`] : []),
    ...(adjusted(look.adjust) ? ["adjusted"] : []),
  ];
}

export const capital = (text: string) => text[0].toUpperCase() + text.slice(1);
