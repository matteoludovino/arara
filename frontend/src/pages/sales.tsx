import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router';
import { ApprovalDialog } from '../components/ApprovalDialog';
import {
  Alert,
  Badge,
  Button,
  Dialog,
  Empty,
  ErrorAlert,
  Field,
  Input,
  Loading,
  PageHeader,
  Select,
  Table,
  Tabs,
} from '../components/ui';
import { api, ApiError, type Page, qs } from '../lib/api';
import { dateTime } from '../lib/format';
import { brl } from '../lib/money';
import { useSession } from '../lib/session';
import type { Lookup, Sale, SaleReturn } from '../lib/types';

export function SalesPage() {
  const { location } = useSession();
  const [tab, setTab] = useState<'sales' | 'returns'>('sales');
  const [noReceipt, setNoReceipt] = useState(false);
  if (!location || location.kind !== 'store') return <Alert tone="info">Escolha uma loja no menu.</Alert>;
  return (
    <div>
      <PageHeader
        title="Vendas e trocas"
        description={`${location.name}: consulte uma venda para cancelar, devolver ou trocar peças.`}
        actions={
          <Button variant="secondary" onClick={() => setNoReceipt(true)}>
            Devolução sem cupom
          </Button>
        }
      />
      <Tabs
        value={tab}
        onChange={setTab}
        options={[
          { value: 'sales', label: 'Vendas' },
          { value: 'returns', label: 'Devoluções' },
        ]}
      />
      {tab === 'sales' ? <SalesList storeId={location.id} /> : <ReturnsList storeId={location.id} />}
      {noReceipt && <NoReceiptReturn storeId={location.id} onClose={() => setNoReceipt(false)} />}
    </div>
  );
}

function SalesList({ storeId }: { storeId: number }) {
  const [number, setNumber] = useState('');
  const [open, setOpen] = useState<number | null>(null);
  const sales = useQuery({
    queryKey: ['sales', storeId, number],
    queryFn: () => api.get<Page<Sale>>(`/pos/sales${qs({ location: storeId, number: number || undefined, limit: 30 })}`),
  });
  return (
    <div className="space-y-3">
      <Input
        className="w-48"
        placeholder="Nº da venda"
        inputMode="numeric"
        value={number}
        onChange={(e) => setNumber(e.target.value.replace(/\D/g, ''))}
      />
      {sales.isPending ? (
        <Loading />
      ) : sales.error ? (
        <ErrorAlert error={sales.error} />
      ) : sales.data.results.length === 0 ? (
        <Empty>Nenhuma venda encontrada.</Empty>
      ) : (
        <Table head={['Nº', 'Quando', 'Caixa', 'Vendedor(a)', 'Peças', 'Total', '']} num={[4, 5]}>
          {sales.data.results.map((s) => (
            <tr key={s.id} className="cursor-pointer hover:bg-stone-50" onClick={() => setOpen(s.id)}>
              <td className="font-medium">{s.number}</td>
              <td>{dateTime(s.created_at)}</td>
              <td>{s.cashier}</td>
              <td>{s.salesperson ?? '—'}</td>
              <td className="text-right">{s.items.reduce((n, i) => n + i.quantity, 0)}</td>
              <td className="text-right">{brl(s.total)}</td>
              <td>{s.status === 'cancelled' ? <Badge tone="red">Cancelada</Badge> : s.items.some((i) => i.quantity_returned) ? <Badge tone="amber">Com devolução</Badge> : null}</td>
            </tr>
          ))}
        </Table>
      )}
      {open !== null && <SaleDialog saleId={open} storeId={storeId} onClose={() => setOpen(null)} />}
    </div>
  );
}

