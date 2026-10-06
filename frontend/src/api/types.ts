export type Tone = "success" | "warning" | "danger" | "primary" | "neutral";

export type User = { id: number; email: string; name: string; workspace_name: string; role: "owner" | "member"; created_at: string };

export type Ref = { id: number; username: string; color: string; initials: string; status?: string };

export type ActivityLog = {
  id: number;
  created_at: string;
  level: "info" | "warning" | "error";
  service: string;
  event: string;
  message: string;
  request_id: string;
  job_id: number | null;
  payload: Record<string, unknown> | null;
};

export type Video = {
  id: number;
  ig_media_id: string;
  permalink: string | null;
  thumbnail_url: string | null;
  posted_at: string | null;
  original_title: string;
  original_caption: string;
  original_tags: string[];
  duration_sec: number | null;
  detected_language: string | null;
  language_confidence: number | null;
  status: "fetched" | "accepted" | "rejected";
  rejection_reason: string | null;
  created_at: string;
  source: Ref | null;
  transcript?: string | null;
};

export type JobStatus =
  | "fetched" | "rewriting" | "awaiting_approval" | "ready" | "uploading" | "posted"
  | "monitoring" | "clean" | "violated" | "failed" | "cancelled";

export type Job = {
  id: number;
  status: JobStatus;
  created_at: string;
  updated_at: string;
  posted_at: string | null;
  approval_required: boolean;
  rewritten_title: string | null;
  rewritten_caption: string | null;
  rewritten_tags: string[];
  privacy_level: string | null;
  tiktok_post_id: string | null;
  error: string | null;
  violation_reason: string | null;
  check_count: number;
  next_check_at: string | null;
  monitor_until: string | null;
  prompt_template_id: number | null;
  video: Video;
  source: Ref | null;
  tiktok_account: Ref | null;
  events?: { id: number; status: JobStatus; message: string; created_at: string }[];
};

export type Kpi = { key: string; label: string; value: number; delta?: number | null; meta?: string; tone: Tone; series: number[] };

export type Summary = {
  kpis: Kpi[];
  distribution: { published: number; pending: number; failed: number; removed: number };
  attention: { username: string; status: string; refresh_expires_at: string | null }[];
  unacknowledged_violations: number;
  recent_activity: ActivityLog[];
  next_run: { at: string | null; interval_minutes: number | null; paused: boolean; active_sources: number; sources: Ref[] };
  rejections: { items: Video[]; removed_today: number; acceptance_rate: number | null; language_gate_enabled: boolean; allowed_languages: string[] };
  accounts: (Ref & { posts_today: number; lifetime_posts: number })[];
};

export type Nav = {
  pending_jobs: number;
  unacknowledged_violations: number;
  monthly_jobs: number;
  monthly_quota: number;
  reset_in_days: number;
  onboarding_completed: boolean;
  active_sources: number;
  tiktok_accounts: number;
};

export type Source = Ref & {
  name: string | null;
  profile_picture_url: string | null;
  is_active: boolean;
  refresh_interval_minutes: number;
  next_run_at: string | null;
  last_checked_at: string | null;
  last_run_status: string | null;
  last_error: string | null;
  approval_mode: "auto" | "manual";
  prompt_template_id: number | null;
  prompt_template_name: string | null;
  videos_found: number;
  token_expires_at: string | null;
  needs_reconnect: boolean;
  tiktok_accounts: Ref[];
};

export type TikTokAccount = Ref & {
  status: "active" | "expiring" | "expired" | "revoked";
  display_name: string | null;
  avatar_url: string | null;
  daily_cap: number;
  default_privacy: string;
  token_expires_at: string | null;
  refresh_expires_at: string | null;
  last_error: string | null;
  last_posted_at: string | null;
  created_at: string;
  sources: Ref[];
  posts_today: number;
  failed_today: number;
  lifetime_posts: number;
  violations: number;
};

export type Violation = {
  id: number;
  job_id: number;
  reason: string;
  removal_status: string;
  acknowledged: boolean;
  detected_at: string;
  tiktok_account: Ref | null;
  title: string;
};

export type Prompt = {
  id: number;
  name: string;
  description: string;
  niche: string;
  title_prompt: string;
  caption_prompt: string;
  hashtags_prompt: string;
  is_default: boolean;
  is_enabled: boolean;
  created_at: string;
  updated_at: string;
};

export type Policy = {
  automations_paused: boolean;
  name: string;
  active_window_start: string;
  active_window_end: string;
  active_days: number[];
  max_duration_sec: number;
  language_gate_enabled: boolean;
  allowed_languages: string[];
  hourly_cap: number;
  random_delay_min_minutes: number;
  random_delay_max_minutes: number;
  timezone: string;
  unique_video_per_account: boolean;
  default_interval_minutes: number;
  max_videos_per_run: number;
  tiktok_app_audited: boolean;
};

export type AuditSettings = { check_hours: number[]; auto_remove: boolean; notifications_enabled: boolean };
export type NotificationSettings = { webhook_url: string; email: string; notify_violations: boolean; notify_failures: boolean; notify_tokens: boolean };

export type AuditItem = Job & {
  display_status: "Checking" | "Warning" | "Clear" | "Violation";
  elapsed_hours: number;
  hours_left: number;
  progress: number;
  checkpoints: { label: string; hours: number; done: boolean }[];
};

export type DailyReport = {
  date: string;
  uploaded: number;
  failed: number;
  accounts: (Ref & { sources: number; posts_today: number; failed_today: number; lifetime_posts: number })[];
  active_accounts: number;
  lifetime_uploads: number;
  accepted: number;
  accepted_by_language: Record<string, number>;
  filtered_out: number;
  hourly: { hour: number; published: number; failed: number }[];
};

export type Integration = { key: string; name: string; masked: string; configured: boolean; source: "app" | "env" | null };

export type LLMProviderName = "anthropic" | "openai" | "gemini" | "openrouter" | "groq" | "mistral" | "custom";
export type LLMProvider = {
  id: number;
  label: string;
  provider: LLMProviderName;
  model: string;
  base_url: string | null;
  max_tokens: number;
  temperature: number | null;
  is_default: boolean;
  status: "unverified" | "valid" | "invalid";
  last_error: string | null;
  last_tested_at: string | null;
  updated_at: string;
  masked_key?: string;
};
export type LLMProviderList = { items: LLMProvider[]; providers: LLMProviderName[]; env_fallback: { configured: boolean; provider: string | null; model: string | null; active: boolean } };

export type CredentialState = "none" | "env" | "unverified" | "valid" | "invalid";
export type CredentialField = { key: string; label: string; secret: boolean; configured: boolean; source: "app" | "env" | null; value?: string; masked?: string };
export type CredentialCard = {
  group: string;
  title: string;
  configured: boolean;
  state: CredentialState;
  connected_accounts: number;
  fields?: CredentialField[];
  last_error?: string | null;
  verified_at?: string | null;
  redirect_uri?: string | null;
  scopes?: string | null;
  docs_url?: string | null;
};
export type CredentialResult = { ok: boolean | null; message: string; card: CredentialCard };

export type Page<T> = { items: T[]; total: number };
