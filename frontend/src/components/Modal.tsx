import type { ReactNode } from "react";
import { Button } from "./ui";

export function Modal({ title, caption, onClose, children, footer, className = "" }: { title: string; caption?: string; onClose: () => void; children: ReactNode; footer?: ReactNode; className?: string }) {
  return <div className="overlay" onMouseDown={onClose}><div className={`modal ${className}`} role="dialog" aria-modal="true" aria-label={title} onMouseDown={e => e.stopPropagation()}>
    <div className="modal-head"><div><div className="card-title">{title}</div>{caption && <div className="card-caption">{caption}</div>}</div><Button variant="ghost" icon="close" onClick={onClose}/></div>
    {children}
    {footer && <div className="modal-foot">{footer}</div>}
  </div></div>;
}

/** A labelled control. `tag` goes next to the label, e.g. the plan an option needs. */
export function Field({ label, children, hint, tag }: { label: string; children: ReactNode; hint?: string; tag?: ReactNode }) {
  return <div className="field"><label>{label}{tag}</label>{children}{hint && <small>{hint}</small>}</div>;
}
