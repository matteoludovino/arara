import { useState } from 'react';
import { api } from '../lib/api';
import type { Lookup } from '../lib/types';
import { ProductPicker } from './ProductPicker';
import { Alert, Button, Input } from './ui';

export interface ScanLine {
  item: Lookup;
  quantity: number;
}

/**
 * Lines of SKUs, read with the scanner (or typed, or picked from a product's grid), each with a
 * quantity. `signed` allows negative quantities (an adjustment: pieces found or missing).
 */
export function ScanLines({
  lines,
  onChange,
  signed = false,
  locationId,
  extra,
}: {
  lines: ScanLine[];
  onChange: (lines: ScanLine[]) => void;
  signed?: boolean;
  locationId?: number;
  /** One more column per line (a unit cost, for instance). */
  extra?: (line: ScanLine) => React.ReactNode;
}) {
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [picking, setPicking] = useState(false);
  const add = (item: Lookup) => {
    setError(null);
    const found = lines.find((l) => l.item.id === item.id);
    onChange(
      found
        ? lines.map((l) => (l === found ? { ...l, quantity: l.quantity + (signed && l.quantity < 0 ? -1 : 1) } : l))
        : [...lines, { item, quantity: 1 }],
    );
  };
  const scan = async () => {
    if (!code.trim()) return;
    try {
      add(await api.get<Lookup>(`/catalog/lookup?code=${encodeURIComponent(code.trim())}`));
      setCode('');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Código não encontrado.');
    }
  };
  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <Input
          value={code}
          onChange={(e) => setCode(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault(); // inside a form: Enter reads the code, it doesn't submit
              void scan();
            }
          }}
          placeholder="Código de barras ou SKU"
          aria-label="Código de barras ou SKU"
          autoComplete="off"
        />
        <Button variant="secondary" onClick={() => void scan()}>
          Adicionar
        </Button>
        <Button variant="secondary" onClick={() => setPicking(true)} className="whitespace-nowrap">
          Buscar produto
        </Button>
      </div>
      {error && <Alert>{error}</Alert>}
      {lines.length > 0 && (
        <ul className="divide-y divide-stone-100 rounded-xl border border-stone-200">
          {lines.map((line) => (
            <li key={line.item.id} className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm">
              <span className="min-w-0 flex-1">
                {line.item.product.name} <span className="text-stone-500">{line.item.color} · {line.item.size}</span>
                <span className="block font-mono text-xs text-stone-500">{line.item.sku}</span>
              </span>
              {extra?.(line)}
              <Input
                type="number"
                className="w-24 text-right"
                aria-label={`Quantidade de ${line.item.sku}`}
                min={signed ? undefined : 1}
                value={line.quantity}
                onChange={(e) =>
                  onChange(lines.map((l) => (l === line ? { ...l, quantity: Math.trunc(Number(e.target.value)) || 0 } : l)))
                }
              />
              <Button variant="ghost" className="px-2 text-stone-400" aria-label="Remover" onClick={() => onChange(lines.filter((l) => l !== line))}>
                ✕
              </Button>
            </li>
          ))}
        </ul>
      )}
      {picking && (
        <ProductPicker
          locationId={locationId}
          onClose={() => setPicking(false)}
          onPick={(item) => {
            add(item);
            setPicking(false);
          }}
        />
      )}
    </div>
  );
}
