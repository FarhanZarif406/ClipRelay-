/**
 * ClipRelay has two workspaces that share one sign-in: Shorts (the main window) and Podcasts, which opens in
 * its own window under /podcasts. Each has its own channels, publishing accounts, rules and reports.
 * The window's address decides which one it is, so every page and every API call in it belongs to that workspace.
 */
export type Workspace = "shorts" | "podcasts";

const path = window.location.pathname;
export const PODCASTS = path === "/podcasts" || path.startsWith("/podcasts/");
export const MODE: Workspace = PODCASTS ? "podcasts" : "shorts";
/** Router base: inside the Podcasts window "/channels" means "/podcasts/channels". */
export const BASENAME = PODCASTS ? "/podcasts" : "/";

export function openWorkspace(mode: Workspace) {
  window.open(mode === "podcasts" ? "/podcasts" : "/", `cliprelay-${mode}`);
}
