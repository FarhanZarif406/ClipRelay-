import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { prompts, settings, tiktok } from "@/api/endpoints";
import { Icon } from "./Icon";
import { Button } from "./ui";

export function Onboarding({ close }: { close: () => void }) {
  const [step, setStep] = useState(1);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const accounts = useQuery({ queryKey: ["tiktok"], queryFn: tiktok.list });
  const promptList = useQuery({ queryKey: ["prompts"], queryFn: prompts.list });
  const policy = useQuery({ queryKey: ["policy"], queryFn: settings.policy });

  const defaultPrompt = promptList.data?.find(p => p.is_default);
  const content: [string, string, string, string, string, string][] = [
    ["Connect TikTok", "Choose where your rewritten videos should be published.", "T", "TikTok account", accounts.data?.items.length ? accounts.data.items.map(a => `@${a.username}`).slice(0, 3).join(", ") : "Connect with TikTok", "/tiktok"],
    ["Set your AI prompt", "Choose how titles, captions, and tags should be rewritten.", "✦", "Prompt", defaultPrompt?.name ?? "Create a prompt", "/prompts"],
    ["Choose a schedule", "Decide when ClipRelay is allowed to publish.", "◷", "Publishing window", policy.data ? `${policy.data.active_window_start}–${policy.data.active_window_end}` : "Set a window", "/rules"],
  ];
  const c = content[step - 1];
  const finish = async () => {
    await settings.completeOnboarding().catch(() => undefined);
    queryClient.invalidateQueries({ queryKey: ["nav"] });
    close();
  };
  return <div className="overlay onboarding-overlay"><div className="onboarding"><div className="onboarding-brand"><div className="brand-mark"><Icon name="play" size={16}/></div><span>ClipRelay</span></div>
    <div className="stepper">{content.map((x, i) => <div className={i + 1 <= step ? "active" : ""} key={x[0]}><i>{i + 1 < step ? <Icon name="check" size={12}/> : i + 1}</i><span>{x[0].split(" ").slice(0, 2).join(" ")}</span></div>)}</div>
    <div className="onboarding-body"><div className="onboarding-icon">{c[2]}</div><div className="onboarding-count">STEP {step} OF {content.length}</div><div className="onboarding-title">{c[0]}</div><p>{c[1]}</p><label>{c[3]}</label>
      <button type="button" className="onboarding-input" style={{ width: "100%", color: "var(--text)", cursor: "pointer" }} onClick={() => { close(); navigate(c[5]); }}>{c[4]}<Icon name="chevron" size={15}/></button></div>
    <div className="onboarding-foot"><Button variant="ghost" onClick={close}>Skip setup</Button><span/><Button onClick={() => setStep(Math.max(1, step - 1))}>Back</Button><Button variant="primary" onClick={() => step === content.length ? finish() : setStep(step + 1)}>{step === content.length ? "Finish setup" : "Continue"} <Icon name="arrow" size={15}/></Button></div>
  </div></div>;
}
