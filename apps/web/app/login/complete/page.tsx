"use client";

import { isSignInWithEmailLink, signInWithEmailLink, signOut } from "firebase/auth";
import { LoaderCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { browserAuth } from "@/lib/firebase-client";

export default function CompleteEmailLoginPage() {
  const router = useRouter();
  const [message, setMessage] = useState("Verifying your secure link…");

  useEffect(() => {
    async function complete() {
      try {
        const auth = await browserAuth();
        if (!isSignInWithEmailLink(auth, window.location.href)) throw new Error("This sign-in link is invalid or expired.");
        const email = window.localStorage.getItem("emailForSignIn");
        if (!email) throw new Error("Open this link in the browser where you requested it.");
        const result = await signInWithEmailLink(auth, email, window.location.href);
        const response = await fetch("/api/session", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ idToken: await result.user.getIdToken(true) }),
        });
        if (!response.ok) {
          const problem = await response.json().catch(() => null) as { detail?: string } | null;
          throw new Error(problem?.detail ?? "Could not create a secure session.");
        }
        await signOut(auth);
        window.localStorage.removeItem("emailForSignIn");
        router.replace("/dashboard");
        router.refresh();
      } catch (error) {
        setMessage(error instanceof Error ? error.message : "Sign-in failed.");
      }
    }
    void complete();
  }, [router]);

  return <main className="centered-page"><div className="empty-state"><LoaderCircle className="spin" /><h1>Completing sign-in</h1><p>{message}</p></div></main>;
}
