import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { audit, settings } from "@/api/endpoints";
import type { AuditSettings } from "@/api/types";
import { Icon } from "@/components/Icon";
import { JobDrawer } from "@/components/JobDrawer";
import { Field, Modal } from "@/components/Modal";
import { useErrorToast, useToast } from "@/components/Toast";
import { Badge, Button, Card, Empty, PageHeader, Toggle } from "@/components/ui";
import { relativeTime } from "@/lib/format";

const THUMB = { Checking: "", Warning: "orange", Clear: "green", Violation: "pink" } as const;
const TONE = { Checking: "primary", Warning: "warning", Clear: "success", Violation: "danger" } as const;
const REMOVAL: Record<string, string> = { removed: "removed automatically", removed_by_tiktok: "already removed by TikTok", manual_required: "remove it in the TikTok app", disabled: "auto-remove is off", removed_manually: "removed manually" };

function FrequencyModal({ current, close, onSave }: { current: number[]; close: () => void; onSave: (hours: number[]) => void }) {
  const [value, setValue] = useState(current.join(", "));
  const hours = value.split(/[\s,]+/).map(Number).filter(n => n > 0 && n <= 72);
  return <Modal title="Check frequency" caption="When ClipRelay re-checks each published video. The last checkpoint ends monitoring." onClose={close}
    footer={<><Button onClick={close}>Cancel</Button><Button variant="primary" disabled={!hours.length} onClick={() => { onSave(hours); close(); }}>Save</Button></>}>
    <Field label="Hours after publishing" hint="Comma-separated, e.g. 1, 6, 12, 24 (max 72 hours)."><input value={value} onChange={e => setValue(e.target.value)} autoFocus/></Field>
  </Modal>;
}

export default function ComplianceAudit() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const [openJob, setOpenJob] = useState<number | null>(null);
  const [editing, setEditing] = useState(false);
  const { data } = useQuery({ queryKey: ["audit"], queryFn: audit.list, refetchInterval: 30_000 });
  const violations = useQuery({ queryKey: ["audit", "violations", "unack"], queryFn: () => audit.violations(true) });
  const saveSettings = useMutation({
    mutationFn: (body: Partial<AuditSettings>) => settings.saveAudit(body),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["audit"] }); toast({ title: "Audit settings saved" }); },
    onError,
  });
  const ack = useMutation({ mutationFn: audit.ack, onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["audit"] }); queryClient.invalidateQueries({ queryKey: ["nav"] }); queryClient.invalidateQueries({ queryKey: ["dashboard"] }); }, onError });
  const cfg = data?.settings;
  const scroll = () => document.querySelector(".audit-settings")?.scrollIntoView({ behavior: "smooth" });

  return <><PageHeader title="Compliance Audit" description={`${cfg ? `${Math.max(...cfg.check_hours)}-hour` : "24-hour"} post-publication monitoring and automatic enforcement.`}><Button onClick={scroll}>Audit settings</Button></PageHeader>
    {(violations.data ?? []).length > 0 && <div className="violation-list">{violations.data!.map(v => <div className="violation-alert" key={v.id}><div className="alert-icon"><Icon name="alert"/></div><div><strong>“{v.title || `Job #${v.job_id}`}” flagged on @{v.tiktok_account?.username}</strong><span>{v.reason} · {relativeTime(v.detected_at, { suffix: true })} · {REMOVAL[v.removal_status] ?? v.removal_status}</span></div><Button variant="ghost" onClick={() => setOpenJob(v.job_id)}>Details</Button><Button variant="danger" onClick={() => ack.mutate(v.id)}>{v.removal_status === "manual_required" ? "Mark removed" : "Acknowledge"}</Button></div>)}</div>}
    <div className="audit-layout"><div className="audit-list">
      {data?.items.length === 0 && <Card><Empty icon="shield" title="Nothing to monitor yet">Published videos are checked automatically for 24 hours.</Empty></Card>}
      {data?.items.map(a => { const status = a.display_status; return <Card className="audit-item" key={a.id}><div className={`audit-thumb ${THUMB[status]}`} style={a.video.thumbnail_url ? { backgroundImage: `url(${a.video.thumbnail_url})`, backgroundSize: "cover" } : undefined}><Icon name="play"/></div><div className="audit-main"><div className="audit-title"><strong>{a.rewritten_title || a.video.original_title || `Job #${a.id}`}</strong><Badge tone={TONE[status]}>{status}</Badge></div><span>Published to @{a.tiktok_account?.username} · {relativeTime(a.posted_at, { suffix: true })}{a.violation_reason ? ` · ${a.violation_reason}` : ""}</span>
        <div className="checkpoint"><div className="progress" style={{ width: `${a.progress}%` }}/>{a.checkpoints.map(c => <div className={c.done ? "done" : ""} key={c.label}><i><Icon name="check" size={10}/></i><span>{c.label}</span></div>)}</div></div>
        <div className={`count-ring ${status.toLowerCase()}`}><strong>{status === "Checking" || status === "Warning" ? String(Math.floor(a.hours_left)).padStart(2, "0") : status === "Violation" ? "!" : "✓"}</strong><span>{status === "Checking" || status === "Warning" ? "hours left" : status === "Violation" ? "Removed" : "Complete"}</span></div><Button variant="ghost" icon="chevron" onClick={() => setOpenJob(a.id)}/></Card>; })}</div>
    <Card className="audit-settings"><div className="card-title">Audit settings</div><div className="setting-row"><div><strong>Auto-remove violations</strong><span>Remove confirmed violations (or flag them for manual removal where TikTok’s API can’t)</span></div><Toggle checked={!!cfg?.auto_remove} onChange={() => cfg && saveSettings.mutate({ auto_remove: !cfg.auto_remove })}/></div><div className="setting-row"><div><strong>Check frequency</strong><span>At {cfg?.check_hours.map(h => `${h}h`).join(", ") ?? "…"}</span></div><Button onClick={() => setEditing(true)}>Edit</Button></div><div className="setting-row"><div><strong>Notifications</strong><span>Dashboard alerts and webhook</span></div><Toggle checked={!!cfg?.notifications_enabled} onChange={() => cfg && saveSettings.mutate({ notifications_enabled: !cfg.notifications_enabled })}/></div><div className="audit-stat"><Icon name="shield"/><div><strong>{data && data.compliance_rate !== null ? `${data.compliance_rate}%` : "—"}</strong><span>Compliance rate this month</span></div></div></Card></div>
    {editing && cfg && <FrequencyModal current={cfg.check_hours} close={() => setEditing(false)} onSave={hours => saveSettings.mutate({ check_hours: hours })}/>}
    {openJob && <JobDrawer jobId={openJob} close={() => setOpenJob(null)}/>}
  </>;
}