function SaleDialog({ saleId, storeId, onClose }: { saleId: number; storeId: number; onClose: () => void }) {
  const [mode, setMode] = useState<'view' | 'cancel' | 'return'>('view');
  const sale = useQuery({ queryKey: ['sale', saleId], queryFn: () => api.get<Sale>(`/pos/sales/${saleId}`) });
  const title = sale.data ? `Venda nº ${sale.data.number} · ${sale.data.location_code}` : 'Venda';
  return (
    <Dialog open onClose={onClose} title={title} wide>
      {!sale.data ? (
        <Loading />
      ) : mode === 'cancel' ? (
        <CancelSale sale={sale.data} onDone={() => setMode('view')} />
      ) : mode === 'return' ? (
        <ReturnItems sale={sale.data} storeId={storeId} onBack={() => setMode('view')} />
      ) : (
        <SaleView sale={sale.data} onCancel={() => setMode('cancel')} onReturn={() => setMode('return')} />
      )}
    </Dialog>
  );
}

function SaleView({ sale, onCancel, onReturn }: { sale: Sale; onCancel: () => void; onReturn: () => void }) {
  const { can } = useSession();
  const returnable = sale.status === 'completed' && sale.items.some((i) => i.quantity > i.quantity_returned);
  return (
    <div className="space-y-4">
      <p className="text-sm text-stone-600">
        {dateTime(sale.created_at)} · caixa {sale.cashier}
        {sale.salesperson && ` · vendedor(a) ${sale.salesperson}`}
        {sale.customer && ` · cliente ${sale.customer}`}
      </p>
      {sale.status === 'cancelled' && (
        <Alert tone="warning">
          Cancelada em {dateTime(sale.cancelled_at)}: {sale.cancel_reason}
        </Alert>
      )}
      <Table head={['Peça', 'Qtd.', 'Devolvidas', 'Preço', 'Pago', ...(can('costs.view') ? ['Margem'] : [])]} num={[1, 2, 3, 4, 5]}>
        {sale.items.map((i) => (
          <tr key={i.id}>
            <td>
              {i.product} <span className="text-xs text-stone-500">{i.color} · {i.size}</span>
            </td>
            <td className="text-right">{i.quantity}</td>
            <td className="text-right">{i.quantity_returned || '—'}</td>
            <td className="text-right">{brl(i.unit_price)}</td>
            <td className="text-right">{brl(i.net_amount)}</td>
            {can('costs.view') && <td className="text-right">{brl(i.margin)}</td>}
          </tr>
        ))}
      </Table>
      <div className="flex flex-wrap justify-between gap-3 text-sm">
        <div className="space-y-0.5 text-stone-600">
          {sale.payments.map((p, i) => (
            <p key={i}>
              {p.method_label}
              {p.installments && p.installments > 1 ? ` ${p.installments}×` : ''}: {brl(p.amount)}
            </p>
          ))}
        </div>
        <div className="text-right">
          {sale.discount_total !== '0.00' && <p className="text-stone-600">Desconto {brl(sale.discount_total)}</p>}
          <p className="text-lg font-semibold">Total {brl(sale.total)}</p>
        </div>
      </div>
      {sale.status === 'completed' && (
        <div className="flex justify-end gap-2 border-t border-stone-200 pt-4">
          <Button variant="danger" onClick={onCancel}>
            Cancelar venda
          </Button>
          <Button onClick={onReturn} disabled={!returnable}>
            Devolver ou trocar
          </Button>
        </div>
      )}
    </div>
  );
}

function CancelSale({ sale, onDone }: { sale: Sale; onDone: () => void }) {
  const [reason, setReason] = useState('');
  const cancel = useMutation({
    mutationFn: () => api.post<Sale>(`/pos/sales/${sale.id}/cancel`, { reason }),
    onSuccess: onDone,
  });
  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        cancel.mutate();
      }}
    >
      <Alert tone="warning">
        Cancelar desfaz a venda inteira: as peças voltam ao estoque e os pagamentos são estornados. Só no mesmo turno de
        caixa; depois disso, faça uma devolução.
      </Alert>
      <Field label="Motivo">{(id) => <Input id={id} value={reason} onChange={(e) => setReason(e.target.value)} required data-autofocus />}</Field>
      <ErrorAlert error={cancel.error} />
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onDone}>
          Voltar
        </Button>
        <Button type="submit" variant="danger" busy={cancel.isPending}>
          Cancelar venda
        </Button>
      </div>
    </form>
  );
}

