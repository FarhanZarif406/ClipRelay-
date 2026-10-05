import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { prompts, sources, tiktok } from "@/api/endpoints";
import type { Source } from "@/api/types";
import { Field, Modal } from "./Modal";
import { useErrorToast, useToast } from "./Toast";
import { Avatar, Button } from "./ui";

export const INTERVAL_PRESETS = [15, 30, 60, 360];

export function SourceEditModal({ source, close }: { source: Source; close: () => void }) {
  const preset = INTERVAL_PRESETS.includes(source.refresh_interval_minutes);
  const [interval, setIntervalChoice] = useState(preset ? String(source.refresh_interval_minutes) : "custom");
  const [custom, setCustom] = useState(String(source.refresh_interval_minutes));
  const [approval, setApproval] = useState(source.approval_mode);
  const [promptId, setPromptId] = useState(source.prompt_template_id ? String(source.prompt_template_id) : "");
  const [accountIds, setAccountIds] = useState<number[]>(source.tiktok_accounts.map(a => a.id));
  const accounts = useQuery({ queryKey: ["tiktok"], queryFn: tiktok.list });
  const promptList = useQuery({ queryKey: ["prompts"], queryFn: prompts.list });
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const minutes = interval === "custom" ? Number(custom) : Number(interval);
  const valid = Number.isFinite(minutes) && minutes >= 5 && minutes <= 10080;

  const save = useMutation({
    mutationFn: () => sources.update(source.id, {
      refresh_interval_minutes: minutes,
      approval_mode: approval,
      tiktok_account_ids: accountIds,
      ...(promptId ? { prompt_template_id: Number(promptId) } : { clear_prompt_template: true }),
    }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["sources"] }); toast({ title: "Source updated", message: `@${source.username} settings saved.` }); close(); },
    onError,
  });

  return <Modal title={`@${source.username}`} caption="Schedule, approval, prompt and publishing destinations for this source." onClose={close}
    footer={<><Button onClick={close}>Cancel</Button><Button variant="primary" disabled={!valid || save.isPending} onClick={() => save.mutate()}>Save changes</Button></>}>
    <div className="field-row">
      <Field label="Refresh interval"><select value={interval} onChange={e => setIntervalChoice(e.target.value)}><option value="15">Every 15 minutes</option><option value="30">Every 30 minutes</option><option value="60">Every hour</option><option value="360">Every 6 hours</option><option value="custom">Custom…</option></select></Field>
      {interval === "custom" ? <Field label="Custom (minutes)" hint="5 minutes to 7 days"><input type="number" min={5} max={10080} value={custom} onChange={e => setCustom(e.target.value)}/></Field>
        : <Field label="Posting mode"><select value={approval} onChange={e => setApproval(e.target.value as "auto" | "manual")}><option value="auto">Auto-post</option><option value="manual">Manual approval</option></select></Field>}
    </div>
    {interval === "custom" && <Field label="Posting mode"><select value={approval} onChange={e => setApproval(e.target.value as "auto" | "manual")}><option value="auto">Auto-post</option><option value="manual">Manual approval</option></select></Field>}
    <Field label="Prompt template" hint="Used to rewrite title, caption and tags for videos from this source."><select value={promptId} onChange={e => setPromptId(e.target.value)}><option value="">Workspace default</option>{promptList.data?.map(p => <option key={p.id} value={p.id}>{p.name}{p.is_default ? " (default)" : ""}{p.is_enabled ? "" : " — disabled"}</option>)}</select></Field>
    <Field label="Publish to TikTok accounts">
      <div className="check-list">{(accounts.data?.items ?? []).map(a => <label key={a.id}><input type="checkbox" checked={accountIds.includes(a.id)} onChange={() => setAccountIds(ids => ids.includes(a.id) ? ids.filter(x => x !== a.id) : [...ids, a.id])}/><Avatar label={a.initials} color={a.color}/>@{a.username}<span style={{ marginLeft: "auto", color: "var(--muted)", fontSize: 8 }}>{a.status}</span></label>)}
        {accounts.data?.items.length === 0 && <label>No TikTok accounts connected yet.</label>}</div>
    </Field>
  </Modal>;
}

export function CustomIntervalModal({ source, close }: { source: Source; close: () => void }) {
  const [value, setValue] = useState(String(source.refresh_interval_minutes));
  const queryClient = useQueryClient();
  const onError = useErrorToast();
  const n = Number(value);
  const save = useMutation({
    mutationFn: () => sources.update(source.id, { refresh_interval_minutes: n }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["sources"] }); close(); },
    onError,
  });
  return <Modal title="Custom check interval" caption={`How often ClipRelay checks @${source.username} for new videos.`} onClose={close}
    footer={<><Button onClick={close}>Cancel</Button><Button variant="primary" disabled={!(n >= 5 && n <= 10080) || save.isPending} onClick={() => save.mutate()}>Save</Button></>}>
    <Field label="Minutes" hint="Between 5 minutes and 7 days (10,080 minutes)."><input type="number" min={5} max={10080} value={value} onChange={e => setValue(e.target.value)} autoFocus/></Field>
  </Modal>;
}
