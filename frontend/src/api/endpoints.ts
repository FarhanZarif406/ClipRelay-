import { api } from "./client";
import type {
  ActivityLog, AuditItem, AuditSettings, CredentialCard, CredentialResult, DailyReport, LLMProvider, LLMProviderList, LLMProviderName, Integration, Job, Nav, NotificationSettings, Page, Policy, Prompt,
  Source, Summary, TikTokAccount, User, Video, Violation,
} from "./types";

export const auth = {
  setup: () => api<{ has_users: boolean; registration_open: boolean }>("/auth/setup"),
  login: (email: string, password: string) => api<{ access_token: string; user: User }>("/auth/login", { method: "POST", body: { email, password } }),
  register: (body: { email: string; password: string; name: string; workspace_name: string }) =>
    api<{ access_token: string; user: User }>("/auth/register", { method: "POST", body }),
  me: () => api<User>("/auth/me"),
};

export const dashboard = {
  summary: () => api<Summary>("/dashboard/summary"),
  performance: (days: number) => api<{ labels: string[]; values: number[] }>("/dashboard/performance", { query: { days } }),
  nav: () => api<Nav>("/dashboard/nav"),
  daily: (day?: string) => api<DailyReport>("/reports/daily", { query: { day } }),
};

export const sources = {
  list: (query: { q?: string; status?: string; page?: number; page_size?: number }) =>
    api<Page<Source> & { connected: number; capacity: number }>("/sources", { query }),
  bulkAdd: (entries: string[]) =>
    api<{ activated: string[]; already_active: string[]; not_authorized: string[]; invalid: string[]; authorize_url: string | null }>(
      "/sources/bulk", { method: "POST", body: { entries } }),
  update: (id: number, body: Partial<{ is_active: boolean; refresh_interval_minutes: number; approval_mode: string; prompt_template_id: number; clear_prompt_template: boolean; tiktok_account_ids: number[] }>) =>
    api<Source>(`/sources/${id}`, { method: "PATCH", body }),
  bulkUpdate: (ids: number[], action: "pause" | "resume" | "delete" | "assign", tiktok_account_ids?: number[]) =>
    api<{ updated: number }>("/sources/bulk-update", { method: "POST", body: { ids, action, tiktok_account_ids } }),
  remove: (id: number) => api<void>(`/sources/${id}`, { method: "DELETE" }),
  run: (id: number) => api<{ queued: number[] }>(`/sources/${id}/run`, { method: "POST" }),
  runAll: () => api<{ queued: number[] }>("/runs", { method: "POST" }),
  oauthStart: () => api<{ url: string }>("/instagram/oauth/start"),
};

export const tiktok = {
  list: () => api<{ items: TikTokAccount[]; capacity: number }>("/tiktok-accounts"),
  update: (id: number, body: Partial<{ daily_cap: number; default_privacy: string; color: string }>) =>
    api<TikTokAccount>(`/tiktok-accounts/${id}`, { method: "PATCH", body }),
  disconnect: (id: number) => api<void>(`/tiktok-accounts/${id}`, { method: "DELETE" }),
  health: (id: number) =>
    api<{ account: TikTokAccount; published: number; failed: number; violation_count: number; compliance_rate: number; health: string; violations: Violation[] }>(
      `/tiktok-accounts/${id}/health`),
  routes: () => api<{ job_id: number; title: string; source: { username: string } | null; video_id: number; tiktok_account: TikTokAccount; status: string }[]>(
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

export type JobQuery = { q?: string; status?: string; source_id?: number; tiktok_account_id?: number; period?: string; page?: number; page_size?: number };

export const jobs = {
  list: (query: JobQuery) => api<Page<Job>>("/jobs", { query }),
  get: (id: number) => api<Job>(`/jobs/${id}`),
  update: (id: number, body: Partial<{ rewritten_title: string; rewritten_caption: string; rewritten_tags: string[]; privacy_level: string; tiktok_account_id: number | null }>) =>
    api<Job>(`/jobs/${id}`, { method: "PATCH", body }),
  approve: (id: number) => api<Job>(`/jobs/${id}/approve`, { method: "POST" }),
  retry: (id: number) => api<Job>(`/jobs/${id}/retry`, { method: "POST" }),
  cancel: (id: number) => api<Job>(`/jobs/${id}/cancel`, { method: "POST" }),
  processNext: () => api<{ job_id: number; action: string }>("/jobs/process-next", { method: "POST" }),
  videos: (status?: string, limit = 20) => api<Video[]>("/videos", { query: { status, limit } }),
};

export const audit = {
  list: () => api<{ items: AuditItem[]; settings: AuditSettings; compliance_rate: number; monitoring: number }>("/audit"),
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
