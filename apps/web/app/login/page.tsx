"use client";

import {
  CheckCircle2,
  DatabaseZap,
  Fingerprint,
  KeyRound,
  LoaderCircle,
  Mail,
  Network,
  ShieldCheck,
} from "lucide-react";
import { GoogleAuthProvider, sendSignInLinkToEmail, signInWithPopup, signOut } from "firebase/auth";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { browserAuth, firebaseConfigured, googleSignInEnabled } from "@/lib/firebase-client";
import { createFirebaseSession } from "@/lib/session-client";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function createDemoSession() {
    const response = await fetch("/api/session", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ demo: true }),
    });
    if (!response.ok) {
      const problem = await response.json().catch(() => null) as { detail?: string } | null;
      throw new Error(problem?.detail ?? "Could not create a secure session.");
    }
    router.push("/dashboard");
    router.refresh();
  }

  async function signInGoogle() {
    setBusy(true);
    setMessage(null);
    try {
      const auth = await browserAuth();
      try {
        const result = await signInWithPopup(auth, new GoogleAuthProvider());
        await createFirebaseSession(result.user);
      } finally {
        await signOut(auth);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Google sign-in failed.");
    } finally {
      setBusy(false);
    }
  }

  async function sendEmailLink(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const auth = await browserAuth();
      await sendSignInLinkToEmail(auth, email, {
        url: `${window.location.origin}/login/complete`,
        handleCodeInApp: true,
      });
      window.localStorage.setItem("emailForSignIn", email);
      setMessage("Check your inbox. The secure link expires automatically.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Email link could not be sent.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-story">
        <div className="brand-lockup large">
          <span className="brand-mark"><Network size={24} strokeWidth={1.8} /></span>
          <span>
            <strong>Ontology</strong>
            <small>Appliance</small>
          </span>
        </div>
        <div className="login-copy">
          <span className="eyebrow light">Semantic control plane</span>
          <h1>Enterprise meaning,<br />made operational.</h1>
          <p>
            Connect evidence once. Discover the language your business already uses.
            Publish governed context that agents can trust.
          </p>
        </div>
        <div className="login-principles">
          <div><DatabaseZap size={19} /><span>Metadata first<strong>Sources remain read-only</strong></span></div>
          <div><ShieldCheck size={19} /><span>Evidence governed<strong>Humans decide high risk</strong></span></div>
          <div><Fingerprint size={19} /><span>Fully reproducible<strong>Every answer carries a trace</strong></span></div>
        </div>
      </section>

      <section className="login-panel-wrap">
        <div className="login-panel">
          <div className="login-panel-heading">
            <span className="status-dot" />
            <span>EU pilot environment</span>
          </div>
          <h2>Enter the workspace</h2>
          <p>Use a verified identity. New members join the pilot tenant with read-only auditor access.</p>

          {firebaseConfigured ? (
            <>
              {googleSignInEnabled && (
                <>
                  <button className="button google" type="button" onClick={signInGoogle} disabled={busy}>
                    {busy ? <LoaderCircle className="spin" size={18} /> : <KeyRound size={18} />}
                    Continue with Google
                  </button>
                  <div className="separator"><span>or use a secure email link</span></div>
                </>
              )}
              <form onSubmit={sendEmailLink} className="email-form">
                <label htmlFor="email">Work email</label>
                <div className="field-with-icon"><Mail size={17} /><input id="email" type="email" required value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@company.com" /></div>
                <button className="button secondary" disabled={busy}>Send sign-in link</button>
              </form>
            </>
          ) : (
            <div className="demo-access">
              <div className="demo-badge"><CheckCircle2 size={17} /> Configuration-safe demo</div>
              <p>Firebase keys are not present, so this local build uses the synthetic <code>demo-bank</code> tenant.</p>
              <button className="button primary" type="button" disabled={busy} onClick={createDemoSession}>
                {busy && <LoaderCircle className="spin" size={18} />}
                Open governed demo
              </button>
            </div>
          )}

          {message && <p className="form-message" role="status">{message}</p>}
          <p className="login-footnote">Session cookies are HTTP-only. Browser clients never receive service credentials.</p>
        </div>
      </section>
    </main>
  );
}
