import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { buffer } from "@/api/endpoints";
import { AIModels } from "@/components/AIModels";
import { YouTubeKeyCard } from "@/components/YouTubeKeyCard";
import { Card, PageHeader } from "@/components/ui";

/**
 * A member's own Integrations: every key their videos use, in one place. Owners have the workspace's own
 * Integrations page instead, and never see this one.
 */
export default function MyIntegrations() {
  const { data } = useQuery({ queryKey: ["buffer"], queryFn: buffer.info });
  const keys = data?.keys ?? [];
  return <><PageHeader title="Integrations" description="Your own keys: your videos use only these. The owner does not pay for them, and other members never see them."/>
    <div className="my-integrations">
      <div className="section-label">1 · AI model (captions, hook text, podcast clips)</div>
      <AIModels/>
      <div className="section-label">2 · YouTube Data API key (optional)</div>
      <YouTubeKeyCard/>
      <div className="section-label">3 · Buffer (publishing)</div>
      <Card><div className="credential-head"><div><div className="card-title">Buffer API keys</div>
        <div className="card-caption">{keys.length ? `${keys.length} of ${data?.max_keys ?? "?"} keys saved · ${data?.channels.length ?? 0} accounts connected${data?.max_accounts ? ` (your plan allows ${data.max_accounts})` : ""}.` : "No Buffer key yet: finished videos wait until you add one."}</div></div>
        <Link className="button primary" to="/buffer">Open Buffer Settings</Link></div>
        {keys.map(item => <div className="api-row" key={item.id}><div><strong>{item.label}</strong><span>••••{item.last4} · {item.accounts} account{item.accounts === 1 ? "" : "s"}</span>{item.error && <span className="row-error">{item.error}</span>}</div></div>)}
      </Card>
    </div>
  </>;
}
