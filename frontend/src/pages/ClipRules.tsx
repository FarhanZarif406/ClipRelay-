import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { rules } from "@/api/endpoints";
import { GlobalRules } from "@/components/RulesEditor";
import { Button, Card, PageHeader } from "@/components/ui";

/** The Podcasts workspace's own rules for choosing and cutting clips. How a clip looks is under Editing Rules. */
export default function ClipRules() {
  const navigate = useNavigate();
  const { data } = useQuery({ queryKey: ["rules"], queryFn: rules.get });
  const v = data?.values;

  return <><PageHeader title="Clip Rules" description="How each podcast is turned into short clips. These rules belong to the Podcasts workspace only."/>
    <div className="narrow-page">
      <Card><div className="card-title">What happens to each podcast</div><div className="card-caption">The transcript is read, an AI model picks the most engaging moments, and only those sections are downloaded and edited. Without subtitles or a working AI model, the clips are spread evenly across the video instead.</div>
        <div className="edit-preview">
          <div><span>Clips per podcast</span><strong>{v ? String(v.clips_per_video) : "—"}</strong><span>Each clip becomes one post</span></div>
          <div><span>Clip length</span><strong>{v ? `${v.clip_min_seconds}–${v.clip_max_seconds}s` : "—"}</strong><span>Shortest and longest clip</span></div>
          <div><span>Editing</span><strong>Editing Rules</strong><span>Shape, speed, sound, text, watermark</span></div>
        </div>
        <div className="modal-foot" style={{ justifyContent: "flex-start" }}><Button onClick={() => navigate("/editing")}>Open Editing Rules</Button></div></Card>
      <GlobalRules title="Change the rules" caption="Saved values apply to the next podcast, with no restart. Timezone and file retention are shared with the Shorts workspace and are set there."/>
    </div>
  </>;
}
