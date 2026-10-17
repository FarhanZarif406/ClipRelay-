import { useMyPlan } from "@/hooks/useMyPlan";

/** A small box next to an option the account's plan does not include, naming the plan that does ("PRO"). */
export function PlanTag({ feature }: { feature: string }) {
  const { upgradeFor } = useMyPlan();
  const plan = upgradeFor(feature);
  if (!plan) return null;
  return <span className="plan-tag" title={`Part of the ${plan} plan. You can try it here; saving it needs that plan.`}>{plan.toUpperCase()}</span>;
}

/** The days left and the end of an account's trial or plan, for banners. */
export function PlanEndedBanner() {
  const { plan, blocked } = useMyPlan();
  if (blocked !== "expired" || !plan) return null;
  return <div className="plan-ended-banner" role="alert"><b>{plan.plan === "Free Trial" ? "Your free trial has ended." : `Your ${plan.plan} plan has ended.`}</b> Nothing is detected, downloaded, edited or uploaded for you until you get a plan. Ask the manager for a plan to carry on.</div>;
}

/** The big notice on the Dashboard when the account's trial or plan has ended. */
export function PlanEndedCard() {
  const { plan, blocked } = useMyPlan();
  if (blocked !== "expired" || !plan) return null;
  const trial = plan.plan === "Free Trial";
  return <div className="plan-ended-card">
    <div className="plan-ended-icon" aria-hidden>!</div>
    <div>
      <h2>{trial ? "Your free trial has ended" : `Your ${plan.plan} plan has ended`}</h2>
      <p>Your account is paused: no new videos are detected, downloaded, edited or uploaded. Your channels, rules and keys are kept, and everything carries on as soon as you have a plan.</p>
      <p><b>To keep working, buy a plan (Bronze, Silver, Gold or Platinum) from your manager.</b>{plan.expires_at ? ` Ended on ${new Date(plan.expires_at).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" })}.` : ""}</p>
    </div>
  </div>;
}
