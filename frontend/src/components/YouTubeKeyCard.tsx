import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { myKeys } from "@/api/endpoints";
import { SecretInput } from "./CredentialCard";
import { Field } from "./Modal";
import { useErrorToast, useToast } from "./Toast";
import { Button, Card } from "./ui";

/** A member's own YouTube Data API key. Optional: without one, videos are looked up through yt-dlp, which needs no key. */
export function YouTubeKeyCard({ forUser }: { forUser?: number }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const onError = useErrorToast();
  const queryKey = ["my-youtube-key", forUser ?? "mine"];
  const { data } = useQuery({ queryKey, queryFn: () => myKeys.youtube(forUser) });
  const [key, setKey] = useState("");
  const save = useMutation({ mutationFn: () => myKeys.saveYoutube(key.trim(), forUser), onSuccess: d => { queryClient.setQueryData(queryKey, d); setKey(""); toast({ title: "Google accepted the key" }); }, onError });
  const remove = useMutation({ mutationFn: () => myKeys.removeYoutube(forUser), onSuccess: d => { queryClient.setQueryData(queryKey, d); toast({ title: "YouTube key removed" }); }, onError });
  return <Card><div className="card-title">YouTube Data API key</div>
    <div className="card-caption">Optional. With a key, new videos are read through Google's API (it has a free daily quota). Without one they are read through yt-dlp, which needs no key. Create it in Google Cloud → APIs &amp; Services → Credentials, with the YouTube Data API v3 switched on.</div>
    {data?.has_key
      ? <div className="source-secret" style={{ marginTop: 12 }}><div><code>••••••••••••{data.key_last4}</code><small>Saved · kept on the server, never shown again</small></div><Button variant="danger" disabled={remove.isPending} onClick={() => window.confirm("Remove this YouTube key?") && remove.mutate()}>Remove</Button></div>
      : <form style={{ marginTop: 12 }} onSubmit={e => { e.preventDefault(); if (key.trim()) save.mutate(); }}>
        <Field label="API key" hint="The key is checked with Google before it is saved."><SecretInput value={key} onChange={setKey} placeholder="Paste a YouTube Data API key"/></Field>
        <div className="inline-form"><Button variant="primary" type="submit" disabled={!key.trim() || save.isPending}>{save.isPending ? "Checking with Google…" : "Save key"}</Button></div></form>}
  </Card>;
}
