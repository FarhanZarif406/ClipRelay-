import { ApiError, api, apiUrl, getToken } from "./client";
import type { Look } from "@/lib/look";
import type {
  ActivityLog, Channel, ChannelRules, CredentialCard, CredentialResult, DailyReport, LLMProvider, LLMProviderList, LLMProviderName, Integration, Job, Nav, NotificationSettings, Page, Prompt,
  PipelineStatus, DailyLimit, SystemState, Account, AccountChanges, MyPlan, PlanInput, PlanList, EditingState, Library, Preset, TestRender, BufferChannelChanges, BufferChannelStatus, BufferStatus, PushInfo, HelperPage, CloudEditing, YouTubeApiInfo, YouTubeApiTest, SourceDiagnosis, SourceInfo, CookiesInfo, RuleChange, RuleDef, RuleValue, RuleValues, Summary, User, Video,
} from "./types";

export const auth = {
  setup: () => api<{ has_users: boolean; registration_open: boolean }>("/auth/setup"),
  login: (email: string, password: string, accept_terms = false) => api<{ access_token: string; user: User }>("/auth/login", { method: "POST", body: { email, password, accept_terms } }),
  mediaToken: () => api<{ token: string }>("/auth/media-token"),
  register: (body: { email: string; password: string; name: string; workspace_name: string; accept_terms?: boolean }) =>
    api<{ access_token: string; user: User }>("/auth/register", { method: "POST", body }),
  me: () => api<User>("/auth/me"),
  /** The account's language, kept for every device it signs in on. */
  setLanguage: (language: "en" | "ur") => api<User>("/auth/me", { method: "PATCH", body: { language } }),
};

/** The owner's panel: accounts and plans. `myPlan` is for every account. */
export const accounts = {
  myPlan: () => api<MyPlan>("/plan"),
  list: () => api<Account[]>("/accounts"),
  create: (body: { email: string; password: string; name: string; plan_id: number | null; plan_expires_at: string | null; features?: Record<string, boolean | "first_day">; limits?: Record<string, number> }) => api<Account>("/accounts", { method: "POST", body }),
  update: (id: number, changes: AccountChanges) => api<Account>(`/accounts/${id}`, { method: "PATCH", body: changes }),
  remove: (id: number) => api<void>(`/accounts/${id}`, { method: "DELETE" }),
  buffer: (id: number) => api<BufferStatus>(`/accounts/${id}/buffer`),
  addBufferKey: (id: number, apiKey: string, label?: string) => api<BufferStatus>(`/accounts/${id}/buffer/keys`, { method: "POST", body: { api_key: apiKey, label: label || null } }),
  removeBufferKey: (id: number, keyId: number) => api<BufferStatus>(`/accounts/${id}/buffer/keys/${keyId}`, { method: "DELETE" }),
  plans: () => api<PlanList>("/plans"),
  createPlan: (body: PlanInput) => api<PlanList>("/plans", { method: "POST", body }),
  updatePlan: (id: number, body: PlanInput) => api<PlanList>(`/plans/${id}`, { method: "PUT", body }),
  removePlan: (id: number) => api<PlanList>(`/plans/${id}`, { method: "DELETE" }),
};

/** The admin's main switch for the whole tool. */
export const system = {
  state: () => api<SystemState>("/system"),
  switch: (on: boolean) => api<SystemState>("/system", { method: "PUT", body: { on } }),
};

export const dashboard = {
  summary: () => api<Summary>("/dashboard/summary"),
  performance: (days: number) => api<{ labels: string[]; values: number[] }>("/dashboard/performance", { query: { days } }),
  nav: () => api<Nav>("/dashboard/nav"),
  status: () => api<PipelineStatus>("/pipeline/status"),
  daily: (day?: string) => api<DailyReport>("/reports/daily", { query: { day } }),
};

export type PromptBody = Omit<Prompt, "id" | "is_default" | "created_at" | "updated_at">;

