import { useMyPlan } from "@/hooks/useMyPlan";

const day = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });

/** A member's plan, on their Dashboard: its name, how long it lasts, its limits and what it does not include. Owners see nothing. */
export default function PlanCard() {
  const { plan, locked, blocked } = useMyPlan();
  if (!plan || plan.owner || blocked) return null;  // an ended plan has its own big notice
  const shown = plan.definitions.limits.filter(l => plan.limits[l.key] && !["auto_check_minutes", "trial_days", "skipped_keep_hours"].includes(l.key)).map(l => `${l.label}: ${plan.limits[l.key]}`);
  shown.push(plan.limits.auto_check_minutes ? `Channels checked every ${plan.limits.auto_check_minutes} min besides push notifications` : "New videos by push notification only");
  const daysLeft = plan.expires_at ? Math.max(0, Math.ceil((Date.parse(plan.expires_at) - Date.now()) / 86_400_000)) : null;
  const when = plan.expires_at && daysLeft !== null
    ? (plan.limits.trial_days ? `Free trial: ${daysLeft} day${daysLeft === 1 ? "" : "s"} left (ends ${day(plan.expires_at)}). ` : `Until ${day(plan.expires_at)} (${daysLeft} day${daysLeft === 1 ? "" : "s"} left). `)
    : "";
  return <div className={`plan-note${daysLeft !== null && daysLeft <= 3 ? " ending" : ""}`}>
    <b>Your plan: {plan.plan}</b>
    <span>{when}{shown.join(" · ")}.{locked.length > 0 && ` Not included: ${locked.join(", ")}.`} Ask the manager to upgrade it.</span>
  </div>;
}
