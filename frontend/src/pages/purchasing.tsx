import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { type ScanLine, ScanLines } from '../components/ScanLines';
import {
  Alert,
  Badge,
  Button,
  Card,
  Dialog,
  Empty,
  ErrorAlert,
  Field,
  formData,
  Input,
  Loading,
  PageHeader,
  Select,
  Table,
  Tabs,
} from '../components/ui';
import { api, type Page, qs } from '../lib/api';
import { dateTime, day } from '../lib/format';
import { brl, toCents } from '../lib/money';
import { useSession } from '../lib/session';
import type { Order, OrderStatus, Receipt, Suggestion, Supplier } from '../lib/types';

const STATUS_TONE: Record<OrderStatus, 'neutral' | 'blue' | 'amber' | 'green' | 'red'> = {
  draft: 'neutral',
  sent: 'blue',
  partially_received: 'amber',
  received: 'green',
  closed: 'neutral',
  cancelled: 'red',
};

/** "12,50" → "12.5000": costs carry four decimals (the average cost does). */
const cost = (typed: string) => {
  const cents = toCents(typed);
  return Number.isNaN(cents) ? '0' : (cents / 100).toFixed(4);
};

export function PurchasingPage() {
  const { can, location } = useSession();
  const buyer = can('purchasing.manage');
  const [tab, setTab] = useState<'orders' | 'suggestions' | 'suppliers'>('orders');
  const [creating, setCreating] = useState(false);
  if (!location) return <Alert tone="info">Você não tem loja ou depósito atribuído.</Alert>;
  return (
    <div>
      <PageHeader
        title="Compras"
        description={`${location.name}: pedidos aos fornecedores e recebimento das notas, inclusive parcial.`}
        actions={buyer && <Button onClick={() => setCreating(true)}>Novo pedido</Button>}
      />
      {buyer && (
        <Tabs
          value={tab}
          onChange={setTab}
          options={[
            { value: 'orders', label: 'Pedidos' },
            { value: 'suggestions', label: 'Sugestão de compra' },
            { value: 'suppliers', label: 'Fornecedores' },
          ]}
        />
      )}
      {tab === 'orders' && <Orders locationId={location.id} />}
      {tab === 'suggestions' && <Suggestions onCreated={() => setTab('orders')} />}
      {tab === 'suppliers' && <Suppliers />}
      {creating && <NewOrder locationId={location.id} onClose={() => setCreating(false)} />}
    </div>
  );
}