function ReturnItems({ sale, storeId, onBack }: { sale: Sale; storeId: number; onBack: () => void }) {
  const [quantities, setQuantities] = useState<Record<number, number>>({});
  const [refund, setRefund] = useState<'store_credit' | 'cash'>('store_credit');
  const [reason, setReason] = useState('');
  const give = useMutation({
    mutationFn: () =>
      api.post<SaleReturn>('/pos/returns', {
        location: storeId,
        sale: sale.id,
        lines: Object.entries(quantities)
          .filter(([, q]) => q > 0)
          .map(([item, quantity]) => ({ sale_item: Number(item), quantity })),
        refund_method: refund,
        reason,
      }),
  });
  if (give.data) return <ReturnDone result={give.data} />;
  const picked = Object.values(quantities).some((q) => q > 0);
  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        give.mutate();
      }}
    >
      <p className="text-sm text-stone-600">
        Quantas peças de cada item voltam? Cada uma é reembolsada pelo que foi pago nela, desconto incluído.
      </p>
      <ul className="divide-y divide-stone-100">
        {sale.items.map((i) => {
          const left = i.quantity - i.quantity_returned;
          return (
            <li key={i.id} className="flex items-center justify-between gap-3 py-2 text-sm">
              <span>
                {i.product} <span className="text-stone-500">{i.color} · {i.size}</span>
                <span className="block text-xs text-stone-500">
                  {left} de {i.quantity} ainda podem voltar · pago {brl(i.net_amount)}
                </span>
              </span>
              <Input
                type="number"
                min={0}
                max={left}
                disabled={left === 0}
                className="w-20 text-right"
                aria-label={`Devolver ${i.sku}`}
                value={quantities[i.id] ?? 0}
                onChange={(e) => setQuantities((q) => ({ ...q, [i.id]: Math.min(left, Math.max(0, Number(e.target.value))) }))}
              />
            </li>
          );
        })}
      </ul>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Reembolso" hint={refund === 'cash' ? 'Sai da gaveta do seu caixa aberto.' : 'Um vale com código, para usar agora ou depois.'}>
          {(id) => (
            <Select id={id} value={refund} onChange={(e) => setRefund(e.target.value as typeof refund)}>
              <option value="store_credit">Vale-troca</option>
              <option value="cash">Dinheiro</option>
            </Select>
          )}
        </Field>
        <Field label="Motivo">{(id) => <Input id={id} value={reason} onChange={(e) => setReason(e.target.value)} required placeholder="Ex.: não serviu" />}</Field>
      </div>
      <ErrorAlert error={give.error} />
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onBack}>
          Voltar
        </Button>
        <Button type="submit" disabled={!picked} busy={give.isPending}>
          Registrar devolução
        </Button>
      </div>
    </form>
  );
}

/** A return done: the refund, and for a credit, its code and the way to the till to exchange. */
function ReturnDone({ result }: { result: SaleReturn }) {
  const navigate = useNavigate();
  return (
    <div className="space-y-4">
      <Alert tone="success">
        Devolução registrada: {brl(result.total)}
        {result.refund_method === 'cash' ? ' em dinheiro, saindo da gaveta.' : ' em vale-troca.'}
      </Alert>
      {result.store_credit && (
        <div className="rounded-xl border border-dashed border-stone-300 p-4 text-center">
          <p className="text-sm text-stone-500">Código do vale-troca</p>
          <p className="mt-1 font-mono text-2xl font-semibold tracking-widest text-stone-900">{result.store_credit}</p>
        </div>
      )}
      {result.store_credit && (
        <div className="flex justify-end">
          <Button onClick={() => navigate(`/pdv?vale=${result.store_credit}`)} data-autofocus>
            Trocar agora no caixa
          </Button>
        </div>
      )}
    </div>
  );
}

