import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { auth } from "@/api/endpoints";
import { Icon } from "@/components/Icon";
import { Field } from "@/components/Modal";
import { Button, Card } from "@/components/ui";
import { useAuth } from "@/hooks/useAuth";

export default function Login() {
  const { user, login, register } = useAuth();
  const location = useLocation();
  const setup = useQuery({ queryKey: ["auth", "setup"], queryFn: auth.setup });
  const [mode, setMode] = useState<"login" | "register" | null>(null);
  const [form, setForm] = useState({ email: "", password: "", name: "", workspace_name: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Remembered on this device after the first sign-in, so the tick is not needed every time.
  const [accepted, setAccepted] = useState(() => { try { return localStorage.getItem("cliprelay.terms") === "1"; } catch { return false; } });
  const current = mode ?? (setup.data && !setup.data.has_users ? "register" : "login");

  if (user) return <Navigate to={(location.state as { from?: string } | null)?.from ?? "/"} replace/>;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      try { localStorage.setItem("cliprelay.terms", "1"); } catch { /* storage unavailable */ }
      if (current === "login") await login(form.email, form.password, accepted);
      else await register({ ...form, workspace_name: form.workspace_name || "My Workspace", accept_terms: accepted });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  };
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  return <div className="login-page"><Card className="login-card">
    <div className="onboarding-brand"><div className="brand-mark"><Icon name="play" size={16}/></div><span>ClipRelay</span></div>
    <div className="page-title">{current === "login" ? "Welcome back" : setup.data?.has_users ? "Create your account" : "Set up your workspace"}</div>
    <div className="page-subtitle">{current === "login" ? "Sign in to manage your content network." : "Create the first account for this ClipRelay installation."}</div>
    <form onSubmit={submit}>
      {current === "register" && <div className="field-row"><Field label="Your name"><input value={form.name} onChange={set("name")} autoComplete="name"/></Field><Field label="Workspace"><input value={form.workspace_name} onChange={set("workspace_name")} placeholder="Northstar Studio"/></Field></div>}
      <Field label="Email"><input type="email" required value={form.email} onChange={set("email")} autoComplete="email" autoFocus/></Field>
      <Field label="Password" hint={current === "register" ? "At least 8 characters." : undefined}><input type="password" required minLength={current === "register" ? 8 : 1} value={form.password} onChange={set("password")} autoComplete={current === "login" ? "current-password" : "new-password"}/></Field>
      <label className="terms-check"><input type="checkbox" required checked={accepted} onChange={e => setAccepted(e.target.checked)}/><span>I accept the <Link to="/terms" target="_blank">Terms of Use</Link> and the <Link to="/privacy" target="_blank">Privacy Policy</Link>.</span></label>
      <Button type="submit" variant="primary" className="full" disabled={busy || !accepted}>{busy ? "Please wait…" : current === "login" ? "Sign in" : "Create account"}</Button>
      {error && <div className="form-error">{error}</div>}
    </form>
    {setup.data?.registration_open && <div className="login-switch">{current === "login" ? <>No account yet? <button type="button" onClick={() => setMode("register")}>Create one</button></> : <>Already have an account? <button type="button" onClick={() => setMode("login")}>Sign in</button></>}</div>}
  </Card></div>;
}