function Orders({ locationId }: { locationId: number }) {
  const { can } = useSession();
  const [status, setStatus] = useState('');
  const [open, setOpen] = useState<number | null>(null);
  const orders = useQuery({
    queryKey: ['orders', locationId, status],
    queryFn: () => api.get<Page<Order>>(`/purchasing/orders${qs({ location: locationId, status, limit: 50 })}`),
  });
  return (
    <div className="space-y-3">
      <Select className="w-56" aria-label="Situação" value={status} onChange={(e) => setStatus(e.target.value)}>
        <option value="">Todas as situações</option>
        <option value="draft">Rascunho</option>
        <option value="sent">Enviado</option>
        <option value="partially_received">Recebido em parte</option>
        <option value="received">Recebido</option>
        <option value="closed">Encerrado</option>
        <option value="cancelled">Cancelado</option>
      </Select>
      {orders.isPending ? (
        <Loading />
      ) : orders.error ? (
        <ErrorAlert error={orders.error} />
      ) : !orders.data.results.length ? (
        <Empty>Nenhum pedido.</Empty>
      ) : (
        <Table head={['Pedido', 'Fornecedor', 'Situação', 'Previsão', 'Peças', ...(can('costs.view') ? ['Custo'] : []), 'Criado']} num={[4, 5]}>
          {orders.data.results.map((o) => (
            <tr key={o.id} className="cursor-pointer hover:bg-stone-50" onClick={() => setOpen(o.id)}>
              <td className="font-medium">{o.number}</td>
              <td>{o.supplier_name}</td>
              <td>
                <Badge tone={STATUS_TONE[o.status]}>{o.status_label}</Badge>
              </td>
              <td>{day(o.expected_on)}</td>
              <td className="text-right">
                {o.lines.reduce((n, l) => n + l.quantity_received, 0)} / {o.lines.reduce((n, l) => n + l.quantity_ordered, 0)}
              </td>
              {can('costs.view') && <td className="text-right">{brl(o.total_cost)}</td>}
              <td>{dateTime(o.created_at)}</td>
            </tr>
          ))}
        </Table>
      )}
      {open !== null && <OrderDialog orderId={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function OrderDialog({ orderId, onClose }: { orderId: number; onClose: () => void }) {
  const { can } = useSession();
  const [mode, setMode] = useState<'view' | 'receive' | 'cancel' | 'close'>('view');
  const order = useQuery({ queryKey: ['order', orderId], queryFn: () => api.get<Order>(`/purchasing/orders/${orderId}`) });
  const receipts = useQuery({
    queryKey: ['receipts', orderId],
    queryFn: () => api.get<Page<Receipt>>(`/purchasing/receipts?order=${orderId}`),
  });
  const send = useMutation({ mutationFn: () => api.post(`/purchasing/orders/${orderId}/send`) });
  const o = order.data;
  const open = o && (o.status === 'sent' || o.status === 'partially_received');
  return (
    <Dialog open onClose={onClose} title={o ? `Pedido ${o.number} · ${o.supplier_name}` : 'Pedido'} wide>
      {!o ? (
        <Loading />
      ) : mode === 'receive' ? (
        <Receive order={o} onDone={() => setMode('view')} />
      ) : mode === 'cancel' || mode === 'close' ? (
        <Finish order={o} kind={mode} onDone={() => setMode('view')} />
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-stone-600">
            <Badge tone={STATUS_TONE[o.status]}>{o.status_label}</Badge> · para {o.location_code} · criado por {o.created_by} em{' '}
            {dateTime(o.created_at)}
            {o.expected_on && ` · previsão ${day(o.expected_on)}`}
            {o.finish_reason && ` · ${o.finish_reason}`}
          </p>
          <Table head={['SKU', 'Produto', 'Pedido', 'Recebido', 'Falta', ...(can('costs.view') ? ['Custo un.'] : [])]} num={[2, 3, 4, 5]}>
            {o.lines.map((l) => (
              <tr key={l.id}>
                <td className="font-mono text-xs">{l.sku}</td>
                <td>
                  {l.product} <span className="text-stone-500">{l.color} · {l.size}</span>
                </td>
                <td className="text-right">{l.quantity_ordered}</td>
                <td className="text-right">{l.quantity_received}</td>
                <td className="text-right">{l.pending || '—'}</td>
                {can('costs.view') && <td className="text-right">{brl(l.unit_cost)}</td>}
              </tr>
            ))}
          </Table>
          {receipts.data && receipts.data.results.length > 0 && (
            <div>
              <h3 className="mb-1 text-sm font-medium text-stone-800">Recebimentos</h3>
              <ul className="text-sm text-stone-600">
                {receipts.data.results.map((r) => (
                  <li key={r.id}>
                    {dateTime(r.received_at)} · NF {r.invoice_number || '—'} · {r.lines.reduce((n, l) => n + l.quantity, 0)} peças ·{' '}
                    {r.received_by}
                    {r.cancelled_at && <Badge tone="red">estornado</Badge>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <ErrorAlert error={send.error} />
          <div className="flex flex-wrap justify-end gap-2 border-t border-stone-200 pt-4">
            {o.status === 'draft' && can('purchasing.manage') && (
              <>
                <Button variant="danger" onClick={() => setMode('cancel')}>
                  Cancelar pedido
                </Button>
                <Button onClick={() => send.mutate()} busy={send.isPending}>
                  Enviar ao fornecedor
                </Button>
              </>
            )}
            {open && can('purchasing.manage') && (
              <Button variant="secondary" onClick={() => setMode('close')}>
                Encerrar com falta
              </Button>
            )}
            {open && can('stock.receive') && <Button onClick={() => setMode('receive')}>Receber mercadoria</Button>}
          </div>
        </div>
      )}
    </Dialog>
  );
}

/** What arrived, line by line: a partial receipt leaves the rest pending on the order. */
function Receive({ order, onDone }: { order: Order; onDone: () => void }) {
  const pending = order.lines.filter((l) => l.pending > 0);
  const [quantities, setQuantities] = useState<Record<number, number>>(() => Object.fromEntries(pending.map((l) => [l.id, l.pending])));
  const [invoice, setInvoice] = useState('');
  const receive = useMutation({
    mutationFn: () =>
      api.post<Receipt>(`/purchasing/orders/${order.id}/receive`, {
        invoice_number: invoice,
        lines: Object.entries(quantities)
          .filter(([, q]) => q > 0)
          .map(([line, quantity]) => ({ order_line: Number(line), quantity })),
      }),
    onSuccess: onDone,
  });
  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        receive.mutate();
      }}
    >
      <p className="text-sm text-stone-600">Confira as caixas: ajuste o que veio de cada item. O que faltar continua pendente no pedido.</p>
      <ul className="divide-y divide-stone-100">
        {pending.map((l) => (
          <li key={l.id} className="flex items-center justify-between gap-3 py-2 text-sm">
            <span>
              {l.product} <span className="text-stone-500">{l.color} · {l.size}</span>
              <span className="block text-xs text-stone-500">faltam {l.pending}</span>
            </span>
            <Input
              type="number"
              min={0}
              max={l.pending}
              className="w-24 text-right"
              aria-label={`Recebido de ${l.sku}`}
              value={quantities[l.id] ?? 0}
              onChange={(e) => setQuantities((q) => ({ ...q, [l.id]: Math.min(l.pending, Math.max(0, Number(e.target.value))) }))}
            />
          </li>
        ))}
      </ul>
      <Field label="Número da nota fiscal">{(id) => <Input id={id} value={invoice} onChange={(e) => setInvoice(e.target.value)} className="w-48" />}</Field>
      <ErrorAlert error={receive.error} />
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onDone}>
          Voltar
        </Button>
        <Button type="submit" busy={receive.isPending} disabled={!Object.values(quantities).some((q) => q > 0)}>
          Dar entrada no estoque
        </Button>
      </div>
    </form>
  );
}

function Finish({ order, kind, onDone }: { order: Order; kind: 'cancel' | 'close'; onDone: () => void }) {
  const finish = useMutation({
    mutationFn: (reason: string) => api.post(`/purchasing/orders/${order.id}/${kind}`, { reason }),
    onSuccess: onDone,
  });
  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        finish.mutate(formData(e.currentTarget).reason ?? '');
      }}
    >
      <Alert tone="warning">
        {kind === 'cancel' ? 'O rascunho é cancelado; nada entra no estoque.' : 'O que ainda falta deixa de ser esperado: a sugestão de compra volta a pedir.'}
      </Alert>
      <Field label="Motivo">{(id) => <Input id={id} name="reason" required data-autofocus />}</Field>
      <ErrorAlert error={finish.error} />
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onDone}>
          Voltar
        </Button>
        <Button type="submit" variant="danger" busy={finish.isPending}>
          {kind === 'cancel' ? 'Cancelar pedido' : 'Encerrar pedido'}
        </Button>
      </div>
    </form>
  );
}

function useSuppliers() {
  return useQuery({ queryKey: ['suppliers'], queryFn: () => api.get<Page<Supplier>>('/purchasing/suppliers?limit=200') });
}

function NewOrder({ locationId, onClose }: { locationId: number; onClose: () => void }) {
  const suppliers = useSuppliers();
  const [lines, setLines] = useState<ScanLine[]>([]);
  const [costs, setCosts] = useState<Record<number, string>>({});
  const create = useMutation({
    mutationFn: (v: Record<string, string>) =>
      api.post<Order>('/purchasing/orders', {
        supplier: Number(v.supplier),
        location: locationId,
        expected_on: v.expected_on || null,
        notes: v.notes,
        lines: lines.map((l) => ({ variant: l.item.id, quantity: l.quantity, unit_cost: cost(costs[l.item.id] ?? '') })),
      }),
    onSuccess: onClose,
  });
  return (
    <Dialog open onClose={onClose} title="Novo pedido de compra" wide>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate(formData(e.currentTarget));
        }}
      >
        <div className="grid gap-3 sm:grid-cols-[1fr_12rem]">
          <Field label="Fornecedor">
            {(id) => (
              <Select id={id} name="supplier" required>
                {suppliers.data?.results.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Previsão de entrega">{(id) => <Input id={id} name="expected_on" type="date" />}</Field>
        </div>
        <ScanLines
          lines={lines}
          onChange={setLines}
          locationId={locationId}
          extra={(line) => (
            <Input
              className="w-28 text-right"
              inputMode="decimal"
              placeholder="Custo un."
              aria-label={`Custo unitário de ${line.item.sku}`}
              value={costs[line.item.id] ?? ''}
              onChange={(e) => setCosts((c) => ({ ...c, [line.item.id]: e.target.value }))}
            />
          )}
        />
        <Field label="Observações">{(id) => <Input id={id} name="notes" />}</Field>
        <ErrorAlert error={create.error} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" disabled={!lines.length || lines.some((l) => l.quantity < 1 || !costs[l.item.id])} busy={create.isPending}>
            Criar rascunho
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

/**
 * Below the minimum even counting what's already on order: enough to reach the maximum. One
 * click drafts the orders, one per store and last supplier, at the last cost paid.
 */
function Suggestions({ onCreated }: { onCreated: () => void }) {
  const suggestions = useQuery({ queryKey: ['suggestions'], queryFn: () => api.get<Suggestion[]>('/purchasing/suggestions') });
  const suppliers = useSuppliers();
  const draft = useMutation({
    mutationFn: async (rows: Suggestion[]) => {
      const groups = new Map<string, Suggestion[]>();
      for (const row of rows) {
        const key = `${row.location}:${row.last_supplier}`;
        groups.set(key, [...(groups.get(key) ?? []), row]);
      }
      for (const group of groups.values()) {
        const first = group[0]!;
        await api.post('/purchasing/orders', {
          supplier: first.last_supplier,
          location: first.location,
          notes: 'Gerado pela sugestão de compra',
          lines: group.map((r) => ({ variant: r.variant, quantity: r.suggested, unit_cost: r.last_unit_cost ?? '0' })),
        });
      }
    },
    onSuccess: onCreated,
  });
  if (suggestions.isPending) return <Loading />;
  if (suggestions.error) return <ErrorAlert error={suggestions.error} />;
  const rows = suggestions.data;
  if (!rows.length) return <Empty>Nada abaixo do mínimo: nenhuma compra sugerida.</Empty>;
  const withSupplier = rows.filter((r) => r.last_supplier !== null);
  const supplierName = (id: number | null) => suppliers.data?.results.find((s) => s.id === id)?.name ?? '—';
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-stone-600">
          {rows.length} SKU(s) abaixo do mínimo, contando o que já está em pedido.
        </p>
        <Button onClick={() => draft.mutate(withSupplier)} busy={draft.isPending} disabled={!withSupplier.length}>
          Gerar rascunhos de pedido
        </Button>
      </div>
      <ErrorAlert error={draft.error} />
      <Table head={['Local', 'SKU', 'Produto', 'Saldo', 'Em pedido', 'Mín.', 'Máx.', 'Sugerido', 'Último fornecedor', 'Último custo']} num={[3, 4, 5, 6, 7, 9]}>
        {rows.map((r) => (
          <tr key={`${r.location}-${r.variant}`}>
            <td>{r.location_code}</td>
            <td className="font-mono text-xs">{r.sku}</td>
            <td>{r.product}</td>
            <td className="text-right">{r.quantity}</td>
            <td className="text-right">{r.on_order}</td>
            <td className="text-right">{r.min_quantity}</td>
            <td className="text-right">{r.max_quantity ?? '—'}</td>
            <td className="text-right font-medium">{r.suggested}</td>
            <td>{supplierName(r.last_supplier)}</td>
            <td className="text-right">{brl(r.last_unit_cost)}</td>
          </tr>
        ))}
      </Table>
      <p className="text-xs text-stone-500">SKUs sem compra anterior ficam de fora dos rascunhos: escolha o fornecedor num pedido novo.</p>
    </div>
  );
}

function Suppliers() {
  const suppliers = useSuppliers();
  const add = useMutation({ mutationFn: (v: Record<string, string>) => api.post('/purchasing/suppliers', v) });
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
      {suppliers.isPending ? (
        <Loading />
      ) : (
        <Table head={['Fornecedor', 'CNPJ', 'Contato', 'E-mail', 'Telefone']}>
          {suppliers.data?.results.map((s) => (
            <tr key={s.id}>
              <td className="font-medium">{s.name}</td>
              <td className="font-mono text-xs">{s.cnpj}</td>
              <td>{s.contact}</td>
              <td>{s.email}</td>
              <td>{s.phone}</td>
            </tr>
          ))}
        </Table>
      )}
      <Card>
        <h2 className="mb-3 font-medium text-stone-900">Novo fornecedor</h2>
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            const form = e.currentTarget;
            add.mutate(formData(form), { onSuccess: () => form.reset() });
          }}
        >
          <Field label="Razão social ou nome">{(id) => <Input id={id} name="name" required />}</Field>
          <Field label="CNPJ" hint="Aceita o formato alfanumérico de 2026.">
            {(id) => <Input id={id} name="cnpj" placeholder="12.ABC.345/01DE-35" />}
          </Field>
          <Field label="Contato">{(id) => <Input id={id} name="contact" />}</Field>
          <Field label="E-mail">{(id) => <Input id={id} name="email" type="email" />}</Field>
          <Field label="Telefone">{(id) => <Input id={id} name="phone" />}</Field>
          <ErrorAlert error={add.error} />
          <Button type="submit" busy={add.isPending}>
            Cadastrar
          </Button>
        </form>
      </Card>
    </div>
  );
}
