import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { helper } from "@/api/endpoints";
import type { HelperDevice } from "@/api/types";
import { Icon } from "@/components/Icon";
import { PlanTag } from "@/components/PlanTag";
import { useErrorToast, useToast } from "@/components/Toast";
import { Badge, Button, Card, PageHeader, Spinner } from "@/components/ui";
import { relativeTime } from "@/lib/format";

/** A code is shown with the minutes it still works. */
function useMinutesLeft(until: string | null): number {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = window.setInterval(() => setNow(Date.now()), 5_000); return () => window.clearInterval(t); }, []);
  return until ? Math.max(0, Math.ceil((new Date(until).getTime() - now) / 60_000)) : 0;
}

function DeviceRow({ device, onRemove, removing }: { device: HelperDevice; onRemove: () => void; removing: boolean }) {
  const tone = device.paused ? "warning" : device.online ? "success" : "neutral";
  const label = device.paused ? "Paused" : device.online ? "On" : "Off";
  return <div className="helper-device">
    <span className="helper-device-icon"><Icon name={device.platform === "mac" ? "sun" : "grid"}/></span>
    <div className="helper-device-main">
      <strong>{device.name}</strong>
      <span>{device.platform === "mac" ? "Mac" : device.platform === "windows" ? "Windows" : "Computer"}{device.version ? ` · v${device.version}` : ""} · {device.online ? "heard from just now" : device.last_seen_at ? `last heard from ${relativeTime(device.last_seen_at, { suffix: true })}` : "not heard from yet"}</span>
      {device.outdated && <span className="form-note warn">A newer PC Helper is ready: download it again from this page.</span>}
    </div>
    <Badge tone={tone}>{label}</Badge>
    <Button variant="danger" disabled={removing} onClick={() => window.confirm(`Disconnect “${device.name}”? Its key stops working, and its video moves on to the cloud.`) && onRemove()}>Disconnect</Button>
  </div>;
}

/**
 * PC Helper: the member's own computer downloads and edits their videos, so the server carries none of it and
 * YouTube sees a home connection. When the computer is off for three minutes, its video moves on to the cloud.
 */
export default function PCHelper() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const { data, isLoading } = useQuery({ queryKey: ["helper"], queryFn: helper.page, refetchInterval: 10_000 });
  const [code, setCode] = useState<{ code: string; expires_at: string } | null>(null);
  const minutes = useMinutesLeft(code?.expires_at ?? null);
  const makeCode = useMutation({ mutationFn: helper.code, onSuccess: setCode, onError });
  const remove = useMutation({
    mutationFn: (id: number) => helper.remove(id),
    onSuccess: () => { toast({ title: "Computer disconnected" }); queryClient.invalidateQueries({ queryKey: ["helper"] }); },
    onError,
  });
  // A code that was used: the new computer shows up in the list, so the code is put away.
  const count = data?.devices.length ?? 0;
  const [seen, setSeen] = useState(count);
  useEffect(() => { if (count > seen && code) { setCode(null); toast({ title: "Computer connected", message: "It takes your next video now." }); } setSeen(count); }, [count]); // eslint-disable-line react-hooks/exhaustive-deps

  if (isLoading || !data) return <Spinner/>;
  const address = window.location.origin;
  const anyOn = data.devices.some(d => d.online && !d.paused);
  const copy = (text: string) => navigator.clipboard?.writeText(text).then(() => toast({ title: "Copied" }));

  return <><PageHeader title="PC Helper" description="Your own computer downloads and edits your videos: free, quick, and YouTube sees your home internet instead of a server. When your computer is off, your videos are edited in the cloud instead.">
    <Badge tone={anyOn ? "success" : "neutral"}>{anyOn ? "Your PC is editing" : "No PC on"}</Badge></PageHeader>
    <div className="helper-page">

    {!data.allowed && <Card className="helper-locked"><div className="card-title">PC Helper editing <PlanTag feature="pc_editing"/></div>
      <div className="card-caption">Your plan does not include editing on your own computer. Ask the owner to upgrade it.</div></Card>}

    <div className="helper-steps">
      {[["download", "1 · Download", "Get the PC Helper for Windows or Mac and open it. It sits next to the clock."],
        ["link", "2 · Connect", "Press Connect a PC below and type the address and code into the helper's window."],
        ["check", "3 · Done", "Your videos are downloaded and edited on your computer, one at a time, while it is on."]].map(([icon, title, text]) =>
        <Card key={title} className="helper-step"><span className="helper-step-icon"><Icon name={icon as "download"}/></span><strong>{title}</strong><span>{text}</span></Card>)}
    </div>

    <Card><div className="credential-head"><div><div className="card-title">Download the PC Helper</div>
      <div className="card-caption">{`Version ${data.latest_version}. Free, about 60 MB. No admin rights needed; it starts with your computer once connected.`}</div></div></div>
      <div className="helper-downloads">
        {([["Windows 10 / 11", data.download_windows, data.ready_windows], ["Mac (Apple chip)", data.download_mac, data.ready_mac], ["Mac (Intel)", data.download_mac_intel, data.ready_mac_intel]] as const).map(([label, href, ready]) =>
          <a key={label} className={ready ? "button primary" : "button"} href={href} target="_blank" rel="noopener noreferrer" title={ready ? undefined : "Not added by the owner yet"}>
            <Icon name="download"/><span>{label}</span>{!ready && <Badge tone="neutral" dot={false}>Soon</Badge>}</a>)}
      </div>
      <p className="howto" style={{ paddingLeft: 0 }}>On a Mac, the first time: right-click the app, choose Open, then Open again (it is not from the App Store).</p>
    </Card>

    <Card><div className="credential-head"><div><div className="card-title">Connect a PC</div>
      <div className="card-caption">Makes a code that works for 10 minutes. Type it into the PC Helper's window with this address.</div></div>
      <Button variant="primary" icon="plus" disabled={!data.allowed || makeCode.isPending} onClick={() => makeCode.mutate()}>{makeCode.isPending ? "Making a code…" : code ? "New code" : "Connect a PC"}</Button></div>
      {code && minutes > 0 && <div className="helper-code">
        <div><small>ClipRelay address</small><code>{address}</code><Button onClick={() => copy(address)}>Copy</Button></div>
        <div><small>Code</small><code className="big">{code.code}</code><Button onClick={() => copy(code.code)}>Copy</Button></div>
        <span className="muted">{`Works for ${minutes} more minute${minutes === 1 ? "" : "s"}, once.`}</span>
      </div>}
    </Card>

    <Card><div className="card-title">Your computers</div>
      {data.working_on && <div className="form-note">{`Now on your PC: “${data.working_on.title}”`}</div>}
      {data.devices.length
        ? data.devices.map(d => <DeviceRow key={d.id} device={d} removing={remove.isPending} onRemove={() => remove.mutate(d.id)}/>)
        : <div className="card-caption">No computer connected yet.</div>}
    </Card>

    <Card><div className="card-title">When your computer is off</div>
      <div className="card-caption">{data.cloud_allowed && data.cloud_ready
        ? "If your computer is off, asleep or offline for 3 minutes, its video is edited in the cloud instead, so your videos never stop. A video is never made twice."
        : data.cloud_allowed
          ? "Cloud editing is not set up yet, so while your computer is off, new videos cannot be edited and show as failed. Turn the PC Helper on and press Retry."
          : "Your plan has no cloud editing, so while your computer is off, new videos cannot be edited. Keep the PC Helper on."}</div>
    </Card>
    </div>
  </>;
}
