import { initializeApp } from "firebase/app";
import { getAuth, GoogleAuthProvider } from "firebase/auth";

// Values are public client identifiers, not secrets (Firebase's own docs:
// https://firebase.google.com/docs/projects/api-keys) -- safe to ship in a
// static bundle. All come from Vite env vars so the SPA can be built once
// and deployed against different Firebase projects without a code change.
const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};

export const isFirebaseConfigured = Boolean(
  firebaseConfig.apiKey && firebaseConfig.authDomain && firebaseConfig.projectId,
);

// A missing/placeholder config (e.g. before Firebase project setup is
// complete -- see the plan's Decisions section) would otherwise throw an
// uncaught "auth/invalid-api-key" during Firebase's own init and white-
// screen the app with no explanation. SignInGate checks
// isFirebaseConfigured and renders a clear message instead of mounting
// AuthProvider at all in that case, so this module only actually calls
// initializeApp/getAuth when the config looks real.
export const firebaseApp = isFirebaseConfigured ? initializeApp(firebaseConfig) : null;
export const auth = firebaseApp ? getAuth(firebaseApp) : null;
export const googleAuthProvider = new GoogleAuthProvider();
