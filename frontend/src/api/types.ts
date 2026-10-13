export type Tone = "success" | "warning" | "danger" | "primary" | "neutral";

export type User = { id: number; email: string; name: string; workspace_name: string; role: "owner" | "member"; created_at: string; terms_accepted_at?: string | null };

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
  youtube_video_id: string | null;
  channel: ChannelRef | null;
  permalink: string | null;
  has_file: boolean;
  files_deleted_at: string | null;
  skip_reason: string | null;
  forced: boolean;
  mode: "shorts" | "podcasts";
  /** Set on a clip cut from a podcast. */
  clip: { start: number; end: number; podcast_id: number; podcast_title: string; podcast_url: string | null } | null;
  thumbnail_url: string | null;
  posted_at: string | null;
  original_title: string;
  original_caption: string;
  original_tags: string[];
  duration_sec: number | null;
  status: "fetched" | "accepted" | "skipped";
  rejection_reason: string | null;
  created_at: string;
};

export type JobStatus =
  | "fetched" | "downloading" | "rendering" | "rewriting" | "awaiting_approval" | "ready" | "uploading" | "posted"
  | "monitoring" | "clean" | "violated" | "failed" | "cancelled" | "clipped";

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
  caption_status: "pending" | "done" | "caption_fallback";
  caption_fallback: boolean;
  publish_mode: "inbox" | "direct" | null;
  reject_reason: string | null;
  waiting_for_account: boolean;
  tiktok_url: string | null;
  privacy_level: string | null;
  tiktok_post_id: string | null;
  error: string | null;
  violation_reason: string | null;
  check_count: number;
  next_check_at: string | null;
  monitor_until: string | null;
  prompt_template_id: number | null;
  video: Video;
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
  timezone: string;
  rejections: { items: Video[]; removed_today: number; acceptance_rate: number | null; max_duration_seconds: number | null; min_source_duration_seconds: number | null };
  accounts: (Ref & { posts_today: number; lifetime_posts: number })[];
};

export type Nav = {
  pending_jobs: number;
  unacknowledged_violations: number;
  failed_jobs: number;
  onboarding_completed: boolean;
  tiktok_accounts: number;
  review_jobs: number;
  skipped_videos: number;
  channels: number;
};

export type TikTokAccount = Ref & {
  status: "active" | "expiring" | "expired" | "revoked";
  display_name: string | null;
  avatar_url: string | null;
  daily_cap: number;
  daily_cap_override: number | null;
  default_privacy: string;
  token_expires_at: string | null;
  refresh_expires_at: string | null;
  last_error: string | null;
  last_posted_at: string | null;
  created_at: string;
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
  llm_provider_id: number | null;
  created_at: string;
  updated_at: string;
};

export type Policy = { tiktok_app_audited: boolean };

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
  timezone: string;
  uploaded: number;
  failed: number;
  accounts: (Ref & { posts_today: number; failed_today: number; lifetime_posts: number })[];
  active_accounts: number;
  lifetime_uploads: number;
  accepted: number;
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
export type CredentialField = { key: string; label: string; secret: boolean; configured: boolean; source: "app" | "env" | "default" | null; value?: string; masked?: string };
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

export type ChannelRef = { id: number; display_name: string; handle: string | null; thumbnail_url: string | null };
export type Channel = ChannelRef & {
  youtube_channel_id: string;
  url: string;
  active: boolean;
  default_tiktok_account: Ref | null;
  push_status: "subscribed" | "pending" | "expired" | "failed" | "unavailable" | "off";
  push_expires_at: string | null;
  push_error: string | null;
  last_checked_at: string | null;
  last_upload_at: string | null;
  last_error: string | null;
  created_at: string;
  videos_published: number;
  videos_detected: number;
  videos_skipped: number;
  override_count: number;
};
export type ChannelCard = { youtube_channel_id: string; display_name: string; handle: string | null; thumbnail_url: string | null; url: string; already_added: boolean; added_in: "shorts" | "podcasts" | null; added_by: string | null };

export type RuleValue = boolean | number | string;
export type RuleValues = Record<string, RuleValue>;
export type RuleDef = {
  key: string; kind: "float" | "int" | "bool" | "text" | "timezone" | "choice"; default: RuleValue; label: string; help: string; group: string;
  min: number | null; max: number | null; choices: string[]; per_channel: boolean;
};
export type RuleChange = { id: number; key: string; label: string; channel_id: number | null; channel_name: string | null; old_value: RuleValue | null; new_value: RuleValue | null; changed_by: string | null; changed_at: string };
export type ChannelRules = { overrides: RuleValues; effective: RuleValues; global: RuleValues };

export type StatusItem = {
  id: number; video_id: number; title: string; channel: string | null; thumbnail_url: string | null; permalink: string | null; duration_sec: number | null;
  progress: number | null; since: string; attempts: number; note: string | null; retry_at: string | null; podcast: boolean;
  clip: { start: number; end: number; podcast_title: string } | null; tiktok_account: Ref | null;
};
export type PipelineStatus = {
  mode: "shorts" | "podcasts"; timezone: string; podcasts_analysing: number;
  today: { total: number; downloaded: number; download_left: number; edited: number; edit_left: number; uploaded: number; upload_left: number; failed: number };
  stages: { key: string; label: string; total: number; items: StatusItem[] }[];
};

export type CookiesInfo = { present: boolean; count?: number; expires_at?: string | null; expired?: boolean; updated_at?: string };
export type SourceInfo = {
  installed: boolean; version: string | null; cookies: boolean; cookies_file: CookiesInfo;
  options: { proxy: string; proxy_set: boolean; player_client: string }; player_clients: string[];
  stats: { completed: number; failed_downloads: number }; working_route: string | null; js_runtime: string | null;
};
export type DiagnosisRow = { client: string; cookies: boolean; ipv6: boolean; ok: boolean; format: string | null; height: number | null; low: boolean; message: string };
export type SourceDiagnosis = {
  id: string; status: "running" | "done" | "failed"; stage: string | null; cookies: boolean; proxy: boolean; player_client: string;
  rows: DiagnosisRow[]; total: number; verdict?: string; version?: string | null; js_runtime?: string | null; verbose?: string; command?: string;
};
