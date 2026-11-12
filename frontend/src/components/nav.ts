import type { Capability } from '../lib/types';

export const NAV: { to: string; label: string; any: Capability[] }[] = [
  { to: '/pdv', label: 'Frente de caixa', any: ['pos.sell'] },
  { to: '/vendas', label: 'Vendas e trocas', any: ['pos.sell'] },
  { to: '/produtos', label: 'Produtos', any: ['stock.view', 'catalog.manage'] },
  { to: '/estoque', label: 'Estoque', any: ['stock.view'] },
  { to: '/compras', label: 'Compras', any: ['purchasing.manage', 'stock.receive'] },
  { to: '/transferencias', label: 'Transferências', any: ['stock.transfer'] },
  { to: '/inventario', label: 'Inventário', any: ['stock.count'] },
  { to: '/relatorios', label: 'Relatórios', any: ['reports.sales'] },
  { to: '/equipe', label: 'Equipe e lojas', any: ['users.manage', 'locations.manage'] },
];

export const navFor = (can: (c: Capability) => boolean) => NAV.filter((item) => item.any.some(can));