export const prompts = {
  list: () => api<Prompt[]>("/prompts"),
  meta: () => api<{ variables: string[]; provider: string; model: string; configured: boolean }>("/prompts/meta"),
  create: (body: PromptBody) => api<Prompt>("/prompts", { method: "POST", body }),
  update: (id: number, body: PromptBody) => api<Prompt>(`/prompts/${id}`, { method: "PUT", body }),
  remove: (id: number) => api<void>(`/prompts/${id}`, { method: "DELETE" }),
  makeDefault: (id: number) => api<Prompt>(`/prompts/${id}/default`, { method: "POST" }),
  versions: (id: number) => api<{ version: number; created_at: string; snapshot: PromptBody }[]>(`/prompts/${id}/versions`),
  restore: (id: number, version: number) => api<Prompt>(`/prompts/${id}/versions/${version}/restore`, { method: "POST" }),
  test: (body: { title_prompt: string; caption_prompt: string; hashtags_prompt: string; niche: string; caption: string; title?: string; tags?: string[]; llm_provider_id?: number | null }) =>
    api<{ title: string; caption: string; tags: string[] }>("/prompts/test", { method: "POST", body }),
};

export type JobQuery = { q?: string; status?: string; buffer_channel_id?: number; channel_id?: number; order?: "newest" | "oldest" | "posted"; period?: string; page?: number; page_size?: number };

export const jobs = {
  list: (query: JobQuery) => api<Page<Job>>("/jobs", { query }),
  get: (id: number) => api<Job>(`/jobs/${id}`),
  update: (id: number, body: Partial<{ rewritten_title: string; rewritten_caption: string; rewritten_tags: string[]; buffer_channel_id: number | null }>) =>
    api<Job>(`/jobs/${id}`, { method: "PATCH", body }),
  approve: (id: number) => api<Job>(`/jobs/${id}/approve`, { method: "POST" }),
  retry: (id: number) => api<Job>(`/jobs/${id}/retry`, { method: "POST" }),
  cancel: (id: number) => api<Job>(`/jobs/${id}/cancel`, { method: "POST" }),
  pause: (id: number) => api<Job>(`/jobs/${id}/pause`, { method: "POST" }),
  resume: (id: number) => api<Job>(`/jobs/${id}/resume`, { method: "POST" }),
  reject: (id: number, reason: string) => api<Job>(`/jobs/${id}/reject`, { method: "POST", body: { reason } }),
  processAnyway: (videoId: number) => api<Job>(`/videos/${videoId}/process`, { method: "POST" }),
  /** `kind` splits the skipped: "limit" = usable but over a daily limit (Not Processed), "filtered" = the rest (Skipped). */
  videos: (status?: string, limit = 20, channel_id?: number, kind?: "limit" | "filtered") => api<Video[]>("/videos", { query: { status, limit, channel_id, kind } }),
  dailyLimit: () => api<DailyLimit>("/limits/daily"),
};

export const channels = {
  /** `poll_minutes`: how often channels are checked besides push notifications; null = push only (the plan has no auto-check). */
  list: () => api<{ items: Channel[]; push_available: boolean; poll_minutes: number | null; channels_used: number; channels_allowed: number; plan: string; bigger_plans: { name: string; value: number }[] }>("/channels"),
  create: (body: { query: string }) => api<Channel>("/channels", { method: "POST", body }),
  update: (id: number, body: { active: boolean }) => api<Channel>(`/channels/${id}`, { method: "PATCH", body }),
  remove: (id: number) => api<void>(`/channels/${id}`, { method: "DELETE" }),
  check: (id: number) => api<{ found: number; queued: number; skipped: number; error: string | null }>(`/channels/${id}/check`, { method: "POST" }),
  rules: (id: number) => api<ChannelRules>(`/channels/${id}/rules`),
  saveRules: (id: number, values: Record<string, RuleValue | null>) => api<ChannelRules>(`/channels/${id}/rules`, { method: "PUT", body: { values } }),
};

