import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { Icon } from "./Icon";
import { Button } from "./ui";

type ToastData = { title: string; message?: string; tone?: "success" | "danger" };
const ToastContext = createContext<(t: ToastData) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<ToastData | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const show = useCallback((t: ToastData) => {
    setToast(t);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setToast(null), 3200);
  }, []);
  return <ToastContext.Provider value={show}>
    {children}
    {toast && <div className="toast" role="status"><div className={toast.tone === "danger" ? "toast-danger" : ""}><Icon name={toast.tone === "danger" ? "alert" : "check"} size={16}/></div><span><strong>{toast.title}</strong>{toast.message}</span><Button variant="ghost" icon="close" onClick={() => setToast(null)}/></div>}
  </ToastContext.Provider>;
}

export const useToast = () => useContext(ToastContext);

/** Convenience: toast an error from a failed mutation. */
export function useErrorToast() {
  const toast = useToast();
  return useCallback((error: unknown) => toast({ title: "Something went wrong", message: error instanceof Error ? error.message : String(error), tone: "danger" }), [toast]);
}
