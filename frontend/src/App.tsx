import { createBrowserRouter, Navigate } from 'react-router';
import { Home, Layout } from './components/Layout';
import { RequireSession } from './lib/session';
import { Login } from './pages/login';

const page = (load: () => Promise<{ Component: React.ComponentType }>) => ({ lazy: load });

export const router = createBrowserRouter([
  { path: '/entrar', element: <Login /> },
  {
    element: (
      <RequireSession>
        <Layout />
      </RequireSession>
    ),
    hydrateFallbackElement: <p className="p-10 text-center text-sm text-stone-500">Carregando…</p>,
    children: [
      { index: true, element: <Home /> },
      { path: '/pdv', ...page(() => import('./pos/PosPage').then((m) => ({ Component: m.PosPage }))) },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
]);
