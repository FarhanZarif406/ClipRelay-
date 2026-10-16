import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { system } from "@/api/endpoints";
import { useAuth } from "@/hooks/useAuth";
import { useErrorToast, useToast } from "@/components/Toast";
import { Button } from "@/components/ui";

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "");

/** The admin's main switch, at the top of the Dashboard. Members never see it. */
export default function MainSwitch() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const { data } = useQuery({ queryKey: ["system"], queryFn: system.state, refetchInterval: 30_000, enabled: user?.role === "owner" });
  const flip = useMutation({
    mutationFn: (on: boolean) => system.switch(on),
    onSuccess: state => {
      queryClient.setQueryData(["system"], state);
      for (const key of ["nav", "jobs", "pipeline-status"]) queryClient.invalidateQueries({ queryKey: [key] });
      toast(state.on
        ? { title: "System is on", message: "Channels are watched again, and paused videos carry on." }
        : { title: "System is off", message: "Nothing is detected, downloaded, edited or published until you switch it on.", tone: "danger" });
    },
    onError,
  });
  if (user?.role !== "owner" || !data) return null;
  const toggle = () => {
    if (data.on && !window.confirm("Switch the whole system off?\n\nFor every member: no new videos are detected, and videos being downloaded, edited or sent to Buffer are paused. Posts already scheduled in Buffer still go out.")) return;
    flip.mutate(!data.on);
  };
  return <div className={`main-switch ${data.on ? "on" : "off"}`}>
    <div className="main-switch-lamp" aria-hidden/>
    <div className="main-switch-text">
      <b>Main switch · System {data.on ? "ON" : "OFF"}</b>
      <span>{data.on
        ? "Everything runs: channels are watched, and videos are downloaded, edited and published."
        : `Everything is stopped for every member${data.changed_at ? ` since ${when(data.changed_at)}` : ""}. New uploads are ignored; paused videos carry on when you switch it on.`}</span>
    </div>
    <Button variant={data.on ? "danger" : "primary"} disabled={flip.isPending} onClick={toggle}>{flip.isPending ? "Switching…" : data.on ? "Switch off" : "Switch on"}</Button>
  </div>;
}

/** Shown on every page while the system is off, to admins and members alike. */
export function SystemOffBanner({ off }: { off: boolean }) {
  if (!off) return null;
  return <div className="system-off-banner" role="alert"><b>The system is off.</b> The admin has switched ClipRelay off: no videos are detected, downloaded, edited or published until it is switched on again.</div>;
}
