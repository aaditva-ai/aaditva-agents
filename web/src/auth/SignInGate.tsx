import type { ReactNode } from "react";
import { isFirebaseConfigured } from "../firebase";
import { useAuth } from "./AuthProvider";

/**
 * Blocks the whole app behind Firebase Auth sign-in (plan Step 4). Every
 * broker call needs a Firebase ID token, so there is no useful unauthed
 * state to render beyond this gate.
 *
 * A missing/placeholder Firebase config (VITE_FIREBASE_* env vars -- see
 * the plan's Decisions section on the pending manual Firebase project
 * setup) is checked here via `loading`/`user` from useAuth, which
 * AuthProvider deliberately never resolves out of its initial state when
 * isFirebaseConfigured is false (see AuthProvider.tsx) -- this avoids ever
 * calling into an unconfigured Firebase SDK, which would otherwise throw
 * an uncaught error and white-screen the app.
 */
export function SignInGate({ children }: { children: ReactNode }) {
  const { user, loading, signIn, signInAsGuest } = useAuth();

  if (!isFirebaseConfigured) {
    return (
      <div className="centered-page">
        <h1>Aaditva Campaign Builder</h1>
        <p>
          Firebase is not configured yet. Set <code>VITE_FIREBASE_*</code> in{" "}
          <code>web/.env</code> once Firebase Auth is set up for this project.
        </p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="centered-page">
        <p>Loading…</p>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="centered-page">
        <h1>Aaditva Campaign Builder</h1>
        <p>Sign in to start or view your campaigns.</p>
        <button onClick={() => void signIn()}>Sign in with Google</button>
        <p>
          <button onClick={() => void signInAsGuest()}>Continue as guest</button>
        </p>
        <p className="muted-text">
          Guest sessions are limited to a small number of campaigns — sign
          in with Google for unrestricted use.
        </p>
      </div>
    );
  }

  return <>{children}</>;
}
