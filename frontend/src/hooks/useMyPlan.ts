import { useQuery } from "@tanstack/react-query";
import { accounts } from "@/api/endpoints";

/** What the signed-in account's plan allows. Until it is known, nothing is shown as locked. */
export function useMyPlan() {
  const { data } = useQuery({ queryKey: ["my-plan"], queryFn: accounts.myPlan, staleTime: 60_000, refetchInterval: 5 * 60_000 });
  const allows = (feature: string) => !data || data.owner || !!data.features[feature];
  const locked = data && !data.owner ? data.definitions.features.filter(f => !data.features[f.key]).map(f => f.label) : [];
  /** The plan to name next to a locked option ("PRO"), or null when the account has it. */
  const upgradeFor = (feature: string) => (allows(feature) ? null : (data?.upgrade[feature] ?? "Paid"));
  return { plan: data, allows, locked, upgradeFor, blocked: data && !data.owner ? data.blocked : null };
}
