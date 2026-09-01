import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/useAuth";

export function Layout({ children }: { children: ReactNode }) {
  const { user, signOutUser } = useAuth();

  const userIdentifier = user?.isAnonymous
    ? "Guest Session"
    : user?.displayName ?? user?.email ?? "Signed In";

  return (
    <div className="min-h-screen flex flex-col bg-background text-foreground">
      <header className="sticky top-0 z-50 w-full border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="max-w-5xl mx-auto px-4 h-14 flex items-center justify-between">
          <Link
            to="/"
            className="text-base font-semibold tracking-tight text-foreground hover:text-primary transition-colors flex items-center gap-2"
          >
            <svg
              className="w-5 h-5 text-primary"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z" />
            </svg>
            <span>Aaditva Campaign Builder</span>
          </Link>

          {user && (
            <div className="flex items-center gap-3">
              <span className="text-xs text-muted-foreground hidden sm:inline-block font-medium">
                {userIdentifier}
              </span>
              <button
                onClick={() => void signOutUser()}
                className="px-2.5 py-1 text-xs font-medium text-destructive hover:bg-destructive/10 rounded-md border border-destructive/20 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
                aria-label="Sign out of account"
              >
                Sign out
              </button>
            </div>
          )}
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-6 w-full flex-1 flex flex-col">
        {children}
      </main>
    </div>
  );
}
