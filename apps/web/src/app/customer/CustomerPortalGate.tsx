"use client";

import { createContext, FormEvent, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import Link from "next/link";

type CustomerSession = { email: string; role: string };
const CustomerSessionContext = createContext<CustomerSession | null>(null);

export function useCustomerSession(): CustomerSession {
  const session = useContext(CustomerSessionContext);
  if (!session) throw new Error("CustomerPortalGate is required for customer portal pages.");
  return session;
}

function responseMessage(payload: unknown, fallback: string): string {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  if (payload && typeof payload === "object" && "message" in payload) {
    const message = (payload as { message?: unknown }).message;
    if (typeof message === "string") return message;
  }
  return fallback;
}

export default function CustomerPortalGate({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<CustomerSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [email, setEmail] = useState("");
  const [challengeId, setChallengeId] = useState("");
  const [code, setCode] = useState("");
  const [sendingCode, setSendingCode] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const loadSession = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch("/api/customer/auth/session", { cache: "no-store" });
      if (!response.ok) {
        setSession(null);
        return;
      }
      const value = await response.json() as CustomerSession;
      if (value.role !== "ROLE_CUSTOMER") {
        await fetch("/api/customer/auth/logout", { method: "POST" });
        setSession(null);
        setError("This portal is for customer accounts. Sign in with your customer email.");
        return;
      }
      setSession(value);
      setEmail(value.email);
    } catch {
      setSession(null);
      setError("Unable to reach the sign-in service. Please try again.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSession();
  }, [loadSession]);

  async function requestCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setNotice("");
    setSendingCode(true);
    try {
      const response = await fetch("/api/customer/auth/otp/request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim(), role: "CUSTOMER" }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(responseMessage(payload, "Could not send a verification code."));
      setChallengeId(payload.challenge_id);
      setNotice("If this email is eligible, a one-time sign-in code has been sent.");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not send a verification code.");
    } finally {
      setSendingCode(false);
    }
  }

  async function verifyCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSendingCode(true);
    try {
      const response = await fetch("/api/customer/auth/otp/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ challenge_id: challengeId, code: code.trim() }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(responseMessage(payload, "That code could not be verified."));
      await loadSession();
    } catch (verifyError) {
      setError(verifyError instanceof Error ? verifyError.message : "That code could not be verified.");
    } finally {
      setSendingCode(false);
    }
  }

  async function signOut() {
    setError("");
    try {
      const response = await fetch("/api/customer/auth/logout", { method: "POST" });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        setError(responseMessage(payload, "Could not sign out. Please try again."));
        return;
      }
      setSession(null);
      setChallengeId("");
      setCode("");
      setNotice("");
    } catch {
      setError("Could not reach the sign-in service to sign out.");
    }
  }

  if (loading) {
    return <main className="auth-shell" aria-live="polite"><p>Checking your secure session…</p></main>;
  }
  if (session) {
    return <CustomerSessionContext.Provider value={session}>
      <div className="session-bar">
        <Link href="/" className="session-brand">WINGED TYCOONS</Link>
        <span>Signed in as <strong>{session.email}</strong></span>
        <button type="button" className="session-signout" onClick={signOut}>Sign out</button>
      </div>
      {error && <p className="error session-error" role="alert">{error}</p>}
      {children}
    </CustomerSessionContext.Provider>;
  }

  return (
    <main className="auth-shell">
      <section className="auth-card" aria-labelledby="signin-title">
        <Link href="/" className="session-brand">WINGED TYCOONS</Link>
        <p className="eyebrow">Customer portal</p>
        <h1 id="signin-title">Sign in with your email</h1>
        <p>We’ll email you a one-time code. No password is needed.</p>
        {!challengeId ? (
          <form onSubmit={requestCode}>
            <label htmlFor="signin-email">Work email</label>
            <input id="signin-email" type="email" autoComplete="email" required value={email} onChange={event => setEmail(event.target.value)} />
            <button className="primary" type="submit" disabled={sendingCode}>{sendingCode ? "Sending…" : "Email me a code"}</button>
          </form>
        ) : (
          <form onSubmit={verifyCode}>
            <p className="auth-recipient">Code sent to <strong>{email}</strong></p>
            <label htmlFor="signin-code">One-time code</label>
            <input id="signin-code" inputMode="numeric" autoComplete="one-time-code" minLength={6} maxLength={12} required value={code} onChange={event => setCode(event.target.value)} />
            <button className="primary" type="submit" disabled={sendingCode}>{sendingCode ? "Verifying…" : "Verify and continue"}</button>
            <button className="text-button" type="button" onClick={() => { setChallengeId(""); setCode(""); setNotice(""); }}>Use a different email</button>
          </form>
        )}
        {notice && <p className="auth-notice" role="status">{notice}</p>}
        {error && <p className="error" role="alert">{error}</p>}
      </section>
    </main>
  );
}
