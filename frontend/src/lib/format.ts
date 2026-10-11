import type { JobStatus, Tone } from "@/api/types";

export function relativeTime(iso: string | null | undefined, { suffix = false }: { suffix?: boolean } = {}): string {
  if (!iso) return "Never";
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  const future = seconds < 0;
  const s = Math.abs(seconds);
  let text: string;
  if (s < 45) text = future ? "in a moment" : "just now";
  else if (s < 3600) text = `${Math.round(s / 60)}m`;
  else if (s < 86400) text = `${Math.round(s / 3600)}h`;
  else if (s < 172800 && !future) return "Yesterday";
  else text = `${Math.round(s / 86400)}d`;
  if (text === "just now" || text === "in a moment") return text;
  return future ? `in ${text}` : suffix ? `${text} ago` : text;
}

export function longAgo(iso: string | null | undefined): string {
  const r = relativeTime(iso, { suffix: true });
  return r.replace(/(\d+)m ago/, (_, n) => `${n} min ago`).replace(/(\d+)h ago/, (_, n) => `${n} hour${n === "1" ? "" : "s"} ago`).replace(/(\d+)d ago/, (_, n) => `${n} days ago`);
}

export function duration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const s = Math.round(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function clock(iso: string): string {
  const d = new Date(iso);
  return `${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })}.${String(d.getMilliseconds()).padStart(3, "0")}`;
}

export function dayTime(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return sameDay ? `Today, ${time}` : `${d.toLocaleDateString([], { month: "short", day: "numeric" })}, ${time}`;
}

export const JOB_STATUS: Record<JobStatus, { label: string; tone: Tone }> = {
  fetched: { label: "Detected", tone: "neutral" },
  downloading: { label: "Downloading", tone: "primary" },
  rendering: { label: "Rendering", tone: "primary" },
  rewriting: { label: "Writing caption", tone: "primary" },
  awaiting_approval: { label: "Needs approval", tone: "warning" },
  ready: { label: "Ready", tone: "primary" },
  uploading: { label: "Uploading", tone: "primary" },
  posted: { label: "Posted", tone: "success" },
  monitoring: { label: "Monitoring", tone: "primary" },
  clean: { label: "Clean", tone: "success" },
  violated: { label: "Violated", tone: "danger" },
  failed: { label: "Failed", tone: "danger" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

export const ACCOUNT_STATUS: Record<string, { label: string; tone: Tone }> = {
  active: { label: "Active", tone: "success" },
  expiring: { label: "Expiring", tone: "warning" },
  expired: { label: "Expired", tone: "danger" },
  revoked: { label: "Disconnected", tone: "neutral" },
};

export const LANGUAGES: Record<string, string> = {
  hi: "Hindi", ur: "Urdu", en: "English", es: "Spanish", pt: "Portuguese", ja: "Japanese", ar: "Arabic", bn: "Bengali",
  fr: "French", de: "German", it: "Italian", tr: "Turkish", ru: "Russian", zh: "Chinese", ko: "Korean", id: "Indonesian", pa: "Punjabi",
};

export const languageName = (code: string | null | undefined) => (code ? LANGUAGES[code] ?? code.toUpperCase() : "—");

export const DAYS = ["M", "T", "W", "T", "F", "S", "S"];

export function greeting(): string {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

export function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? parts[0]?.[1] ?? "")).toUpperCase() || "?";
}

export const SKIP_REASON: Record<string, string> = {
  not_a_short: "Not a Short (long video)",
  too_long: "Too long",
  too_short: "Too short",
  skipped_channel_cap: "Channel daily cap",
  skipped_account_cap: "TikTok account daily cap",
  language: "Language",
};
