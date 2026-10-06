import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { llmProviders } from "@/api/endpoints";
import type { LLMProvider, LLMProviderName } from "@/api/types";
import { dayTime } from "@/lib/format";
import { SecretInput } from "./CredentialCard";
import { Field, Modal } from "./Modal";
import { useErrorToast, useToast } from "./Toast";
import { Badge, Button, Card, Empty } from "./ui";

export const PROVIDER_NAMES: Record<LLMProviderName, string> = {
  anthropic: "Anthropic (Claude)", openai: "OpenAI", gemini: "Google Gemini", openrouter: "OpenRouter",
  groq: "Groq", mistral: "Mistral", custom: "Custom (OpenAI-compatible)",
};
const STATUS = { valid: ["Valid", "success"], unverified: ["Unverified", "warning"], invalid: ["Invalid", "danger"] } as const;

function ProviderModal({ existing, close }: { existing?: LLMProvider; close: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const [provider, setProvider] = useState<LLMProviderName>(existing?.provider ?? "anthropic");
  const [label, setLabel] = useState(existing?.label ?? "");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(existing?.base_url ?? "");
  const [models, setModels] = useState<string[] | null>(existing ? [existing.model] : null);
  const [model, setModel] = useState(existing?.model ?? "");
  const [maxTokens, setMaxTokens] = useState(String(existing?.max_tokens ?? 600));
  const [temperature, setTemperature] = useState(existing?.temperature != null ? String(existing.temperature) : "");
  const [validated, setValidated] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A new provider, a new key, another provider type or base URL must be validated before saving.
  const connectionChanged = !existing || !!apiKey.trim() || provider !== existing.provider || (baseUrl || "") !== (existing.base_url || "");
  const resetValidation = () => { setValidated(false); setError(null); };

  const validate = useMutation({
    mutationFn: () => llmProviders.validate({ provider, api_key: apiKey.trim(), base_url: provider === "custom" ? baseUrl.trim() || null : null, provider_id: existing?.id }),
    onSuccess: r => {
      setModels(r.models); setValidated(true); setError(null);
      if (!r.models.includes(model)) setModel(r.models[0] ?? "");
    },
    onError: e => { setValidated(false); setModels(existing ? [existing.model] : null); setError(e instanceof Error ? e.message : String(e)); },
  });
  const save = useMutation({
    mutationFn: () => {
      const temp = temperature.trim() === "" ? null : Number(temperature);
      const common = { label: label.trim() || PROVIDER_NAMES[provider], provider, model, max_tokens: Number(maxTokens) || 600, base_url: provider === "custom" ? baseUrl.trim() || null : null };
      return existing
        ? llmProviders.update(existing.id, { ...common, ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}), ...(temp === null ? { clear_temperature: true } : { temperature: temp }) })
        : llmProviders.create({ ...common, api_key: apiKey.trim(), temperature: temp });
    },
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["llm-providers"] }); queryClient.invalidateQueries({ queryKey: ["prompts", "meta"] }); toast({ title: existing ? "AI model updated" : "AI model added" }); close(); },
    onError,
  });
  const canSave = !!model && (!connectionChanged || validated) && (existing || apiKey.trim()) && (provider !== "custom" || baseUrl.trim()) && !save.isPending;

  return <Modal title={existing ? `Edit ${existing.label}` : "Add AI model"} caption="Keys are encrypted and never shown again after saving." onClose={close}
    footer={<><Button onClick={close}>Cancel</Button><Button variant="primary" disabled={!canSave} onClick={() => save.mutate()} title={connectionChanged && !validated ? "Validate the key first" : undefined}>{save.isPending ? "Saving…" : "Save"}</Button></>}>
    <div className="field-row">
      <Field label="Provider"><select value={provider} onChange={e => { setProvider(e.target.value as LLMProviderName); resetValidation(); setModels(null); }}>{Object.entries(PROVIDER_NAMES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
      <Field label="Label"><input value={label} onChange={e => setLabel(e.target.value)} placeholder={PROVIDER_NAMES[provider]}/></Field>
    </div>
    <Field label="API key" hint={existing ? `Current key: ${existing.masked_key ?? "••••"} — leave blank to keep it.` : undefined}><SecretInput value={apiKey} onChange={v => { setApiKey(v); resetValidation(); }} placeholder={existing ? "Leave blank to keep the current key" : "Paste the API key"}/></Field>
    {provider === "custom" && <Field label="Base URL" hint="OpenAI-compatible endpoint, e.g. https://llm.example.com/v1"><input value={baseUrl} onChange={e => { setBaseUrl(e.target.value); resetValidation(); }} placeholder="https://…/v1"/></Field>}
    <div className="inline-form" style={{ marginTop: 0, marginBottom: 14 }}><Button onClick={() => validate.mutate()} disabled={validate.isPending || (!apiKey.trim() && !existing)}>{validate.isPending ? "Validating…" : "Validate"}</Button>{validated && <Badge tone="success">Key accepted · {models?.length ?? 0} models</Badge>}</div>
    {error && <div className="form-error" style={{ marginTop: 0, marginBottom: 14 }}>{error}</div>}
    <div className="field-row">
      <Field label="Model">{models && models.length ? <select value={model} onChange={e => setModel(e.target.value)}>{models.map(m => <option key={m} value={m}>{m}</option>)}</select> : <input value={model} disabled placeholder="Validate to load models"/>}</Field>
      <Field label="Max tokens"><input type="number" min={16} max={32000} value={maxTokens} onChange={e => setMaxTokens(e.target.value)}/></Field>
    </div>
    <Field label="Temperature (optional)" hint="Leave blank to use the provider’s default."><input type="number" min={0} max={2} step={0.1} value={temperature} onChange={e => setTemperature(e.target.value)}/></Field>
  </Modal>;
}

function RemoveModal({ item, all, envConfigured, close }: { item: LLMProvider; all: LLMProvider[]; envConfigured: boolean; close: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const others = all.filter(p => p.id !== item.id);
  const [replacement, setReplacement] = useState(others[0]?.id);
  const remove = useMutation({
    mutationFn: () => llmProviders.remove(item.id, item.is_default ? replacement : undefined),
    onSuccess: r => { queryClient.invalidateQueries({ queryKey: ["llm-providers"] }); queryClient.invalidateQueries({ queryKey: ["prompts"] }); toast({ title: "AI model removed", message: r.fallback === "env" ? "Using LLM_* from .env." : r.fallback === "none" ? "No AI model is configured now." : undefined }); close(); },
    onError,
  });
  return <Modal title={`Remove ${item.label}?`} onClose={close} footer={<><Button onClick={close}>Cancel</Button><Button variant="danger" onClick={() => remove.mutate()} disabled={remove.isPending}>Remove</Button></>}>
    {item.is_default && others.length > 0 && <Field label="New default model"><select value={replacement} onChange={e => setReplacement(Number(e.target.value))}>{others.map(o => <option key={o.id} value={o.id}>{o.label} · {o.model}</option>)}</select></Field>}
    {others.length === 0 && (envConfigured
      ? <div className="form-note">This is the last AI model. ClipRelay falls back to the <code>LLM_*</code> settings in <code>.env</code>.</div>
      : <div className="form-error">This is the last AI model and <code>.env</code> has no LLM key — rewriting and the language gate stop working until you add one.</div>)}
    <div className="form-note">Prompt templates that use this model switch to the workspace default.</div>
  </Modal>;
}

export function AIModels({ isOwner }: { isOwner: boolean }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const { data } = useQuery({ queryKey: ["llm-providers"], queryFn: llmProviders.list });
  const [modal, setModal] = useState<{ kind: "add" } | { kind: "edit" | "remove"; item: LLMProvider } | null>(null);
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["llm-providers"] });
  const test = useMutation({ mutationFn: (id: number) => llmProviders.test(id), onSuccess: r => { invalidate(); toast({ title: r.ok ? "Model replied" : "Test failed", message: r.message, tone: r.ok ? "success" : "danger" }); }, onError });
  const makeDefault = useMutation({ mutationFn: (id: number) => llmProviders.makeDefault(id), onSuccess: () => { invalidate(); queryClient.invalidateQueries({ queryKey: ["prompts", "meta"] }); }, onError });
  const items = data?.items ?? [];
  const env = data?.env_fallback;

  return <Card><div className="credential-head" style={{ marginBottom: 6 }}><div><div className="card-title">AI models</div><div className="card-caption">Rewrite titles, captions and hashtags with any of these. The default is used unless a prompt template picks another model.</div></div>{isOwner && <Button variant="primary" icon="plus" onClick={() => setModal({ kind: "add" })}>Add model</Button>}</div>
    {items.length === 0 && env && <div className={env.configured ? "form-note" : "form-error"}>{env.configured ? <>No AI models added yet — using <strong>{env.provider} · {env.model}</strong> from <code>.env</code>.</> : <>No AI model configured. Add one to enable rewriting.</>}</div>}
    {items.map(p => { const [label, tone] = STATUS[p.status]; const testing = test.isPending && test.variables === p.id; return <div className="api-row" key={p.id}>
      <div><strong>{p.label}{p.is_default && <> <Badge tone="primary" dot={false}>Default</Badge></>}</strong><span>{PROVIDER_NAMES[p.provider]} · {p.model}{isOwner && p.masked_key ? ` · ${p.masked_key}` : ""}{p.last_tested_at ? ` · tested ${dayTime(p.last_tested_at)}` : ""}</span>{p.status === "invalid" && p.last_error && <span className="row-error" style={{ maxWidth: 420 }} title={p.last_error}>{p.last_error}</span>}</div>
      <Badge tone={testing ? "primary" : tone}>{testing ? "Testing…" : label}</Badge>
      {isOwner && <><Button onClick={() => test.mutate(p.id)} disabled={testing}>Test</Button><Button onClick={() => setModal({ kind: "edit", item: p })}>Edit</Button>{!p.is_default && <Button onClick={() => makeDefault.mutate(p.id)}>Set default</Button>}<Button variant="danger" onClick={() => setModal({ kind: "remove", item: p })}>Remove</Button></>}
    </div>; })}
    {items.length === 0 && !env && <Empty icon="sparkles" title="Loading…"/>}
    {modal?.kind === "add" && <ProviderModal close={() => setModal(null)}/>}
    {modal?.kind === "edit" && <ProviderModal existing={modal.item} close={() => setModal(null)}/>}
    {modal?.kind === "remove" && <RemoveModal item={modal.item} all={items} envConfigured={!!env?.configured} close={() => setModal(null)}/>}
  </Card>;
}
