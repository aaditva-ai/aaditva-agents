import type { ReactNode } from "react";
import { isFirebaseConfigured } from "../firebase";
import { useAuth } from "./useAuth";

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
      <div className="min-h-screen flex items-center justify-center bg-background px-4 py-8">
        <div className="max-w-md w-full bg-card border border-border rounded-xl shadow-lg p-6 sm:p-8 flex flex-col items-center text-center space-y-4">
          <div className="w-12 h-12 rounded-full bg-yellow-100 dark:bg-yellow-950/40 text-yellow-600 flex items-center justify-center">
            <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
          <h1 className="text-xl font-bold tracking-tight text-foreground">Firebase Configuration Required</h1>
          <p className="text-sm text-muted-foreground leading-relaxed">
            Firebase is not configured yet. Set <code className="px-1.5 py-0.5 rounded bg-muted text-xs font-mono">VITE_FIREBASE_*</code> in{" "}
            <code className="px-1.5 py-0.5 rounded bg-muted text-xs font-mono">web/.env</code> once Firebase Auth is set up for this project.
          </p>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background px-4">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
          <p className="text-sm text-muted-foreground font-medium">Checking authentication…</p>
        </div>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background px-4 py-8">
        <div className="max-w-md w-full bg-card border border-border rounded-xl shadow-lg p-6 sm:p-8 flex flex-col items-center text-center space-y-6">
          <div className="flex flex-col items-center space-y-2">
            <div className="w-12 h-12 rounded-xl bg-primary/10 text-primary flex items-center justify-center mb-1">
              <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z" />
              </svg>
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-foreground">Aaditva Campaign Builder</h1>
            <p className="text-sm text-muted-foreground">Sign in to create, run, and monitor automated AI campaigns.</p>
          </div>

          <div className="w-full space-y-3">
            <button
              type="button"
              onClick={() => void signIn()}
              className="w-full py-2.5 px-4 rounded-lg bg-primary text-primary-foreground font-medium flex items-center justify-center gap-2 shadow-sm hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 transition-all cursor-pointer"
            >
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
                <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
                <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z" />
                <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z" />
              </svg>
              <span>Sign in with Google</span>
            </button>

            <button
              type="button"
              onClick={() => void signInAsGuest()}
              className="w-full py-2.5 px-4 rounded-lg border border-input bg-background text-foreground hover:bg-muted font-medium text-sm flex items-center justify-center gap-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring transition-colors cursor-pointer"
            >
              Continue as guest
            </button>
          </div>

          <p className="text-xs text-muted-foreground bg-muted/40 p-3 rounded-lg border border-border/50 text-center leading-relaxed">
            Guest sessions are limited to a small number of campaigns — sign in with Google for unrestricted use.
          </p>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