/** Without the receipt: the pieces by code, at today's price, with a manager's approval. */
function NoReceiptReturn({ storeId, onClose }: { storeId: number; onClose: () => void }) {
  const [lines, setLines] = useState<{ item: Lookup; quantity: number }[]>([]);
  const [code, setCode] = useState('');
  const [reason, setReason] = useState('');
  const [needsApproval, setNeedsApproval] = useState(false);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const give = useMutation({
    mutationFn: (approval: number | null) =>
      api.post<SaleReturn>('/pos/returns', {
        location: storeId,
        sale: null,
        lines: lines.map((l) => ({ variant: l.item.id, quantity: l.quantity })),
        refund_method: 'store_credit',
        reason,
        approval,
      }),
    onError: (error) => setNeedsApproval(error instanceof ApiError && error.code === 'return_needs_approval'),
  });
  const add = async () => {
    setLookupError(null);
    try {
      const item = await api.get<Lookup>(`/catalog/lookup?code=${encodeURIComponent(code.trim())}`);
      setLines((ls) => {
        const found = ls.find((l) => l.item.id === item.id);
        return found ? ls.map((l) => (l === found ? { ...l, quantity: l.quantity + 1 } : l)) : [...ls, { item, quantity: 1 }];
      });
      setCode('');
    } catch (error) {
      setLookupError(error instanceof Error ? error.message : 'Código não encontrado.');
    }
  };
  return (
    <Dialog open onClose={onClose} title="Devolução sem cupom" wide>
      {give.data ? (
        <ReturnDone result={give.data} />
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-stone-600">Sem o cupom, a peça volta pelo preço de hoje, em vale-troca, com aprovação do gerente.</p>
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              void add();
            }}
          >
            <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="Código de barras ou SKU" data-autofocus />
            <Button type="submit" variant="secondary">
              Adicionar
            </Button>
          </form>
          {lookupError && <Alert>{lookupError}</Alert>}
          {lines.length > 0 && (
            <ul className="divide-y divide-stone-100 text-sm">
              {lines.map((l) => (
                <li key={l.item.id} className="flex justify-between py-1.5">
                  <span>
                    {l.quantity}× {l.item.product.name} <span className="text-stone-500">{l.item.color} · {l.item.size}</span>
                  </span>
                  <span>{brl(l.item.current_price)}</span>
                </li>
              ))}
            </ul>
          )}
          <Field label="Motivo">{(id) => <Input id={id} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Ex.: presente, sem nota" />}</Field>
          {!needsApproval && <ErrorAlert error={give.error} />}
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={onClose}>
              Cancelar
            </Button>
            <Button disabled={!lines.length || !reason.trim()} busy={give.isPending} onClick={() => give.mutate(null)}>
              Registrar devolução
            </Button>
          </div>
        </div>
      )}
      {needsApproval && (
        <ApprovalDialog
          action="return_without_receipt"
          location={storeId}
          detail={reason}
          onClose={() => setNeedsApproval(false)}
          onApproved={(approval) => {
            setNeedsApproval(false);
            give.mutate(approval.id);
          }}
        />
      )}
    </Dialog>
  );
}

function ReturnsList({ storeId }: { storeId: number }) {
  const returns = useQuery({
    queryKey: ['returns', storeId],
    queryFn: () => api.get<Page<SaleReturn>>(`/pos/returns${qs({ location: storeId, limit: 30 })}`),
  });
  if (returns.isPending) return <Loading />;
  if (returns.error) return <ErrorAlert error={returns.error} />;
  if (!returns.data.results.length) return <Empty>Nenhuma devolução nesta loja.</Empty>;
  return (
    <Table head={['Quando', 'Venda', 'Peças', 'Reembolso', 'Valor', 'Motivo', 'Por']} num={[2, 4]}>
      {returns.data.results.map((r) => (
        <tr key={r.id}>
          <td>{dateTime(r.created_at)}</td>
          <td>{r.sale_number ? `nº ${r.sale_number}` : <Badge tone="amber">sem cupom</Badge>}</td>
          <td className="text-right">{r.lines.reduce((n, l) => n + l.quantity, 0)}</td>
          <td>{r.refund_method === 'cash' ? 'Dinheiro' : <span className="font-mono text-xs">{r.store_credit}</span>}</td>
          <td className="text-right">{brl(r.total)}</td>
          <td>{r.reason}</td>
          <td>{r.created_by}</td>
        </tr>
      ))}
    </Table>
  );
}
