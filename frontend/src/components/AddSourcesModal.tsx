import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { sources } from "@/api/endpoints";
import { Icon } from "./Icon";
import { useErrorToast, useToast } from "./Toast";
import { Badge, Button } from "./ui";

type Result = Awaited<ReturnType<typeof sources.bulkAdd>>;

export function AddSourcesModal({ close, availableSlots }: { close: () => void; availableSlots: number }) {
  const [method, setMethod] = useState<"username" | "link">("username");
  const [value, setValue] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const entries = Array.from(new Set(value.split(/[\n,]+/).map(entry => entry.trim()).filter(Boolean)));
  const count = Math.min(entries.length, 30, availableSlots);
  const overLimit = entries.length > 30;

  const add = useMutation({
    mutationFn: () => sources.bulkAdd(entries.slice(0, 30)),
    onSuccess: res => {
      setResult(res);
      queryClient.invalidateQueries({ queryKey: ["sources"] });
      queryClient.invalidateQueries({ queryKey: ["nav"] });
      if (res.activated.length && !res.not_authorized.length && !res.invalid.length) {
        toast({ title: "Sources connected", message: `${res.activated.length} Instagram account${res.activated.length === 1 ? "" : "s"} now monitored.` });
        close();
      }
    },
    onError,
  });
  const authorize = useMutation({ mutationFn: sources.oauthStart, onSuccess: r => { window.location.href = r.url; }, onError });

  return <div className="overlay" onMouseDown={close}><div className="modal source-modal" onMouseDown={e => e.stopPropagation()}><div className="modal-head"><div><div className="card-title">Add Instagram accounts</div><div className="card-caption">Connect up to 30 accounts at once. ClipRelay supports 7,000 sources in total.</div></div><Button variant="ghost" icon="close" onClick={close}/></div>
    <div className="connect-methods"><button className={method === "username" ? "active" : ""} onClick={() => { setMethod("username"); setValue(""); setResult(null); }}><span><Icon name="instagram" size={16}/></span><div><strong>By username</strong><small>Primary method · Recommended</small></div>{method === "username" && <Icon name="check" size={14}/>}</button><button className={method === "link" ? "active" : ""} onClick={() => { setMethod("link"); setValue(""); setResult(null); }}><span><Icon name="link" size={16}/></span><div><strong>By profile link</strong><small>For accounts without a username</small></div>{method === "link" && <Icon name="check" size={14}/>}</button></div>
    <div className="bulk-label"><label>{method === "username" ? "Instagram usernames" : "Instagram profile links"}</label><span className={overLimit ? "over" : ""}>{entries.length} / 30</span></div>
    <textarea value={value} onChange={event => { setValue(event.target.value); setResult(null); }} placeholder={method === "username" ? "@slowtravel\n@foundoutside\n@daily.nature\n…up to 30 usernames" : "https://instagram.com/slowtravel\nhttps://instagram.com/profile/789012\n…up to 30 profile links"} autoFocus/>
    <div className={`validation-row ${overLimit ? "invalid" : ""}`}><Icon name={overLimit ? "alert" : "check"} size={15}/>{overLimit ? "Only the first 30 accounts can be connected in one batch" : method === "username" ? "Usernames will be validated and duplicates skipped" : "Links will be resolved, validated, and duplicates skipped"}</div>
    {result && <div className="form-note">
      {result.activated.length > 0 && <div><strong>{result.activated.length} activated:</strong> {result.activated.map(u => `@${u}`).join(", ")}</div>}
      {result.already_active.length > 0 && <div><strong>Already active:</strong> {result.already_active.map(u => `@${u}`).join(", ")}</div>}
      {result.invalid.length > 0 && <div><strong>Invalid:</strong> {result.invalid.join(", ")}</div>}
      {result.not_authorized.length > 0 && <div><strong>{result.not_authorized.length} need authorization:</strong> {result.not_authorized.join(", ")}. ClipRelay uses the official Instagram Graph API, so each Business/Creator account must sign in once with Instagram before it can be monitored.</div>}
    </div>}
    <div className="bulk-summary"><div><strong>{count}</strong><span>Ready to connect</span></div><div><strong>{availableSlots.toLocaleString()}</strong><span>Workspace slots available</span></div><Badge tone="primary" dot={false}>Bulk connection</Badge></div>
    <div className="modal-foot"><Button variant="ghost" icon="instagram" onClick={() => authorize.mutate()} disabled={authorize.isPending}>Authorize with Instagram</Button><span style={{ flex: 1 }}/><Button onClick={close}>Cancel</Button><Button variant="primary" onClick={() => count > 0 && add.mutate()} disabled={!count || add.isPending}>Connect {count || 0} account{count === 1 ? "" : "s"}</Button></div></div></div>;
}
