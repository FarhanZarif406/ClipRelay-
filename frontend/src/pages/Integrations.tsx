import { useQuery } from "@tanstack/react-query";
import { credentials } from "@/api/endpoints";
import { AIModels } from "@/components/AIModels";
import { CredentialCard } from "@/components/CredentialCard";
import { Card, PageHeader } from "@/components/ui";
import { useAuth } from "@/hooks/useAuth";
import { OtherIntegrations } from "@/pages/Settings";

export default function Integrations() {
  const { user } = useAuth();
  const isOwner = user?.role === "owner";
  const { data } = useQuery({ queryKey: ["credentials"], queryFn: credentials.list });
  const card = (group: string) => data?.find(c => c.group === group);
  const tiktokCard = card("tiktok");
  const youtubeCard = card("youtube");

  return <><PageHeader title="Integrations" description="Everything ClipRelay connects to: TikTok, YouTube, the AI model, the downloader and the editor."/>
    <div className="narrow-page">
      {!isOwner && <div className="form-note" style={{ marginTop: 0 }}>Only workspace owners can view or change keys.</div>}

      <div className="section-label">1 · TikTok (required to publish)</div>
      <Card><div className="card-title">How to get the TikTok keys</div>
        <ol className="howto">
          <li>Open <a href="https://developers.tiktok.com/apps" target="_blank" rel="noreferrer">developers.tiktok.com → Manage apps</a> and create an app.</li>
          <li>Add the products <strong>Login Kit</strong> and <strong>Content Posting API</strong>, with the scopes shown in the card below.</li>
          <li>In Login Kit, set the redirect URI to the one shown in the card below (it must match exactly, and TikTok needs HTTPS).</li>
          <li>Copy the <strong>Client key</strong> and <strong>Client secret</strong> into the card, then click Validate and Save.</li>
          <li>Go to <a href="/tiktok">TikTok Accounts</a> and click <strong>Connect account</strong>.</li>
        </ol></Card>
      {tiktokCard && <CredentialCard card={tiktokCard} isOwner={isOwner}/>}

      <div className="section-label">2 · AI model for captions (Gemini)</div>
      <Card><div className="card-title">How to get the Gemini key</div>
        <ol className="howto">
          <li>Open <a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer">aistudio.google.com/apikey</a> and click <strong>Create API key</strong>.</li>
          <li>Below, click <strong>Add model</strong>, choose the provider <strong>gemini</strong>, paste the key and click Validate.</li>
          <li>Pick a <strong>Flash</strong> model from the list (for example <code>gemini-2.5-flash</code>) and save it as the default.</li>
        </ol>
        <p className="howto" style={{ paddingLeft: 0 }}>Without a model, videos still go through: the original YouTube title and the fallback hashtags are used, and the video is marked “caption fallback”.</p></Card>
      <AIModels isOwner={isOwner}/>

      <div className="section-label">3 · YouTube (optional)</div>
      <Card><div className="card-title">YouTube works without a key</div>
        <p className="howto" style={{ paddingLeft: 0 }}>Finding channels, detecting new uploads and downloading all work with no key. A YouTube Data API key only makes channel and video lookups faster and more reliable. To get one: open <a href="https://console.cloud.google.com/apis/library/youtube.googleapis.com" target="_blank" rel="noreferrer">Google Cloud Console → YouTube Data API v3</a>, click Enable, then Credentials → Create credentials → API key, and paste it below.</p></Card>
      {youtubeCard && <CredentialCard card={youtubeCard} isOwner={isOwner}/>}

      <div className="section-label">4 · Downloader and editor (already installed)</div>
      <OtherIntegrations isOwner={isOwner}/>
    </div>
  </>;
}
