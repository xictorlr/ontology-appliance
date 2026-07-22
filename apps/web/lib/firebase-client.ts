"use client";

import { getApp, getApps, initializeApp } from "firebase/app";
import { getAuth, inMemoryPersistence, setPersistence, type Auth } from "firebase/auth";

const config = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
  storageBucket: process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET,
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
};

const explicitFirebaseConfig = Boolean(
  config.apiKey && config.authDomain && config.projectId && config.appId,
);
export const firebaseConfigured =
  explicitFirebaseConfig || process.env.NEXT_PUBLIC_FIREBASE_AUTO_INIT === "true";
export const googleSignInEnabled =
  process.env.NEXT_PUBLIC_GOOGLE_SIGN_IN_ENABLED === "true";

let configuredAuth: Promise<Auth> | undefined;

export function browserAuth(): Promise<Auth> {
  if (!firebaseConfigured) {
    throw new Error("Firebase client configuration is missing.");
  }

  const app = getApps().length
    ? getApp()
    : explicitFirebaseConfig
      ? initializeApp(config)
      : initializeApp();
  const auth = getAuth(app);

  // The application exchanges the short-lived ID token for an HTTP-only
  // session cookie. Keeping Firebase credentials in browser persistence would
  // create a second, unnecessary long-lived session.
  configuredAuth ??= setPersistence(auth, inMemoryPersistence).then(() => auth);
  return configuredAuth;
}
