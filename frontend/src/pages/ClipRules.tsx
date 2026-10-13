import { useQuery } from "@tanstack/react-query";
import { rules } from "@/api/endpoints";
import { GlobalRules } from "@/components/RulesEditor";
import { Card, PageHeader } from "@/components/ui";

const FRAME: Record<string, [string, string]> = {
  crop: ["Vertical crop", "The middle of the picture fills the 9:16 screen"],
  blur: ["Blurred background", "The whole picture, over a blurred copy of itself"],
  original: ["Original", "The picture is left as it is"],
};

/** The Podcasts workspace's own rules: how clips are chosen, cut and edited. */
export default function ClipRules() {
  const { data } = useQuery({ queryKey: ["rules"], queryFn: rules.get });
  const v = data?.values;
  const frame = FRAME[String(v?.framing ?? "crop")] ?? FRAME.crop;
  const speed = Number(v?.speed ?? 1);

  return <><PageHeader title="Clip Rules" description="How each podcast is turned into short clips. These rules belong to the Podcasts workspace only."/>
    <div className="narrow-page">
      <Card><div className="card-title">What happens to each podcast</div><div className="card-caption">The transcript is read, an AI model picks the most engaging moments, and only those sections are downloaded and edited. Without subtitles or a working AI model, the clips are spread evenly across the video instead.</div>
        <div className="edit-preview">
          <div><span>Clips per podcast</span><strong>{v ? String(v.clips_per_video) : "—"}</strong><span>Each clip becomes one TikTok post</span></div>
          <div><span>Clip length</span><strong>{v ? `${v.clip_min_seconds}–${v.clip_max_seconds}s` : "—"}</strong><span>Shortest and longest clip</span></div>
          <div><span>Frame</span><strong>{frame[0]}</strong><span>{frame[1]}</span></div>
        </div>
        <div className="edit-preview">
          <div><span>Speed</span><strong>{speed === 1 ? "Unchanged" : `${speed}x`}</strong><span>{speed === 1 ? "Original pace" : "Video and audio together"}</span></div>
          <div><span>Horizontal flip</span><strong>{v?.horizontal_flip ? "On" : "Off"}</strong><span>{v?.horizontal_flip ? "Mirrored left to right" : "Not mirrored"}</span></div>
          <div><span>Audio</span><strong>{v?.keep_audio === false ? "Removed" : "Kept"}</strong><span>{v?.keep_audio === false ? "The clip is silent" : "The original sound"}</span></div>
        </div></Card>
      <GlobalRules title="Change the rules" caption="Saved values apply to the next podcast, with no restart. Timezone, publish mode and file retention are shared with the Shorts workspace and are set there."/>
    </div>
  </>;
}
