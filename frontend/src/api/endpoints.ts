import { ApiError, api, apiUrl, getToken } from "./client";
import type { Look } from "@/lib/look";
import type {
  ActivityLog, Channel, ChannelRules, CredentialCard, CredentialResult, DailyReport, LLMProvider, LLMProviderList, LLMProviderName, Integration, Job, Nav, NotificationSettings, Page, Prompt,
  PipelineStatus, EditingState, Library, Preset, TestRender, BufferChannelChanges, BufferChannelStatus, BufferStatus, PushInfo, YouTubeApiInfo, YouTubeApiTest, SourceDiagnosis, SourceInfo, CookiesInfo, RuleChange, RuleDef, RuleValue, RuleValues, Summary, User, Video,
} from "./types";

export const auth = {
  setup: () => api<{ has_users: boolean; registration_open: boolean }>("/auth/setup"),
  login: (email: string, password: string, accept_terms = false) => api<{ access_token: string; user: User }>("/auth/login", { method: "POST", body: { email, password, accept_terms } }),
  mediaToken: () => api<{ token: string }>("/auth/media-token"),
  register: (body: { email: string; password: string; name: string; workspace_name: string; accept_terms?: boolean }) =>
    api<{ access_token: string; user: User }>("/auth/register", { method: "POST", body }),
  me: () => api<User>("/auth/me"),
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
  videos: (status?: string, limit = 20, channel_id?: number) => api<Video[]>("/videos", { query: { status, limit, channel_id } }),
};

export const channels = {
  list: () => api<{ items: Channel[]; push_available: boolean; poll_minutes: number }>("/channels"),
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

export const llmProviders = {
  list: () => api<LLMProviderList>("/llm-providers"),
  validate: (body: { provider: LLMProviderName; api_key: string; base_url: string | null; provider_id?: number }) =>
    api<{ models: string[] }>("/llm-providers/validate", { method: "POST", body }),
  create: (body: LLMProviderBody) => api<LLMProvider>("/llm-providers", { method: "POST", body }),
  update: (id: number, body: Partial<LLMProviderBody> & { clear_temperature?: boolean }) => api<LLMProvider>(`/llm-providers/${id}`, { method: "PATCH", body }),
  remove: (id: number, new_default_id?: number) => api<{ fallback: "env" | "none" | null }>(`/llm-providers/${id}`, { method: "DELETE", query: { new_default_id } }),
  makeDefault: (id: number) => api<LLMProvider>(`/llm-providers/${id}/default`, { method: "POST" }),
  test: (id: number) => api<{ ok: boolean; message: string; item: LLMProvider }>(`/llm-providers/${id}/test`, { method: "POST" }),
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

/** Buffer Settings: the member's own Buffer key and the accounts connected there. */
export const buffer = {
  info: () => api<BufferStatus>("/buffer"),
  /** The key is checked with Buffer first, and refused if Buffer does not accept it. */
  saveKey: (apiKey: string) => api<BufferStatus>("/buffer/key", { method: "PUT", body: { api_key: apiKey } }),
  removeKey: () => api<BufferStatus>("/buffer/key", { method: "DELETE" }),
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
