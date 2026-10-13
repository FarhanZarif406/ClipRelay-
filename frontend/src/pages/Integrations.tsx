import { Navigate } from "react-router-dom";
import { AIModels } from "@/components/AIModels";
import { VideoSource } from "@/components/VideoSource";
import { PushNotificationsCard, YouTubeApiCard } from "@/components/YouTubeCards";
import { Card, PageHeader } from "@/components/ui";
import { useAuth } from "@/hooks/useAuth";
import { OtherIntegrations } from "@/pages/Settings";

export default function Integrations() {
  const { user } = useAuth();
  const isOwner = user?.role === "owner";

  if (!isOwner) return <Navigate to="/" replace/>;  // API keys are the admin's only

  return <><PageHeader title="Integrations" description="Everything ClipRelay connects to: YouTube, the AI model, the downloader and the editor. Publishing accounts are under Buffer Settings."/>
    <div className="narrow-page">
      {!isOwner && <div className="form-note" style={{ marginTop: 0 }}>Only workspace owners can view or change keys.</div>}

      <div className="section-label">1 · YouTube (detecting new uploads)</div>
      <YouTubeApiCard/>
      <PushNotificationsCard/>

      <div className="section-label">2 · AI model for captions (Gemini)</div>
      <Card><div className="card-title">How to get the Gemini key</div>
        <ol className="howto">
          <li>Open <a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer">aistudio.google.com/apikey</a> and click <strong>Create API key</strong>.</li>
          <li>Below, click <strong>Add model</strong>, choose the provider <strong>gemini</strong>, paste the key and click Validate.</li>
          <li>Pick a <strong>Flash</strong> model from the list (for example <code>gemini-2.5-flash</code>) and save it as the default.</li>
        </ol>
        <p className="howto" style={{ paddingLeft: 0 }}>Without a model, videos still go through: the original YouTube title and the fallback hashtags are used, and the video is marked “caption fallback”.</p></Card>
      <AIModels isOwner={isOwner}/>

      <div className="section-label">3 · Video source (the downloader)</div>
      <VideoSource/>

      <div className="section-label">4 · Editor and storage (already installed)</div>
      <OtherIntegrations isOwner={isOwner}/>
    </div>
  </>;
}
