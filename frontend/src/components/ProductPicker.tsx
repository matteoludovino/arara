import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { api, type Page, qs } from '../lib/api';
import { brl } from '../lib/money';
import { useSession } from '../lib/session';
import type { Grid, Lookup, Product, ProductListItem } from '../lib/types';
import { cx, Dialog, Empty, Input, Loading } from './ui';

/** A product's SKUs as a color × size grid; a click picks one. Shows stock here when allowed. */
export function VariantGrid({
  product,
  locationId,
  onPick,
}: {
  product: Product;
  locationId?: number;
  onPick: (item: Lookup) => void;
}) {
  const { can } = useSession();
  const grid = useQuery({
    queryKey: ['stock-grid', product.id, locationId],
    queryFn: () => api.get<Grid>(`/stock/grid${qs({ product: product.id, location: locationId })}`),
    enabled: can('stock.view'),
  });
  const sizes = product.size_grid.sizes.map((s) => s.label);
  const colors = [...new Map(product.variants.map((v) => [v.color.id, v.color])).values()].sort((a, b) =>
    a.name.localeCompare(b.name),
  );
  const stockOf = (color: string, size: string) => {
    const row = grid.data?.rows.find((r) => r.color === color);
    const i = grid.data?.sizes.indexOf(size) ?? -1;
    return row && i >= 0 ? row.quantities[i] : undefined;
  };
  return (
    <div className="overflow-x-auto">
      <table className="text-sm">
        <thead>
          <tr>
            <th />
            {sizes.map((s) => (
              <th key={s} className="px-2 py-1 text-center font-medium text-stone-600">
                {s}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {colors.map((color) => (
            <tr key={color.id}>
              <th className="py-1 pr-3 text-left font-medium whitespace-nowrap text-stone-700">
                <span className="mr-1.5 inline-block size-3 rounded-full border border-stone-300 align-middle" style={{ background: color.hex || '#fff' }} />
                {color.name}
              </th>
              {sizes.map((size) => {
                const variant = product.variants.find((v) => v.color.id === color.id && v.size === size);
                const stock = stockOf(color.name, size);
                return (
                  <td key={size} className="p-0.5">
                    {variant ? (
                      <button
                        type="button"
                        disabled={!variant.is_active}
                        onClick={() =>
                          onPick({
                            id: variant.id,
                            sku: variant.sku,
                            product: { id: product.id, reference: product.reference, name: product.name },
                            size: variant.size,
                            color: variant.color.name,
                            is_active: variant.is_active,
                            current_price: variant.current_price,
                          })
                        }
                        className={cx(
                          'h-11 w-14 rounded-lg border text-center tabular-nums hover:border-brand-500 hover:bg-brand-50 disabled:opacity-40',
                          stock === 0 ? 'border-stone-200 text-stone-400' : 'border-stone-300 text-stone-800',
                        )}
                        title={variant.sku}
                      >
                        {stock ?? '·'}
                      </button>
                    ) : (
                      <span className="block h-11 w-14" />
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {grid.data && <p className="mt-2 text-xs text-stone-500">Números: peças em estoque nesta loja.</p>}
    </div>
  );
}

/** Find a product by name or reference, then pick the SKU in its grid. */
export function ProductPicker({
  locationId,
  onPick,
  onClose,
}: {
  locationId?: number;
  onPick: (item: Lookup) => void;
  onClose: () => void;
}) {
  const [q, setQ] = useState('');
  const [chosen, setChosen] = useState<number | null>(null);
  const results = useQuery({
    queryKey: ['products', 'picker', q],
    queryFn: () => api.get<Page<ProductListItem>>(`/catalog/products${qs({ q, is_active: true, limit: 12 })}`),
    enabled: chosen === null,
  });
  const product = useQuery({
    queryKey: ['product', chosen],
    queryFn: () => api.get<Product>(`/catalog/products/${chosen}`),
    enabled: chosen !== null,
  });
  return (
    <Dialog open onClose={onClose} title="Buscar produto" wide>
      {chosen === null ? (
        <div className="space-y-3">
          <Input data-autofocus placeholder="Nome ou referência" value={q} onChange={(e) => setQ(e.target.value)} />
          {results.isPending ? (
            <Loading />
          ) : results.data?.results.length ? (
            <ul className="divide-y divide-stone-100">
              {results.data.results.map((p) => (
                <li key={p.id}>
                  <button
                    type="button"
                    onClick={() => setChosen(p.id)}
                    className="flex w-full items-center justify-between gap-3 px-2 py-2 text-left hover:bg-stone-50"
                  >
                    <span>
                      <span className="font-medium text-stone-900">{p.name}</span>{' '}
                      <span className="text-xs text-stone-500">{p.reference}</span>
                    </span>
                    <span className="text-sm text-stone-600">{brl(p.current_price)}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <Empty>Nenhum produto encontrado.</Empty>
          )}
        </div>
      ) : product.data ? (
        <div className="space-y-3">
          <button type="button" className="text-sm text-brand-700 hover:underline" onClick={() => setChosen(null)}>
            ← Voltar à busca
          </button>
          <p className="font-medium text-stone-900">
            {product.data.name} <span className="text-sm text-stone-500">· {brl(product.data.current_price)}</span>
          </p>
          <VariantGrid product={product.data} locationId={locationId} onPick={onPick} />
        </div>
      ) : (
        <Loading />
      )}
    </Dialog>
  );
}