export const rules = {
  get: () => api<{ definitions: RuleDef[]; values: RuleValues }>("/settings/rules"),
  save: (values: Record<string, RuleValue | null>) => api<{ definitions: RuleDef[]; values: RuleValues }>("/settings/rules", { method: "PUT", body: { values } }),
  history: (channel_id?: number) => api<RuleChange[]>("/settings/rules/history", { query: { channel_id, limit: 100 } }),
};

export const logs = {
  list: (query: { q?: string; level?: string; service?: string; page?: number; page_size?: number; limit?: number }) =>
    api<Page<ActivityLog> & { services: string[] }>("/logs", { query }),
};

export const settings = {
  notifications: () => api<NotificationSettings>("/settings/notifications"),
  saveNotifications: (body: Partial<NotificationSettings>) => api<NotificationSettings>("/settings/notifications", { method: "PUT", body }),
  testNotification: () => api<{ ok: boolean; message: string }>("/settings/notifications/test", { method: "POST" }),
  testEmail: () => api<{ ok: boolean; message: string }>("/settings/notifications/test-email", { method: "POST" }),
  integrations: () => api<Integration[]>("/settings/integrations"),
  testIntegration: (key: string) => api<{ ok: boolean; message: string }>(`/settings/integrations/${key}/test`, { method: "POST" }),
  completeOnboarding: () => api<{ completed: boolean }>("/settings/onboarding/complete", { method: "POST" }),
};

export const credentials = {
  list: () => api<CredentialCard[]>("/credentials"),
  validate: (group: string, values: Record<string, string> = {}) => api<CredentialResult>(`/credentials/${group}/validate`, { method: "POST", body: { values } }),
  save: (group: string, values: Record<string, string>, confirm_reconnect = false) =>
    api<CredentialResult>(`/credentials/${group}`, { method: "PUT", body: { values, confirm_reconnect } }),
  remove: (group: string, confirm_reconnect = false) =>
    api<{ fallback: "env" | "none"; card: CredentialCard }>(`/credentials/${group}`, { method: "DELETE", query: { confirm_reconnect } }),
};

export type LLMProviderBody = { label: string; provider: LLMProviderName; api_key: string; base_url: string | null; model: string; max_tokens: number; temperature: number | null };

/** An account's own AI models. `forUser`: an owner managing another account's models for them. */
export const llmProviders = {
  list: (forUser?: number) => api<LLMProviderList>("/llm-providers", { query: { for_user: forUser } }),
  validate: (body: { provider: LLMProviderName; api_key: string; base_url: string | null; provider_id?: number }, forUser?: number) =>
    api<{ models: string[] }>("/llm-providers/validate", { method: "POST", body, query: { for_user: forUser } }),
  create: (body: LLMProviderBody, forUser?: number) => api<LLMProvider>("/llm-providers", { method: "POST", body, query: { for_user: forUser } }),
  update: (id: number, body: Partial<LLMProviderBody> & { clear_temperature?: boolean }, forUser?: number) => api<LLMProvider>(`/llm-providers/${id}`, { method: "PATCH", body, query: { for_user: forUser } }),
  remove: (id: number, new_default_id?: number, forUser?: number) => api<{ fallback: "env" | "none" | null }>(`/llm-providers/${id}`, { method: "DELETE", query: { new_default_id, for_user: forUser } }),
  makeDefault: (id: number, forUser?: number) => api<LLMProvider>(`/llm-providers/${id}/default`, { method: "POST", query: { for_user: forUser } }),
  test: (id: number, forUser?: number) => api<{ ok: boolean; message: string; item: LLMProvider }>(`/llm-providers/${id}/test`, { method: "POST", query: { for_user: forUser } }),
};

type YouTubeKeyState = { has_key: boolean; key_last4: string; shared: boolean };
/** A member's own YouTube Data API key (owners use the shared one on the Integrations page). */
export const myKeys = {
  youtube: (forUser?: number) => api<YouTubeKeyState>("/my-keys/youtube", { query: { for_user: forUser } }),
  saveYoutube: (apiKey: string, forUser?: number) => api<YouTubeKeyState>("/my-keys/youtube", { method: "PUT", body: { api_key: apiKey }, query: { for_user: forUser } }),
  removeYoutube: (forUser?: number) => api<YouTubeKeyState>("/my-keys/youtube", { method: "DELETE", query: { for_user: forUser } }),
};

