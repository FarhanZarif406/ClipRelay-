import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { settings, tiktok } from "@/api/endpoints";
import type { TikTokAccount } from "@/api/types";
import { AccountHealthDrawer, AccountSettingsModal } from "@/components/AccountDrawers";
import { Icon } from "@/components/Icon";
import { Menu } from "@/components/Menu";
import { useErrorToast, useToast } from "@/components/Toast";
import { Avatar, Badge, Button, Card, PageHeader, VideoThumb } from "@/components/ui";
import { ACCOUNT_STATUS } from "@/lib/format";

export default function TikTokAccounts() {
  const [params, setParams] = useSearchParams();
  const [panel, setPanel] = useState<{ kind: "health" | "settings"; account: TikTokAccount } | null>(null);
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const { data } = useQuery({ queryKey: ["tiktok"], queryFn: tiktok.list });
  const routes = useQuery({ queryKey: ["tiktok", "routes"], queryFn: tiktok.routes });
  const policy = useQuery({ queryKey: ["policy"], queryFn: settings.policy });
  const accounts = data?.items ?? [];
  const max = data?.capacity ?? 20;

  useEffect(() => {
    const connected = params.get("connected");
    const error = params.get("error");
    if (connected) toast({ title: "TikTok connected", message: `@${connected} can now receive videos.` });
    if (error) toast({ title: "TikTok connection failed", message: error, tone: "danger" });
    if (connected || error) setParams({}, { replace: true });
  }, [params, setParams, toast]);

  const connect = useMutation({ mutationFn: tiktok.oauthStart, onSuccess: r => { window.location.href = r.url; }, onError });
  const disconnect = useMutation({
    mutationFn: (a: TikTokAccount) => tiktok.disconnect(a.id),
    onSuccess: (_, a) => { toast({ title: "Account disconnected", message: `@${a.username} was removed.` }); queryClient.invalidateQueries(); },
    onError,
  });
  const askDisconnect = (a: TikTokAccount) => { if (window.confirm(`Disconnect @${a.username}? Pending uploads to this account will be cancelled.`)) disconnect.mutate(a); };
  const full = accounts.length >= max;
  const guard = policy.data?.unique_video_per_account ?? true;

  return <><PageHeader title="TikTok Accounts" description="Connect up to 20 publishing destinations and manage them at any time."><div className="account-capacity"><strong>{accounts.length}</strong><span>/ {max} linked</span></div><Button icon="plus" variant="primary" onClick={() => connect.mutate()} disabled={full || connect.isPending}>{full ? "Limit reached" : "Connect account"}</Button></PageHeader>
    {policy.data && !policy.data.tiktok_app_audited && <div className="alert-banner"><div className="alert-icon"><Icon name="alert"/></div><div><strong>TikTok app not audited</strong><span>Posts will be private (SELF_ONLY) until the TikTok app passes the Content Posting audit.</span></div></div>}
    <Card className="capacity-card"><div><div className="card-title">Account capacity</div><div className="card-caption">Each connected account receives its own unique video during every parallel publishing run.</div></div><div className="capacity-meter"><i style={{ width: `${(accounts.length / max) * 100}%` }}/></div><strong>{max - accounts.length} slots available</strong></Card>
    <div className="account-grid">{accounts.map(a => { const status = ACCOUNT_STATUS[a.status]; const needsReconnect = a.status === "expired"; return <Card className="account-card" key={a.id}><div className="account-top"><Avatar label={a.initials} color={a.color}/>
      <Menu items={[{ label: "Health & violations", icon: "shield", onSelect: () => setPanel({ kind: "health", account: a }) }, { label: "Settings", icon: "settings", onSelect: () => setPanel({ kind: "settings", account: a }) }, { label: "Reconnect", icon: "refresh", onSelect: () => connect.mutate() }, { label: "Disconnect", icon: "close", danger: true, onSelect: () => askDisconnect(a) }]} trigger={toggle => <Button variant="ghost" icon="more" onClick={toggle}/>}/></div>
      <strong className="account-name">@{a.username}</strong><Badge tone={status.tone}>{status.label}</Badge>
      <div className="meter-row"><span>Posts today</span><strong>{a.posts_today} / {a.daily_cap}</strong></div><div className="meter"><i style={{ width: `${Math.min(100, (a.posts_today / Math.max(1, a.daily_cap)) * 100)}%` }}/></div>
      <div className="account-footer"><span><Icon name="link" size={15}/>{a.sources.length} source{a.sources.length === 1 ? "" : "s"}</span>{needsReconnect ? <Button variant="primary" icon="refresh" onClick={() => connect.mutate()}>Reconnect</Button> : <Button variant="danger" onClick={() => askDisconnect(a)}>Disconnect</Button>}</div></Card>; })}
      {!full && <button className="add-account-card" onClick={() => connect.mutate()}><span><Icon name="plus" size={20}/></span><strong>Connect another account</strong><small>{max - accounts.length} of {max} slots available</small></button>}
    </div>
    <Card className="parallel-card"><div className="parallel-head"><div><div className="card-title">Unique parallel publishing</div><div className="card-caption">One run selects a different eligible Instagram video for every destination, then uploads them simultaneously.</div></div><Badge tone={guard ? "success" : "neutral"}>{guard ? "Duplicate guard on" : "Post to all linked accounts"}</Badge></div>
      <div className="route-grid">{(routes.data ?? []).length === 0 && <div className="route-row" style={{ gridTemplateColumns: "1fr" }}><span className="muted">No videos are queued for publishing right now. New videos appear here once they are rewritten.</span></div>}
        {(routes.data ?? []).slice(0, 3).map((route, index) => <div className="route-row" key={route.job_id}><div className="route-source"><VideoThumb index={index} size={13}/><div><span>UNIQUE VIDEO {index + 1}</span><strong>{route.title || "Untitled video"}</strong><small>@{route.source?.username} · VID-{route.video_id}</small></div></div><div className="route-line"><i/><Icon name="arrow" size={15}/></div><div className="route-target"><Avatar label={route.tiktok_account.initials} color={route.tiktok_account.color}/><div><span>TIKTOK DESTINATION</span><strong>@{route.tiktok_account.username}</strong><small>{route.status === "awaiting_approval" ? "Waiting for approval" : route.status === "uploading" ? "Uploading now" : "Uploads in parallel"}</small></div></div></div>)}</div>
      <div className="duplicate-note"><Icon name="shield" size={17}/><div><strong>Same-video protection</strong><span>ClipRelay reserves each selected video to one account before publishing begins. A video can never be posted to the same account twice — every upload is tracked by its TikTok publish ID.</span></div></div>
    </Card>
    <Card className="oauth-card"><div className="oauth-icon"><Icon name="tiktok" size={24}/></div><div><div className="card-title">Connect securely with TikTok</div><div className="card-caption">Add, disconnect, or replace accounts whenever you choose. ClipRelay only requests permissions to publish and inspect your videos.</div></div><div className="oauth-steps"><span className="done"><i>1</i>Permissions</span><b/><span className={accounts.length ? "done" : ""}><i>2</i>Connect</span><b/><span className={accounts.length ? "done" : ""}><i>3</i>Success</span></div></Card>
    {panel?.kind === "health" && <AccountHealthDrawer account={panel.account} close={() => setPanel(null)}/>}
    {panel?.kind === "settings" && <AccountSettingsModal account={panel.account} close={() => setPanel(null)}/>}
  </>;
}
