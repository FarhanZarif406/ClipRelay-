import { useCallback, useEffect, useRef, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { dashboard } from "@/api/endpoints";
import { useAuth } from "@/hooks/useAuth";
import { useDismiss } from "@/hooks/useDismiss";
import { useLiveEvents } from "@/hooks/useLiveEvents";
import { useTheme } from "@/hooks/useTheme";
import { initialsOf } from "@/lib/format";
import { PODCASTS, openWorkspace } from "@/lib/mode";
import { Icon, type IconName } from "./Icon";
import { Onboarding } from "./Onboarding";
import { Avatar, Badge } from "./ui";

type NavItem = { label: string; icon: IconName; to: string; open?: "shorts" | "podcasts" };

/** The Podcasts window's own menu. */
const podcastNavigation: NavItem[] = [
  { label: "Dashboard", icon: "grid", to: "/" },
  { label: "Live Status", icon: "clock", to: "/status" },
  { label: "Podcast Channels", icon: "play", to: "/channels" },
  { label: "Review Queue", icon: "check", to: "/review" },
  { label: "Published", icon: "arrow", to: "/published" },
  { label: "Skipped", icon: "filter", to: "/skipped" },
  { label: "Clip Rules", icon: "filter", to: "/rules" },
  { label: "Editing Rules", icon: "code", to: "/editing" },
  { label: "Buffer Settings", icon: "arrow", to: "/buffer" },
  { label: "Daily Report", icon: "logs", to: "/report" },
  { label: "Shorts workspace", icon: "link", to: "", open: "shorts" },
];

const shortsNavigation: NavItem[] = [
  { label: "Dashboard", icon: "grid", to: "/" },
  { label: "Live Status", icon: "clock", to: "/status" },
  { label: "Channels", icon: "play", to: "/channels" },
  { label: "Review Queue", icon: "check", to: "/review" },
  { label: "Published", icon: "arrow", to: "/published" },
  { label: "Skipped", icon: "filter", to: "/skipped" },
  { label: "Editing Rules", icon: "code", to: "/editing" },
  { label: "Integrations", icon: "link", to: "/integrations" },
  { label: "Daily Report", icon: "logs", to: "/report" },
  { label: "Buffer Settings", icon: "arrow", to: "/buffer" },
  { label: "Prompt Studio", icon: "sparkles", to: "/prompts" },
  { label: "Logs", icon: "logs", to: "/logs" },
  { label: "Settings", icon: "settings", to: "/settings" },
  { label: "For Podcasts", icon: "sparkles", to: "", open: "podcasts" },
];

const allNavigation = PODCASTS ? podcastNavigation : shortsNavigation;
/** Pages only the admin has: the API keys. */
const ADMIN_ONLY = ["/integrations"];

const DOCS_URL = (import.meta.env.VITE_DOCS_URL as string | undefined) ?? "/api/docs";

export function Layout() {
  const { user, logout } = useAuth();
  const navigation = allNavigation.filter(n => user?.role === "owner" || !ADMIN_ONLY.includes(n.to));
  const { theme, setTheme } = useTheme();
  const [menu, setMenu] = useState(false);
  const [onboarding, setOnboarding] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [search, setSearch] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const profileRef = useRef<HTMLDivElement>(null);
  useDismiss(profileRef, profileOpen, useCallback(() => setProfileOpen(false), []));
  const navigate = useNavigate();
  const location = useLocation();

  useLiveEvents(!!user);
  const nav = useQuery({ queryKey: ["nav"], queryFn: dashboard.nav, refetchInterval: 30_000 });

  useEffect(() => { setMenu(false); setProfileOpen(false); window.scrollTo(0, 0); }, [location.pathname]);
  useEffect(() => {
    if (!PODCASTS && nav.data && !nav.data.onboarding_completed && !nav.data.buffer_connected && !sessionStorage.getItem("cliprelay.onboarding.seen")) {
      sessionStorage.setItem("cliprelay.onboarding.seen", "1");
      setOnboarding(true);
    }
  }, [nav.data]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); searchRef.current?.focus(); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const name = user?.name || user?.email || "";

  return <div className="app-shell">
    <aside className={`sidebar ${menu ? "open" : ""}`}><div className="brand"><div className="brand-mark"><Icon name="play" size={15}/></div><span>ClipRelay</span><Badge tone="primary" dot={false}>{PODCASTS ? "PODCASTS" : "BETA"}</Badge><button className="mobile-close" onClick={() => setMenu(false)}><Icon name="close"/></button></div>
      <nav>{navigation.map(n => { if (n.open) return <button key={n.label} className="nav-window" title="Opens in its own window" onClick={() => openWorkspace(n.open!)}><Icon name={n.icon}/><span>{n.label}</span><Icon name="arrow" size={13}/></button>; const active = n.to === "/" ? location.pathname === "/" : location.pathname.startsWith(n.to); return <button key={n.to} className={active ? "active" : ""} aria-current={active ? "page" : undefined} onClick={() => navigate(n.to)}><Icon name={n.icon}/><span>{n.label}</span>{n.to === "/published" && !!nav.data?.failed_jobs && <b title="Failed videos">{nav.data.failed_jobs}</b>}{n.to === "/review" && !!nav.data?.review_jobs && <b>{nav.data.review_jobs}</b>}{n.to === "/status" && !!nav.data?.pending_jobs && <b title="In progress">{nav.data.pending_jobs}</b>}{n.to === "/skipped" && !!nav.data?.skipped_videos && <b>{nav.data.skipped_videos}</b>}</button>; })}</nav>
      <div className="sidebar-bottom">
        <a className="help" href={DOCS_URL} target="_blank" rel="noreferrer" style={{ textDecoration: "none" }}><Icon name="alert" size={16}/><div><strong>Need help?</strong><span>View documentation</span></div><Icon name="chevron" size={14}/></a>
        <div className="legal-links"><a href="/terms" target="_blank" rel="noreferrer">Terms</a><a href="/privacy" target="_blank" rel="noreferrer">Privacy</a></div></div>
    </aside>
    <div className="workspace"><header className="topbar"><button className="menu-button" onClick={() => setMenu(true)}><Icon name="menu"/></button><div className="mobile-brand"><div className="brand-mark"><Icon name="play" size={13}/></div>ClipRelay</div>
      <form className="global-search" onSubmit={e => { e.preventDefault(); navigate(`/published?q=${encodeURIComponent(search)}`); }}><Icon name="search" size={17}/><input ref={searchRef} value={search} onChange={e => setSearch(e.target.value)} placeholder={PODCASTS ? "Search clips, accounts…" : "Search videos, accounts…"}/><kbd>⌘ K</kbd></form>
      <div className="top-actions">
        <button className="theme-button" aria-label="Toggle theme" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}><Icon name={theme === "dark" ? "sun" : "moon"} size={17}/></button>
        <div className="menu-anchor profile-anchor" ref={profileRef}><button className="profile" onClick={() => setProfileOpen(o => !o)}><Avatar label={initialsOf(name)} color="violet"/><div><strong>{name}</strong><span>{user?.workspace_name}</span></div><Icon name="chevron" size={14}/></button>
          {profileOpen && <div className="menu-pop right"><div className="menu-head"><strong>{name}</strong><span>{user?.email}</span></div><button onClick={() => (PODCASTS ? window.open("/settings", "cliprelay-shorts") : navigate("/settings"))}><Icon name="settings" size={14}/><span>Settings</span></button><button className="danger" onClick={logout}><Icon name="arrow" size={14}/><span>Sign out</span></button></div>}
        </div>
      </div></header><main><Outlet context={{ openOnboarding: () => setOnboarding(true) }}/></main></div>
    {menu && <div className="sidebar-scrim" onClick={() => setMenu(false)}/>}
    {onboarding && <Onboarding close={() => setOnboarding(false)}/>}
  </div>;
}
