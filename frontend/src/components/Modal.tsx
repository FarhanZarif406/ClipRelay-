import type { ReactNode } from "react";
import { Button } from "./ui";

export function Modal({ title, caption, onClose, children, footer, className = "" }: { title: string; caption?: string; onClose: () => void; children: ReactNode; footer?: ReactNode; className?: string }) {
  return <div className="overlay" onMouseDown={onClose}><div className={`modal ${className}`} role="dialog" aria-modal="true" aria-label={title} onMouseDown={e => e.stopPropagation()}>
    <div className="modal-head"><div><div className="card-title">{title}</div>{caption && <div className="card-caption">{caption}</div>}</div><Button variant="ghost" icon="close" onClick={onClose}/></div>
    {children}
    {footer && <div className="modal-foot">{footer}</div>}
  </div></div>;
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return <div className="field"><label>{label}</label>{children}{hint && <small>{hint}</small>}</div>;
}
