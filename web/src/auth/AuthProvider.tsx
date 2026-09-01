import {
  useEffect,
  useState,
  type ReactNode,
} from "react";
import {
  onAuthStateChanged,
  signInAnonymously,
  signInWithPopup,
  signOut,
  type User,
} from "firebase/auth";
import { auth, googleAuthProvider, isFirebaseConfigured } from "../firebase";
import { AuthContext } from "./useAuth";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Without a real Firebase config, `auth` is null (see firebase.ts) and
    // this deliberately never resolves out of the initial loading=true
    // state -- SignInGate checks isFirebaseConfigured before this matters
    // to the user, but skipping the call here is what avoids ever handing
    // an unconfigured SDK instance to Firebase and having it throw.
    if (!auth) return;

    // The single source of truth for sign-in state; fires once on mount
    // with the persisted session (if any), then on every sign-in/out.
    return onAuthStateChanged(auth, (nextUser) => {
      setUser(nextUser);
      setLoading(false);
    });
  }, []);

  const signIn = async () => {
    if (!isFirebaseConfigured || !auth) return;
    await signInWithPopup(auth, googleAuthProvider);
  };

  // Anonymous sessions are subject to a hard, non-refilling lifetime cap
  // on campaign starts/resumes (broker/campaign_limits.py's
  // CAMPAIGN_ANONYMOUS_MAX_TRIGGERS) -- offered as a lower-friction way to
  // try the product without a Google account, at a deliberately tighter
  // usage ceiling.
  const signInAsGuest = async () => {
    if (!isFirebaseConfigured || !auth) return;
    await signInAnonymously(auth);
  };

  const signOutUser = async () => {
    if (!isFirebaseConfigured || !auth) return;
    await signOut(auth);
  };

  return (
    <AuthContext.Provider value={{ user, loading, signIn, signInAsGuest, signOutUser }}>
      {children}
    </AuthContext.Provider>
  );
}
