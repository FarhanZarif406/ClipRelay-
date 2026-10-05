import { useEffect, useRef, useState, type ReactNode } from "react";
import { Icon, type IconName } from "./Icon";

export type MenuItem = { label: string; onSelect: () => void; icon?: IconName; danger?: boolean; active?: boolean; disabled?: boolean };

/** Dropdown anchored to its trigger. Closes on outside click / Escape. */
export function Menu({ trigger, items, align = "right", className = "" }: { trigger: (open: () => void) => ReactNode; items: MenuItem[]; align?: "left" | "right"; className?: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);
  return <div className={`menu-anchor ${className}`} ref={ref} onClick={e => e.stopPropagation()}>
    {trigger(() => setOpen(o => !o))}
    {open && <div className={`menu-pop ${align}`} role="menu">{items.map(item => <button type="button" role="menuitem" key={item.label} disabled={item.disabled} className={`${item.danger ? "danger" : ""} ${item.active ? "active" : ""}`} onClick={() => { setOpen(false); item.onSelect(); }}>{item.icon && <Icon name={item.icon} size={14}/>}<span>{item.label}</span>{item.active && <Icon name="check" size={13}/>}</button>)}</div>}
  </div>;
}

/** The design's `.filter-select` button, made functional. */
export function FilterSelect<T extends string>({ value, options, onChange, placeholder }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; placeholder?: string }) {
  const current = options.find(o => o.value === value);
  return <Menu align="left" items={options.map(o => ({ label: o.label, active: o.value === value, onSelect: () => onChange(o.value) }))}
    trigger={toggle => <button type="button" className="filter-select" onClick={toggle}>{current?.label ?? placeholder}<Icon name="chevron" size={13}/></button>}/>;
}
