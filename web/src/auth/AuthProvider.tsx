import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { onAuthStateChanged, signInWithPopup, signOut, type User } from "firebase/auth";
import { auth, googleAuthProvider, isFirebaseConfigured } from "../firebase";

type AuthState = {
  user: User | null;
  loading: boolean;
  signIn: () => Promise<void>;
  signOutUser: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

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

  const signOutUser = async () => {
    if (!isFirebaseConfigured || !auth) return;
    await signOut(auth);
  };

  return (
    <AuthContext.Provider value={{ user, loading, signIn, signOutUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
