import { useQuery } from '@tanstack/react-query';
import { createContext, type ReactNode, use, useState } from 'react';
import { Navigate, useLocation } from 'react-router';
import { api, ApiError } from './api';
import type { Capability, LocationRef, Me } from './types';

interface Session {
  me: Me;
  can: (capability: Capability) => boolean;
  /** The store or warehouse this screen works at; the user picks it once, it's remembered. */
  location: LocationRef | null;
  setLocation: (id: number) => void;
}

const SessionContext = createContext<Session | null>(null);

/** Who is signed in; null when signed out (the API answers 401 or 403). */
export function useMeQuery() {
  return useQuery({
    queryKey: ['me'],
    queryFn: async (): Promise<Me | null> => {
      try {
        return await api.get<Me>('/auth/me');
      } catch (error) {
        if (error instanceof ApiError && (error.status === 401 || error.status === 403)) return null;
        throw error;
      }
    },
    staleTime: 60_000,
  });
}

export function useSession(): Session {
  const session = use(SessionContext);
  if (!session) throw new Error('useSession outside a signed-in route');
  return session;
}

const storageKey = (me: Me) => `arara.location.${me.id}`;

function remembered(me: Me): number | null {
  try {
    return Number(localStorage.getItem(storageKey(me))) || null;
  } catch {
    return null;
  }
}

function SessionProvider({ me, children }: { me: Me; children: ReactNode }) {
  const [chosen, setChosen] = useState<number | null>(() => remembered(me));
  const location = me.locations.find((l) => l.id === chosen) ?? me.locations[0] ?? null;
  const setLocation = (id: number) => {
    setChosen(id);
    try {
      localStorage.setItem(storageKey(me), String(id));
    } catch {
      // Private window: the choice lasts for this tab only.
    }
  };
  const can = (capability: Capability) => me.capabilities.includes(capability);
  return <SessionContext value={{ me, can, location, setLocation }}>{children}</SessionContext>;
}

/** Signed-in routes: anyone else goes to the sign-in page, and comes back here afterwards. */
export function RequireSession({ children }: { children: ReactNode }) {
  const { data, isPending, error } = useMeQuery();
  const location = useLocation();
  if (isPending) return <p className="p-10 text-center text-sm text-stone-500">Carregando…</p>;
  if (error) return <p className="p-10 text-center text-sm text-red-700">Não foi possível falar com o servidor.</p>;
  if (!data) return <Navigate to="/entrar" replace state={{ from: location.pathname }} />;
  return <SessionProvider me={data}>{children}</SessionProvider>;
}