export const users = {
  list: () => api<User[]>("/users"),
  create: (body: { email: string; password: string; name: string }) => api<User>("/users", { method: "POST", body }),
  remove: (id: number) => api<void>(`/users/${id}`, { method: "DELETE" }),
  setRole: (id: number, role: "owner" | "member") => api<User>(`/users/${id}/role`, { method: "PATCH", body: { role } }),
};

/** Integrations → Video Source: the downloader's cookies file, proxy, player client, test and diagnosis (admin only). */
export const source = {
  info: () => api<SourceInfo>("/integrations/source"),
  save: (body: { proxy?: string; player_client?: string }) => api<SourceInfo>("/integrations/source", { method: "PUT", body }),
  /** The file itself is the request body; only its status comes back. */
  uploadCookies: async (file: File) => {
    const response = await fetch(apiUrl("/integrations/source/cookies"), { method: "POST", headers: { Authorization: `Bearer ${getToken() ?? ""}`, "Content-Type": "text/plain" }, body: await file.text() });
    const body = await response.json().catch(() => null);
    if (!response.ok) throw new ApiError(typeof body?.detail === "string" ? body.detail : `Upload failed (${response.status})`, response.status);
    return body as CookiesInfo;
  },
  removeCookies: () => api<void>("/integrations/source/cookies", { method: "DELETE" }),
  update: () => api<{ ok: boolean; message: string }>("/integrations/source/update", { method: "POST" }),
  test: (url: string) => api<{ ok: boolean; message: string }>("/integrations/source/test", { method: "POST", body: { url } }),
  diagnose: (url: string) => api<SourceDiagnosis>("/integrations/source/diagnose", { method: "POST", body: { url } }),
  diagnosis: (id: string) => api<SourceDiagnosis>(`/integrations/source/diagnose/${id}`),
};

/** Integrations → YouTube Data API: the key, the project ID and a live test (admin only). */
export const youtubeApi = {
  info: () => api<YouTubeApiInfo>("/integrations/youtube"),
  save: (body: { api_key?: string; project_id?: string }) => api<YouTubeApiInfo>("/integrations/youtube", { method: "PUT", body }),
  removeKey: () => api<YouTubeApiInfo>("/integrations/youtube/key", { method: "DELETE" }),
  test: () => api<YouTubeApiTest>("/integrations/youtube/test", { method: "POST" }),
};

/** Integrations → YouTube Push Notifications: the public address, the verify token and the subscriptions (admin only). */
export const push = {
  info: () => api<PushInfo>("/integrations/push"),
  save: (body: { public_base_url?: string; verify_token?: string }) => api<PushInfo>("/integrations/push", { method: "PUT", body }),
  subscribe: (channelId: string) => api<PushInfo>("/integrations/push/subscribe", { method: "POST", body: { channel_id: channelId } }),
  retryFailed: () => api<PushInfo>("/integrations/push/retry-failed", { method: "POST" }),
};

/** Buffer Settings: the member's own Buffer keys (up to ten) and the accounts connected there. */
export const buffer = {
  info: () => api<BufferStatus>("/buffer"),
  /** The key is checked with Buffer first, and refused if Buffer does not accept it. */
  addKey: (apiKey: string, label?: string) => api<BufferStatus>("/buffer/keys", { method: "POST", body: { api_key: apiKey, label: label || null } }),
  /** Rename a key, or replace it (a new key is checked with Buffer first). */
  updateKey: (id: number, changes: { api_key?: string; label?: string }) => api<BufferStatus>(`/buffer/keys/${id}`, { method: "PATCH", body: changes }),
  removeKey: (id: number) => api<BufferStatus>(`/buffer/keys/${id}`, { method: "DELETE" }),
  refresh: () => api<BufferStatus>("/buffer/refresh", { method: "POST" }),
  updateChannel: (id: number, changes: BufferChannelChanges) => api<BufferStatus>(`/buffer/channels/${id}`, { method: "PATCH", body: changes }),
  channelStatus: (id: number) => api<BufferChannelStatus>(`/buffer/channels/${id}/status`),
};

