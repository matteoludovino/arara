import { useMutation } from '@tanstack/react-query';
import { Alert, Button, Dialog, Field, formData, Input } from '../components/ui';
import { api } from '../lib/api';
import { dateTime } from '../lib/format';
import { brl, fromCents, toCents } from '../lib/money';
import type { CashSession, Sale } from '../lib/types';
import { METHOD_LABEL } from './PaymentDialog';

/** Sangria (cash out to the safe) or suprimento (more change into the drawer). */
export function CashMovementDialog({
  session,
  kind,
  onClose,
}: {
  session: CashSession;
  kind: 'withdrawal' | 'supply';
  onClose: () => void;
}) {
  const move = useMutation({
    mutationFn: (v: Record<string, string>) =>
      api.post(`/pos/sessions/${session.id}/movements`, { kind, amount: fromCents(toCents(v.amount)), reason: v.reason }),
    onSuccess: onClose,
  });
  return (
    <Dialog open onClose={onClose} title={kind === 'withdrawal' ? 'Sangria' : 'Suprimento'}>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          move.mutate(formData(e.currentTarget));
        }}
      >
        <Field label="Valor (R$)">{(id) => <Input id={id} name="amount" inputMode="decimal" required data-autofocus />}</Field>
        <Field label="Motivo">
          {(id) => <Input id={id} name="reason" required placeholder={kind === 'withdrawal' ? 'Ex.: cofre' : 'Ex.: troco'} />}
        </Field>
        {move.error && <Alert>{move.error.message}</Alert>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" busy={move.isPending}>
            Registrar
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

/**
 * Closing is blind: the cashier counts the drawer before seeing what the system expected, so
 * the count isn't nudged towards the expected figure. The difference shows after closing.
 */
export function CloseTillDialog({
  session,
  onClose,
  onClosed,
}: {
  session: CashSession;
  onClose: () => void;
  onClosed: (closed: CashSession) => void;
}) {
  const close = useMutation({
    mutationFn: (v: Record<string, string>) =>
      api.post<CashSession>(`/pos/sessions/${session.id}/close`, { counted_cash: fromCents(toCents(v.counted_cash)), note: v.note }),
    onSuccess: onClosed,
  });
  return (
    <Dialog open onClose={onClose} title="Fechar caixa">
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            close.mutate(formData(e.currentTarget));
          }}
        >
          <p className="text-sm text-stone-600">Conte o dinheiro da gaveta e informe o total. O valor esperado aparece depois.</p>
          <Field label="Dinheiro contado (R$)">{(id) => <Input id={id} name="counted_cash" inputMode="decimal" required data-autofocus />}</Field>
          <Field label="Observação">{(id) => <Input id={id} name="note" maxLength={200} />}</Field>
          {close.error && <Alert>{close.error.message}</Alert>}
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={onClose}>
              Cancelar
            </Button>
            <Button type="submit" busy={close.isPending}>
              Fechar caixa
            </Button>
          </div>
        </form>
    </Dialog>
  );
}

/** The closing, with the difference: shown once the till is closed (and the selling screen is gone). */
export function ClosedTillDialog({ closed, onClose }: { closed: CashSession; onClose: () => void }) {
  const summary = closed.summary!;
  const difference = summary.difference ? toCents(summary.difference) : 0;
  return (
    <Dialog open onClose={onClose} title="Caixa fechado">
        <div className="space-y-4">
          <dl className="grid grid-cols-2 gap-y-1.5 text-sm">
            <dt className="text-stone-500">Troco inicial</dt>
            <dd className="text-right">{brl(summary.opening_float)}</dd>
            {Object.entries(summary.by_method).map(([method, total]) => (
              <div key={method} className="contents">
                <dt className="text-stone-500">Vendas em {METHOD_LABEL[method as keyof typeof METHOD_LABEL].toLowerCase()}</dt>
                <dd className="text-right">{brl(total)}</dd>
              </div>
            ))}
            {summary.movements.withdrawal && (
              <>
                <dt className="text-stone-500">Sangrias</dt>
                <dd className="text-right">− {brl(summary.movements.withdrawal)}</dd>
              </>
            )}
            {summary.movements.supply && (
              <>
                <dt className="text-stone-500">Suprimentos</dt>
                <dd className="text-right">+ {brl(summary.movements.supply)}</dd>
              </>
            )}
            {summary.movements.refund && (
              <>
                <dt className="text-stone-500">Devoluções em dinheiro</dt>
                <dd className="text-right">− {brl(summary.movements.refund)}</dd>
              </>
            )}
            <dt className="border-t border-stone-200 pt-1.5 font-medium">Esperado na gaveta</dt>
            <dd className="border-t border-stone-200 pt-1.5 text-right font-medium">{brl(summary.expected_cash)}</dd>
            <dt className="font-medium">Contado</dt>
            <dd className="text-right font-medium">{brl(summary.counted_cash)}</dd>
          </dl>
          <Alert tone={difference === 0 ? 'success' : 'warning'}>
            {difference === 0
              ? 'Caixa conferido, sem diferença.'
              : `${difference < 0 ? 'Falta' : 'Sobra'} de ${brl(fromCents(Math.abs(difference)))}: fica registrada para o gerente.`}
          </Alert>
          <p className="text-xs text-stone-500">
            {summary.sales} venda(s), {summary.cancelled_sales} cancelada(s). Fechado em {dateTime(closed.closed_at)}.
          </p>
          <div className="flex justify-end">
            <Button onClick={onClose} data-autofocus>
              Concluir
            </Button>
          </div>
        </div>
    </Dialog>
  );
}

/** What was sold, as the customer's receipt shows it. */
export function ReceiptDialog({ sale, onClose }: { sale: Sale; onClose: () => void }) {
  const change = sale.payments.reduce((sum, p) => sum + (p.change ? toCents(p.change) : 0), 0);
  return (
    <Dialog open onClose={onClose} title={`Venda nº ${sale.number}`}>
      <div className="space-y-4">
        {change > 0 && (
          <div className="rounded-xl bg-emerald-50 px-4 py-3 text-center">
            <p className="text-sm text-emerald-800">Troco</p>
            <p className="text-3xl font-semibold text-emerald-900">{brl(fromCents(change))}</p>
          </div>
        )}
        <ul className="divide-y divide-stone-100 text-sm">
          {sale.items.map((item) => (
            <li key={item.id} className="flex justify-between gap-3 py-1.5">
              <span>
                {item.quantity}× {item.product} <span className="text-stone-500">{item.color} {item.size}</span>
              </span>
              <span>{brl(item.net_amount)}</span>
            </li>
          ))}
        </ul>
        <dl className="grid grid-cols-2 gap-y-1 text-sm">
          {sale.discount_total !== '0.00' && (
            <>
              <dt className="text-stone-500">Desconto</dt>
              <dd className="text-right">− {brl(sale.discount_total)}</dd>
            </>
          )}
          <dt className="font-medium">Total</dt>
          <dd className="text-right font-medium">{brl(sale.total)}</dd>
          {sale.payments.map((p, i) => (
            <div key={i} className="contents">
              <dt className="text-stone-500">
                {p.method_label}
                {p.installments && p.installments > 1 ? ` (${p.installments}×)` : ''}
              </dt>
              <dd className="text-right">{brl(p.amount)}</dd>
            </div>
          ))}
        </dl>
        <div className="flex justify-end">
          <Button onClick={onClose} data-autofocus>
            Nova venda
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
