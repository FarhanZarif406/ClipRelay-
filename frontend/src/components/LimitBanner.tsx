import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { jobs } from "@/api/endpoints";
import type { DailyLimit } from "@/api/types";
import { Button } from "@/components/ui";
import { PODCASTS } from "@/lib/mode";
import { useMyPlan } from "@/hooks/useMyPlan";

/** "11h 42m" until the daily count starts again. */
export function untilReset(limit: DailyLimit) {
  const minutes = Math.max(0, Math.ceil((Date.parse(limit.resets_at) - Date.now()) / 60_000));
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

/** Where today's number comes from, in a few words. */
export function limitSource(limit: DailyLimit) {
  if (limit.source === "accounts") return `from your ${limit.accounts} switched-on Buffer account${limit.accounts === 1 ? "" : "s"} (${limit.account_posts} posts a day${PODCASTS ? ", divided by the clips per podcast" : ""})`;
  return limit.set_to_match ? "set in the rules — no Buffer account is switched on" : "set by hand in the rules";
}

export function useDailyLimit() {
  return useQuery({ queryKey: ["daily-limit"], queryFn: jobs.dailyLimit, refetchInterval: 60_000 });
}

/** What a member at their limit is told to do, by plan: a bigger plan, or (on the biggest) that the limit is reached. */
export function upgradeLine(planName: string | undefined, owner: boolean) {
  if (owner || !planName) return null;
  if (planName === "Business") return "Limit reached: Business is the biggest plan.";
  if (planName === "Pro") return "Choose the Business plan for more videos a day.";
  return "Choose your plan: a bigger plan takes more videos a day.";
}

/** Shown once today's daily limit is used up: new uploads are only recorded (not even read), not edited. */
export default function LimitBanner() {
  const navigate = useNavigate();
  const { data: limit } = useDailyLimit();
  const { plan } = useMyPlan();
  if (!limit?.reached) return null;
  const upgrade = upgradeLine(plan?.plan, !!plan?.owner);
  return <div className="limit-banner" role="status">
    <div><b>Daily limit reached — {limit.used} of {limit.limit} {PODCASTS ? "podcasts" : "videos"} taken today.</b>
      <span>New uploads are only listed under Not Processed; nothing more is checked, downloaded or edited today. The count starts again in {untilReset(limit)}.</span>
      {upgrade && <strong className="limit-upgrade">{upgrade} Ask the manager.</strong>}</div>
    <Button onClick={() => navigate("/not-processed")}>Not Processed</Button>
  </div>;
}