/** Editing Rules: the member's default look and presets for this workspace, and which channel uses which. */
export const editing = {
  get: () => api<EditingState>("/editing"),
  saveDefault: (look: Look) => api<EditingState>("/editing", { method: "PUT", body: { look } }),
  createPreset: (name: string, look: Look) => api<Preset>("/editing/presets", { method: "POST", body: { name, look } }),
  updatePreset: (id: number, body: { name?: string; look?: Look }) => api<Preset>(`/editing/presets/${id}`, { method: "PATCH", body }),
  deletePreset: (id: number) => api<void>(`/editing/presets/${id}`, { method: "DELETE" }),
  assign: (channelId: number, presetId: number | null) => api<EditingState>(`/editing/channels/${channelId}`, { method: "PUT", body: { preset_id: presetId } }),
  startTest: (url: string, look: Look) => api<TestRender>("/editing/test", { method: "POST", body: { url, look } }),
  test: (id: string) => api<TestRender>(`/editing/test/${id}`),
  previewUrl: (id: string, token: string) => apiUrl(`/editing/test/${id}/preview.mp4`, { token }),
};

export type LibraryKind = "music" | "fonts" | "watermark";
/** The member's own files: music, fonts and their watermark image. */
export const library = {
  list: (kind: LibraryKind) => api<Library>(`/library/${kind}`),
  /** The file itself is the request body. */
  upload: async (kind: LibraryKind, file: File) => {
    const response = await fetch(apiUrl(`/library/${kind}`, { name: file.name }), { method: "POST", headers: { Authorization: `Bearer ${getToken() ?? ""}`, "Content-Type": "application/octet-stream" }, body: file });
    const body = await response.json().catch(() => null);
    if (!response.ok) throw new ApiError(typeof body?.detail === "string" ? body.detail : `Upload failed (${response.status})`, response.status);
    return body as Library;
  },
  remove: (kind: LibraryKind, id: number) => api<Library>(`/library/${kind}/${id}`, { method: "DELETE" }),
  fileUrl: (kind: LibraryKind, id: number, token: string) => apiUrl(`/library/${kind}/${id}/file`, { token }),
};

/** PC Helper: connect a computer with a short code, and see or disconnect the member's computers. */
export const helper = {
  page: () => api<HelperPage>("/helper"),
  code: () => api<{ code: string; expires_at: string }>("/helper/code", { method: "POST" }),
  remove: (id: number) => api<void>(`/helper/devices/${id}`, { method: "DELETE" }),
};

/** Integrations → Cloud editing: Cloud Run's address, the service account key, and what happens when nothing can edit (owner only). */
export const cloudEditing = {
  info: () => api<CloudEditing>("/integrations/cloud-editing"),
  save: (body: { url?: string; fallback?: "fail" | "server"; enabled?: boolean }) => api<CloudEditing>("/integrations/cloud-editing", { method: "PUT", body }),
  /** The key file goes up once; only its status comes back. */
  uploadKey: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const response = await fetch(apiUrl("/integrations/cloud-editing/key"), { method: "POST", headers: { Authorization: `Bearer ${getToken() ?? ""}` }, body: form });
    const body = await response.json().catch(() => null);
    if (!response.ok) throw new ApiError(typeof body?.detail === "string" ? body.detail : `Upload failed (${response.status})`, response.status);
    return body as CloudEditing;
  },
  removeKey: () => api<CloudEditing>("/integrations/cloud-editing/key", { method: "DELETE" }),
  test: () => api<{ ok: boolean; message: string; at: string }>("/integrations/cloud-editing/test", { method: "POST" }),
};
