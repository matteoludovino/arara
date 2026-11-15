import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Navigate, NavLink, Outlet, useLocation, useNavigate } from 'react-router';
import { api } from '../lib/api';
import { useSession } from '../lib/session';
import { navFor } from './nav';

function LocationPicker() {
  const { me, location, setLocation } = useSession();
  if (me.locations.length <= 1) return location ? <p className="truncate px-2 text-xs text-stone-500">{location.name}</p> : null;
  return (
    <select
      aria-label="Loja"
      value={location?.id ?? ''}
      onChange={(e) => setLocation(Number(e.target.value))}
      className="w-full rounded-lg border border-stone-300 bg-white px-2 py-1.5 text-sm"
    >
      {me.locations.map((l) => (
        <option key={l.id} value={l.id}>
          {l.name}
        </option>
      ))}
    </select>
  );
}

export function Layout() {
  const { me, can } = useSession();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const items = navFor(can);
  const current = items.find((i) => pathname.startsWith(i.to))?.to ?? '';
  const client = useQueryClient();
  const signOut = useMutation({
    mutationFn: () => api.post('/auth/logout'),
    onSettled: () => {
      client.clear();
      navigate('/entrar', { replace: true });
    },
  });
  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-stone-200 bg-white px-4 py-6 md:flex print:hidden">
        <p className="px-2 text-xl font-bold tracking-tight text-brand-700">Arara</p>
        <div className="mt-3">
          <LocationPicker />
        </div>
        <nav className="mt-6 flex flex-1 flex-col gap-1">
          {items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `rounded-lg px-3 py-2 text-sm font-medium ${isActive ? 'bg-brand-50 text-brand-700' : 'text-stone-600 hover:bg-stone-100'}`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-stone-200 pt-4">
          <p className="truncate px-2 text-sm font-medium text-stone-800">{me.name}</p>
          <p className="px-2 text-xs text-stone-500">{me.role_label}</p>
          <button
            type="button"
            onClick={() => signOut.mutate()}
            className="mt-3 w-full rounded-lg px-2 py-1.5 text-left text-sm text-stone-600 hover:bg-stone-100"
          >
            Sair
          </button>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-3 border-b border-stone-200 bg-white px-4 py-3 md:hidden print:hidden">
          <span className="font-bold text-brand-700">Arara</span>
          <div className="flex gap-2">
            <LocationPicker />
            <select
              aria-label="Navegação"
              className="rounded border border-stone-300 px-2 py-1 text-sm"
              onChange={(e) => navigate(e.target.value)}
              value={current}
            >
              <option value="" disabled>
                Menu
              </option>
              {items.map((i) => (
                <option key={i.to} value={i.to}>
                  {i.label}
                </option>
              ))}
            </select>
            <button type="button" onClick={() => signOut.mutate()} className="rounded px-2 py-1 text-sm text-stone-600 hover:bg-stone-100">
              Sair
            </button>
          </div>
        </header>
        <main className="flex-1 p-4 md:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

/** The landing page: the first screen this person may use. */
export function Home() {
  const { can } = useSession();
  // Owners and managers start at the numbers; everyone else at their first tool (the till, stock).
  const first = can('reports.sales') ? { to: '/relatorios' } : navFor(can)[0];
  return first ? <Navigate to={first.to} /> : <p className="text-sm text-stone-500">Nenhuma área disponível para o seu perfil.</p>;
}
