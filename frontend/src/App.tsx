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
      { path: '/vendas', ...page(() => import('./pages/sales').then((m) => ({ Component: m.SalesPage }))) },
      { path: '/produtos', ...page(() => import('./pages/products').then((m) => ({ Component: m.ProductsPage }))) },
      { path: '/produtos/:id', ...page(() => import('./pages/products').then((m) => ({ Component: m.ProductDetailPage }))) },
      { path: '/estoque', ...page(() => import('./pages/stock').then((m) => ({ Component: m.StockPage }))) },
      { path: '/compras', ...page(() => import('./pages/purchasing').then((m) => ({ Component: m.PurchasingPage }))) },
      { path: '/transferencias', ...page(() => import('./pages/transfers').then((m) => ({ Component: m.TransfersPage }))) },
      { path: '/inventario', ...page(() => import('./pages/counts').then((m) => ({ Component: m.CountsPage }))) },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
]);
