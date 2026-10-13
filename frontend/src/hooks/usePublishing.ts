import { useQuery } from "@tanstack/react-query";
import { buffer } from "@/api/endpoints";

/** The member's Buffer accounts that are switched on in this workspace, and whether a Buffer key is saved at all. */
export function useBufferChannels() {
  const { data } = useQuery({ queryKey: ["buffer"], queryFn: buffer.info, staleTime: 30_000 });
  return { connected: data?.connected, channels: (data?.channels ?? []).filter(channel => channel.enabled) };
}
