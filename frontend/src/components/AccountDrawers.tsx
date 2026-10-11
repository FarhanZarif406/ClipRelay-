import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { tiktok } from "@/api/endpoints";
import type { TikTokAccount } from "@/api/types";
import { dayTime } from "@/lib/format";
import { Field, Modal } from "./Modal";
import { useErrorToast, useToast } from "./Toast";
import { Avatar, Badge, Button, Empty } from "./ui";

const HEALTH = { healthy: ["Healthy", "success"], at_risk: ["At risk", "warning"], poor: ["Poor", "danger"] } as const;
const REMOVAL: Record<string, string> = {
  removed: "Removed automatically", removed_by_tiktok: "Removed by TikTok", manual_required: "Remove manually in TikTok",
  removed_manually: "Removed manually", disabled: "Auto-remove off", pending: "Pending",
};

export function AccountHealthDrawer({ account, close }: { account: TikTokAccount; close: () => void }) {
  const { data } = useQuery({ queryKey: ["tiktok", "health", account.id], queryFn: () => tiktok.health(account.id) });
  const health = data ? HEALTH[data.health as keyof typeof HEALTH] ?? HEALTH.poor : null;
  return <div className="drawer-overlay" onMouseDown={close}><aside className="drawer" onMouseDown={e => e.stopPropagation()}>
    <div className="drawer-head"><div style={{ display: "flex", gap: 10, alignItems: "center" }}><Avatar label={account.initials} color={account.color}/><div>{health && <Badge tone={health[1]}>{health[0]}</Badge>}<div className="card-title">@{account.username}</div></div></div><Button variant="ghost" icon="close" onClick={close}/></div>
    <div className="drawer-section" style={{ marginTop: 18 }}><div className="section-label">ACCOUNT HEALTH</div>
      <div className="drawer-meta"><div><span>Compliance rate</span><strong>{data ? `${data.compliance_rate}%` : "—"}</strong></div><div><span>Published</span><strong>{data?.published ?? "—"}</strong></div><div><span>Violations</span><strong>{data?.violation_count ?? "—"}</strong></div><div><span>Failed uploads</span><strong>{data?.failed ?? "—"}</strong></div><div><span>Token expires</span><strong>{account.refresh_expires_at ? dayTime(account.refresh_expires_at) : "—"}</strong></div><div><span>Last post</span><strong>{account.last_posted_at ? dayTime(account.last_posted_at) : "Never"}</strong></div></div>
      {account.last_error && <div className="error-note">{account.last_error}</div>}
    </div>
    <div className="drawer-section"><div className="section-label">VIOLATION HISTORY</div>
      {data?.violations.length === 0 && <Empty icon="shield" title="No violations">Every video on this account has passed monitoring.</Empty>}
      <div className="timeline">{data?.violations.map(v => <div className="timeline-item violated" key={v.id}><i/><div><strong>{v.title || `Job #${v.job_id}`}</strong><span>{v.reason}</span><span>{dayTime(v.detected_at)} · {REMOVAL[v.removal_status] ?? v.removal_status}</span></div></div>)}</div>
    </div>
  </aside></div>;
}

export function AccountSettingsModal({ account, close }: { account: TikTokAccount; close: () => void }) {
  const [cap, setCap] = useState(account.daily_cap_override ? String(account.daily_cap_override) : "");
  const [privacy, setPrivacy] = useState(account.default_privacy);
  const [color, setColor] = useState(account.color);
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const save = useMutation({
    mutationFn: () => tiktok.update(account.id, { daily_cap: cap.trim() ? Number(cap) : null, default_privacy: privacy, color }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["tiktok"] }); toast({ title: "Account updated" }); close(); },
    onError,
  });
  return <Modal title={`@${account.username}`} caption="Publishing limits and defaults for this TikTok account." onClose={close}
    footer={<><Button onClick={close}>Cancel</Button><Button variant="primary" disabled={save.isPending || !(cap.trim() === "" || (Number(cap) >= 1 && Number(cap) <= 100))} onClick={() => save.mutate()}>Save</Button></>}>
    <div className="field-row">
      <Field label="Daily post cap" hint="Leave empty to follow the global rule (Settings → Pipeline rules)."><input type="number" min={1} max={100} value={cap} placeholder={`${account.daily_cap} (global rule)`} onChange={e => setCap(e.target.value)}/></Field>
      <Field label="Avatar color"><select value={color} onChange={e => setColor(e.target.value)}>{["violet", "blue", "orange", "pink", "green"].map(c => <option key={c} value={c}>{c}</option>)}</select></Field>
    </div>
    <Field label="Default privacy" hint="Must be one of the options TikTok returns for this creator; unaudited apps can only post privately (SELF_ONLY).">
      <select value={privacy} onChange={e => setPrivacy(e.target.value)}><option value="PUBLIC_TO_EVERYONE">Public</option><option value="MUTUAL_FOLLOW_FRIENDS">Friends</option><option value="FOLLOWER_OF_CREATOR">Followers</option><option value="SELF_ONLY">Only me</option></select>
    </Field>
  </Modal>;
}
