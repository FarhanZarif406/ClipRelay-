import type { ReactNode } from "react";
import type { Tone } from "@/api/types";
import { Icon, type IconName } from "./Icon";

export function Button({ children, variant = "secondary", icon, onClick, className = "", disabled, type = "button", title }: {
  children?: ReactNode; variant?: "primary" | "secondary" | "ghost" | "danger"; icon?: IconName; onClick?: () => void; className?: string;
  disabled?: boolean; type?: "button" | "submit"; title?: string;
}) {
  return <button type={type} title={title} disabled={disabled} className={`button ${variant} ${className}`} onClick={onClick}>{icon && <Icon name={icon} size={16}/>} {children}</button>;
}

export function Badge({ children, tone = "neutral", dot = true }: { children: ReactNode; tone?: Tone; dot?: boolean }) {
  return <span className={`badge ${tone}`}>{dot && <i/>}{children}</span>;
}

export function Toggle({ checked = true, onChange, disabled, label = "Toggle" }: { checked?: boolean; onChange?: () => void; disabled?: boolean; label?: string }) {
  return <button type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled} className={`toggle ${checked ? "on" : ""}`} onClick={onChange}><span/></button>;
}

export function Avatar({ label, color = "violet" }: { label: string; color?: string }) {
  return <div className={`avatar ${color}`}>{label}</div>;
}

export function PageHeader({ title, description, children }: { title: string; description: string; children?: ReactNode }) {
  return <div className="page-heading"><div><div className="eyebrow">CLIPRELAY</div><div className="page-title">{title}</div><div className="page-subtitle">{description}</div></div><div className="header-actions">{children}</div></div>;
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`card ${className}`}>{children}</section>;
}

/** 10-day sparkline. Heights follow the design's 4–13 scale (×2px). */
export function MiniBars({ series }: { series: number[] }) {
  const max = Math.max(...series, 1);
  return <div className="mini-bars">{series.map((n, i) => <i key={i} style={{ height: `${Math.max(4, Math.round(4 + (n / max) * 9)) * 2}px` }}/>)}</div>;
}

export function VideoThumb({ index, image, label, size = 14, className = "video-thumb" }: { index: number; image?: string | null; label?: string; size?: number; className?: string }) {
  return <div className={`${className} v${index % 5}`} style={image ? { backgroundImage: `url(${image})`, backgroundSize: "cover", backgroundPosition: "center" } : undefined}><Icon name="play" size={size}/>{label && <span>{label}</span>}</div>;
}

export function Empty({ icon = "sparkles", title, children }: { icon?: IconName; title: string; children?: ReactNode }) {
  return <div className="empty-state"><span><Icon name={icon} size={18}/></span><strong>{title}</strong>{children && <small>{children}</small>}</div>;
}

export function Spinner() {
  return <div className="empty-state loading"><span><Icon name="refresh" size={16}/></span><small>Loading…</small></div>;
}
