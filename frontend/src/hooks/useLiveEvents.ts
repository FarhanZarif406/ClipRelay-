import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiUrl, getToken } from "@/api/client";

/**
 * Subscribes to the backend's Server-Sent Events stream and refreshes cached queries
 * when jobs or activity change. Invalidations are batched to at most one per second.
 */
export function useLiveEvents(enabled: boolean) {
  const queryClient = useQueryClient();
  useEffect(() => {
    const token = getToken();
    if (!enabled || !token) return;
    let source: EventSource | null = null;
    let retry: number | undefined;
    let pending: number | undefined;
    let closed = false;

    const flush = () => {
      pending = undefined;
      ["dashboard", "nav", "jobs", "job", "logs", "buffer", "report"].forEach(key =>
        queryClient.invalidateQueries({ queryKey: [key] }));
    };

    const connect = () => {
      source = new EventSource(apiUrl("/events", { token }));
      source.onmessage = event => {
        try {
          if (JSON.parse(event.data).type === "hello") return;
        } catch {
          return;
        }
        if (pending === undefined) pending = window.setTimeout(flush, 1000);
      };
      source.onerror = () => {
        source?.close();
        if (!closed) retry = window.setTimeout(connect, 5000);
      };
    };
    connect();
    return () => {
      closed = true;
      source?.close();
      window.clearTimeout(retry);
      window.clearTimeout(pending);
    };
  }, [enabled, queryClient]);
}
