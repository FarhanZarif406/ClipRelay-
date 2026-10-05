import { useEffect, useState } from "react";

export function useCountdown(target: string | null | undefined) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  const remaining = target ? Math.max(0, Math.floor((new Date(target).getTime() - now) / 1000)) : 0;
  const pad = (n: number) => String(n).padStart(2, "0");
  return {
    remaining,
    hours: pad(Math.min(99, Math.floor(remaining / 3600))),
    minutes: pad(Math.floor((remaining % 3600) / 60)),
    seconds: pad(remaining % 60),
  };
}
