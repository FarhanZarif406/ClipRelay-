import { useState } from "react";
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

/**
 * The Podcasts window for an account whose plan has no Podcasts: it can be looked at, not worked in. A banner says so
 * on every page, and the first visit of a session shows what Podcasts does and which plan has it.
 */
export function PodcastsLocked() {
  const { plan, allows, upgradeFor } = useMyPlan();
  const [open, setOpen] = useState(() => { try { return !sessionStorage.getItem("cliprelay.podcasts.seen"); } catch { return true; } });
  if (!plan || plan.owner || allows("podcasts")) return null;
  const needs = upgradeFor("podcasts") ?? "a bigger";
  const close = () => { try { sessionStorage.setItem("cliprelay.podcasts.seen", "1"); } catch { /* private window */ } setOpen(false); };
  return <>
    <div className="podcasts-locked-banner" role="status"><b>{`Look around only: Podcasts is part of the ${needs} plan.`}</b> <span>You can see how it works; adding channels and making clips needs that plan.</span>
      <button type="button" className="link-button" onClick={() => setOpen(true)}>What Podcasts does</button></div>
    {open && <div className="overlay" onMouseDown={close}><div className="modal podcasts-locked" role="dialog" aria-modal="true" aria-label="Podcasts workspace" onMouseDown={e => e.stopPropagation()}>
      <div className="podcasts-locked-icon" aria-hidden>🎙️</div>
      <h2>Podcasts workspace</h2>
      <p className="muted">Turn long videos and podcasts into many short clips, on their own channels, rules and Buffer accounts.</p>
      <ul>
        <li>Watches podcast channels and takes each new episode by itself</li>
        <li>The AI reads the transcript and picks the strongest moments</li>
        <li>Each moment becomes a vertical clip, edited with your own look</li>
        <li>Clip Rules: how many clips, how long, which parts to skip</li>
        <li>Its own channels, review queue, reports and Buffer accounts</li>
      </ul>
      <div className="podcasts-locked-plan">{`Included in the ${needs} plan. Ask your manager to upgrade.`}</div>
      <div className="modal-foot"><button type="button" className="button primary" onClick={close}>Look around</button></div>
    </div></div>}
  </>;
}
