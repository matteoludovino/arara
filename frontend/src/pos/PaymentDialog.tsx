import { useState } from 'react';
import { Alert, Button, cx, Dialog, Input, Select } from '../components/ui';
import { api } from '../lib/api';
import { brlCents, fromCents, toCents } from '../lib/money';
import type { PaymentMethod, StoreCredit } from '../lib/types';

export const METHOD_LABEL: Record<PaymentMethod, string> = {
  cash: 'Dinheiro',
  debit: 'Débito',
  credit: 'Crédito',
  pix: 'Pix',
  store_credit: 'Vale-troca',
};

interface Row {
  key: number;
  method: PaymentMethod;
  amount: string;
  tendered: string;
  installments: number;
  code: string;
  credit?: StoreCredit | null;
}

export interface PaymentInput {
  method: PaymentMethod;
  amount: string;
  tendered?: string;
  installments?: number;
  store_credit_code?: string;
}

const cents = (typed: string) => {
  const value = toCents(typed);
  return Number.isNaN(value) ? 0 : value;
};

/** Split the bill across methods; the server checks it again, to the cent. */
export function PaymentDialog({
  total,
  busy,
  error,
  initialCredit,
  onConfirm,
  onClose,
}: {
  total: number;
  busy: boolean;
  error: Error | null;
  initialCredit?: string;
  onConfirm: (payments: PaymentInput[]) => void;
  onClose: () => void;
}) {
  const [rows, setRows] = useState<Row[]>(() =>
    initialCredit
      ? [{ key: 1, method: 'store_credit', amount: '', tendered: '', installments: 1, code: initialCredit }]
      : [],
  );
  const paid = rows.reduce((sum, r) => sum + cents(r.amount), 0);
  const remaining = total - paid;
  const update = (key: number, patch: Partial<Row>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const add = (method: PaymentMethod) =>
    setRows((rs) => [
      ...rs,
      { key: Date.now(), method, amount: remaining > 0 ? fromCents(remaining).replace('.', ',') : '', tendered: '', installments: 1, code: '' },
    ]);
  const checkCredit = async (row: Row) => {
    if (!row.code.trim()) return;
    try {
      const credit = await api.get<StoreCredit>(`/pos/store-credits/${encodeURIComponent(row.code.trim())}`);
      const usable = Math.min(toCents(credit.balance), cents(row.amount) || remaining + cents(row.amount));
      update(row.key, { credit, amount: fromCents(Math.max(usable, 0)).replace('.', ',') });
    } catch {
      update(row.key, { credit: null });
    }
  };
  const cashShort = rows.some((r) => r.method === 'cash' && r.tendered && cents(r.tendered) < cents(r.amount));
  const ready = rows.length > 0 && remaining === 0 && rows.every((r) => cents(r.amount) > 0) && !cashShort;
  const submit = () =>
    onConfirm(
      rows.map((r) => ({
        method: r.method,
        amount: fromCents(cents(r.amount)),
        ...(r.method === 'cash' && { tendered: fromCents(cents(r.tendered) || cents(r.amount)) }),
        ...(r.method === 'credit' && { installments: r.installments }),
        ...(r.method === 'store_credit' && { store_credit_code: r.code.trim() }),
      })),
    );
  return (
    <Dialog open onClose={onClose} title="Pagamento" wide>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault(); // Enter concludes, once the payments add up
          if (ready && !busy) submit();
        }}
      >
        <div className="flex items-baseline justify-between rounded-xl bg-stone-50 px-4 py-3">
          <span className="text-sm text-stone-600">Total da venda</span>
          <span className="text-2xl font-semibold text-stone-900">{brlCents(total)}</span>
        </div>
        <div className="flex flex-wrap gap-2">
          {(Object.keys(METHOD_LABEL) as PaymentMethod[]).map((m) => (
            <Button key={m} variant="secondary" onClick={() => add(m)} disabled={remaining <= 0}>
              + {METHOD_LABEL[m]}
            </Button>
          ))}
        </div>
        {rows.map((r) => {
          const change = r.method === 'cash' && r.tendered ? cents(r.tendered) - cents(r.amount) : 0;
          return (
            <div key={r.key} className="grid gap-2 rounded-xl border border-stone-200 p-3 sm:grid-cols-[8rem_1fr_1fr_auto] sm:items-end">
              <p className="text-sm font-medium text-stone-800 sm:pb-2">{METHOD_LABEL[r.method]}</p>
              <label className="text-xs text-stone-500">
                Valor
                <Input inputMode="decimal" value={r.amount} onChange={(e) => update(r.key, { amount: e.target.value })} autoFocus />
              </label>
              {r.method === 'cash' && (
                <label className="text-xs text-stone-500">
                  Recebido {change > 0 && <span className="font-medium text-emerald-700">· troco {brlCents(change)}</span>}
                  <Input inputMode="decimal" value={r.tendered} placeholder="o valor exato" onChange={(e) => update(r.key, { tendered: e.target.value })} />
                </label>
              )}
              {r.method === 'credit' && (
                <label className="text-xs text-stone-500">
                  Parcelas
                  <Select value={r.installments} onChange={(e) => update(r.key, { installments: Number(e.target.value) })}>
                    {Array.from({ length: 12 }, (_, i) => i + 1).map((n) => (
                      <option key={n} value={n}>
                        {n}× de {brlCents(Math.floor(cents(r.amount) / n))}
                      </option>
                    ))}
                  </Select>
                </label>
              )}
              {r.method === 'store_credit' && (
                <label className="text-xs text-stone-500">
                  Código do vale
                  {r.credit && <span className="font-medium text-emerald-700"> · saldo {brlCents(toCents(r.credit.balance))}</span>}
                  {r.credit === null && <span className="font-medium text-red-700"> · não encontrado</span>}
                  <Input value={r.code} onChange={(e) => update(r.key, { code: e.target.value.toUpperCase(), credit: undefined })} onBlur={() => checkCredit(r)} />
                </label>
              )}
              {(r.method === 'debit' || r.method === 'pix') && <span />}
              <Button variant="ghost" onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))} aria-label="Remover pagamento">
                ✕
              </Button>
            </div>
          );
        })}
        <p className={cx('text-right text-sm', remaining === 0 ? 'text-emerald-700' : 'text-stone-700')}>
          {remaining > 0 ? `Falta ${brlCents(remaining)}` : remaining < 0 ? `Passou ${brlCents(-remaining)}: ajuste os valores` : 'Pagamento completo'}
        </p>
        {cashShort && <Alert tone="warning">O valor recebido em dinheiro é menor que o pago em dinheiro.</Alert>}
        {error && <Alert>{error.message}</Alert>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            Voltar
          </Button>
          <Button type="submit" disabled={!ready} busy={busy}>
            Concluir venda
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
