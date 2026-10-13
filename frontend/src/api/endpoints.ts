import { ApiError, api, apiUrl, getToken } from "./client";
import type {
  ActivityLog, AuditItem, AuditSettings, Channel, ChannelCard, ChannelRules, CredentialCard, CredentialResult, DailyReport, LLMProvider, LLMProviderList, LLMProviderName, Integration, Job, Nav, NotificationSettings, Page, Policy, Prompt,
  PipelineStatus, SourceDiagnosis, SourceInfo, CookiesInfo, RuleChange, RuleDef, RuleValue, RuleValues, Summary, TikTokAccount, User, Video, Violation,
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

export const tiktok = {
  list: () => api<{ items: TikTokAccount[]; capacity: number }>("/tiktok-accounts"),
  update: (id: number, body: Partial<{ daily_cap: number | null; default_privacy: string; color: string }>) =>
    api<TikTokAccount>(`/tiktok-accounts/${id}`, { method: "PATCH", body }),
  disconnect: (id: number) => api<void>(`/tiktok-accounts/${id}`, { method: "DELETE" }),
  health: (id: number) =>
    api<{ account: TikTokAccount; published: number; failed: number; violation_count: number; compliance_rate: number; health: string; violations: Violation[] }>(
      `/tiktok-accounts/${id}/health`),
  routes: () => api<{ job_id: number; title: string; video_id: number; tiktok_account: TikTokAccount; status: string }[]>(
    "/tiktok-accounts/routes-preview"),
  oauthStart: () => api<{ url: string }>("/tiktok/oauth/start"),
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

export type JobQuery = { q?: string; status?: string; tiktok_account_id?: number; channel_id?: number; order?: "newest" | "oldest" | "posted"; period?: string; page?: number; page_size?: number };

export const jobs = {
  list: (query: JobQuery) => api<Page<Job>>("/jobs", { query }),
  get: (id: number) => api<Job>(`/jobs/${id}`),
  update: (id: number, body: Partial<{ rewritten_title: string; rewritten_caption: string; rewritten_tags: string[]; privacy_level: string; tiktok_account_id: number | null }>) =>
    api<Job>(`/jobs/${id}`, { method: "PATCH", body }),
  approve: (id: number) => api<Job>(`/jobs/${id}/approve`, { method: "POST" }),
  retry: (id: number) => api<Job>(`/jobs/${id}/retry`, { method: "POST" }),
  cancel: (id: number) => api<Job>(`/jobs/${id}/cancel`, { method: "POST" }),
  reject: (id: number, reason: string) => api<Job>(`/jobs/${id}/reject`, { method: "POST", body: { reason } }),
  processAnyway: (videoId: number) => api<Job>(`/videos/${videoId}/process`, { method: "POST" }),
  videos: (status?: string, limit = 20, channel_id?: number) => api<Video[]>("/videos", { query: { status, limit, channel_id } }),
};

export const channels = {
  list: () => api<{ items: Channel[]; push_available: boolean }>("/channels"),
  resolve: (query: string) => api<ChannelCard>("/channels/resolve", { method: "POST", body: { query } }),
  create: (body: { query: string; default_tiktok_account_id: number | null }) => api<Channel>("/channels", { method: "POST", body }),
  update: (id: number, body: Partial<{ active: boolean; default_tiktok_account_id: number | null }>) => api<Channel>(`/channels/${id}`, { method: "PATCH", body }),
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

export const audit = {
  list: () => api<{ items: AuditItem[]; settings: AuditSettings; compliance_rate: number | null; monitoring: number }>("/audit"),
  violations: (unacknowledged = false) => api<Violation[]>("/violations", { query: { unacknowledged } }),
  ack: (id: number) => api<Violation>(`/violations/${id}/ack`, { method: "POST" }),
};

export const logs = {
  list: (query: { q?: string; level?: string; service?: string; page?: number; page_size?: number; limit?: number }) =>
    api<Page<ActivityLog> & { services: string[] }>("/logs", { query }),
};

export const settings = {
  policy: () => api<Policy>("/settings/policy"),
  savePolicy: (body: Partial<Policy>) => api<Policy>("/settings/policy", { method: "PUT", body }),
  audit: () => api<AuditSettings>("/settings/audit"),
  saveAudit: (body: Partial<AuditSettings>) => api<AuditSettings>("/settings/audit", { method: "PUT", body }),
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
