import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { rules } from "@/api/endpoints";
import { GlobalRules } from "@/components/RulesEditor";
import { Button, Card, PageHeader } from "@/components/ui";

export default function EditingRules() {
  const navigate = useNavigate();
  const { data } = useQuery({ queryKey: ["rules"], queryFn: rules.get });
  const v = data?.values;
  const speed = Number(v?.speed ?? 1.08);

  return <><PageHeader title="Editing Rules" description="The edit every video gets before it is published. Deliberately minimal: a speed-up and a flip."/>
    <div className="narrow-page">
      <Card><div className="card-title">What happens to each video</div><div className="card-caption">The editor (FFmpeg) applies these values to the next video. Nothing else is changed: no cropping, no trimming, no watermark, no text, no music.</div>
        <div className="edit-preview">
          <div><span>Speed</span><strong>{speed === 1 ? "Unchanged" : `${speed}x`}</strong><span>{speed === 1 ? "Original length" : `A 30s video becomes ${(30 / speed).toFixed(1)}s`}</span></div>
          <div><span>Horizontal flip</span><strong>{v?.horizontal_flip ? "On" : "Off"}</strong><span>{v?.horizontal_flip ? "Mirrored left to right" : "Not mirrored"}</span></div>
          <div><span>Audio</span><strong>{v?.keep_audio ? "Kept" : "Removed"}</strong><span>{v?.keep_audio ? "Sped up with the video, pitch stays natural" : "The output is silent"}</span></div>
        </div></Card>
      <GlobalRules groups={["Editing"]} title="Change the edit" caption="Saved values apply to the next video, with no restart. The output keeps the source resolution and frame rate (H.264 / AAC, MP4)."/>
      <Card><div className="card-title">Different edit for one channel?</div><div className="card-caption">Any of these can be overridden per channel, and every change is recorded with who made it and when.</div>
        <div className="modal-foot" style={{ justifyContent: "flex-start" }}><Button onClick={() => navigate("/settings")}>Open Settings → Channel overrides</Button></div></Card>
    </div>
  </>;
}
