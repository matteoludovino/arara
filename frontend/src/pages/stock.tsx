import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { ApprovalDialog } from '../components/ApprovalDialog';
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
  Input,
  Loading,
  PageHeader,
  Select,
  Table,
  Tabs,
} from '../components/ui';
import { api, ApiError, type Page, qs } from '../lib/api';
import { dateTime, signed } from '../lib/format';
import { brl } from '../lib/money';
import { useSession } from '../lib/session';
import type { AdjustmentReason, Movement, StockLevel } from '../lib/types';

const REASONS: Record<AdjustmentReason, string> = {
  damaged: 'Avaria',
  theft: 'Furto',
  found: 'Encontrado',
  error: 'Erro de lançamento',
  other: 'Outro',
};

const KINDS: Record<string, string> = {
  purchase_receipt: 'Recebimento de compra',
  receipt_cancellation: 'Estorno de recebimento',
  purchase_return: 'Devolução ao fornecedor',
  sale: 'Venda',
  sale_cancellation: 'Cancelamento de venda',
  sale_return: 'Devolução de cliente',
  transfer_dispatch: 'Envio de transferência',
  transfer_receipt: 'Recebimento de transferência',
  adjustment: 'Ajuste manual',
  count_adjustment: 'Acerto de inventário',
  cost_adjustment: 'Ajuste de custo',
};

export function StockPage() {
  const { location } = useSession();
  const [tab, setTab] = useState<'levels' | 'ledger' | 'adjust'>('levels');
  if (!location) return <Alert tone="info">Você não tem loja ou depósito atribuído.</Alert>;
  return (
    <div>
      <PageHeader title="Estoque" description={`${location.name}: saldos, movimentos do razão e ajustes.`} />
      <Tabs
        value={tab}
        onChange={setTab}
        options={[
          { value: 'levels', label: 'Saldos' },
          { value: 'ledger', label: 'Movimentos' },
          { value: 'adjust', label: 'Ajuste' },
        ]}
      />
      {tab === 'levels' && <Levels locationId={location.id} />}
      {tab === 'ledger' && <Ledger locationId={location.id} />}
      {tab === 'adjust' && <Adjustment locationId={location.id} onDone={() => setTab('ledger')} />}
    </div>
  );
}

function Levels({ locationId }: { locationId: number }) {
  const { can } = useSession();
  const [q, setQ] = useState('');
  const [belowMin, setBelowMin] = useState(false);
  const [editing, setEditing] = useState<StockLevel | null>(null);
  const levels = useQuery({
    queryKey: ['levels', locationId, q, belowMin],
    queryFn: () =>
      api.get<Page<StockLevel>>(`/stock/levels${qs({ location: locationId, q, below_min: belowMin || undefined, limit: 200 })}`),
  });
  const costs = can('costs.view');
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <Input className="w-64" placeholder="SKU, referência ou nome" value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="inline-flex items-center gap-2 text-sm text-stone-700">
          <input type="checkbox" checked={belowMin} onChange={(e) => setBelowMin(e.target.checked)} />
          Só abaixo do mínimo
        </label>
        {levels.data && <span className="text-sm text-stone-500">{levels.data.count} SKU(s)</span>}
      </div>
      {levels.isPending ? (
        <Loading />
      ) : levels.error ? (
        <ErrorAlert error={levels.error} />
      ) : !levels.data.results.length ? (
        <Empty>Nada por aqui.</Empty>
      ) : (
        <Table
          head={['SKU', 'Produto', 'Cor', 'Tam.', 'Saldo', 'Mín.', 'Máx.', ...(costs ? ['Custo médio', 'Valor'] : []), '']}
          num={[4, 5, 6, 7, 8]}
        >
          {levels.data.results.map((l) => (
            <tr key={l.id}>
              <td className="font-mono text-xs">{l.sku}</td>
              <td>{l.product}</td>
              <td>{l.color}</td>
              <td>{l.size}</td>
              <td className="text-right font-medium">
                {l.below_min && <Badge tone="amber">baixo</Badge>} {l.quantity}
              </td>
              <td className="text-right">{l.min_quantity}</td>
              <td className="text-right">{l.max_quantity ?? '—'}</td>
              {costs && <td className="text-right">{brl(l.average_cost)}</td>}
              {costs && <td className="text-right">{brl(l.stock_value)}</td>}
              <td>
                {can('stock.adjust') && (
                  <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => setEditing(l)}>
                    Mín./máx.
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </Table>
      )}
      {editing && <Targets level={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

/** Restock targets: below the minimum, the purchase suggestion asks for enough to reach the maximum. */
function Targets({ level, onClose }: { level: StockLevel; onClose: () => void }) {
  const [min, setMin] = useState(String(level.min_quantity));
  const [max, setMax] = useState(level.max_quantity === null ? '' : String(level.max_quantity));
  const save = useMutation({
    mutationFn: () =>
      api.patch(`/stock/levels/${level.id}`, { min_quantity: Number(min), max_quantity: max === '' ? null : Number(max) }),
    onSuccess: onClose,
  });
  return (
    <Dialog open onClose={onClose} title={`Mínimo e máximo · ${level.sku}`}>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <div className="grid grid-cols-2 gap-3">
          <Field label="Mínimo">{(id) => <Input id={id} type="number" min={0} value={min} onChange={(e) => setMin(e.target.value)} data-autofocus />}</Field>
          <Field label="Máximo">{(id) => <Input id={id} type="number" min={0} value={max} onChange={(e) => setMax(e.target.value)} />}</Field>
        </div>
        <ErrorAlert error={save.error} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" busy={save.isPending}>
            Salvar
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function Ledger({ locationId }: { locationId: number }) {
  const { can } = useSession();
  const [kind, setKind] = useState('');
  const movements = useQuery({
    queryKey: ['movements', locationId, kind],
    queryFn: () => api.get<Page<Movement>>(`/stock/movements${qs({ location: locationId, entry__kind: kind, limit: 100 })}`),
  });
  const costs = can('costs.view');
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <Select className="w-64" aria-label="Tipo" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">Todos os tipos</option>
          {Object.entries(KINDS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </Select>
        <p className="text-sm text-stone-500">O razão só cresce: nada é editado ou apagado, um erro se corrige com outro lançamento.</p>
      </div>
      {movements.isPending ? (
        <Loading />
      ) : movements.error ? (
        <ErrorAlert error={movements.error} />
      ) : !movements.data.results.length ? (
        <Empty>Nenhum movimento.</Empty>
      ) : (
        <Table head={['Quando', 'Tipo', 'SKU', 'Qtd.', 'Saldo', ...(costs ? ['Valor'] : []), 'Por', 'Obs.']} num={[3, 4, 5]}>
          {movements.data.results.map((m) => (
            <tr key={m.id}>
              <td className="whitespace-nowrap">{dateTime(m.created_at)}</td>
              <td>
                {m.kind_label}
                {m.reason && <span className="text-stone-500"> · {REASONS[m.reason as AdjustmentReason] ?? m.reason}</span>}
              </td>
              <td className="font-mono text-xs">{m.sku}</td>
              <td className={`text-right font-medium ${m.quantity_delta < 0 ? 'text-red-700' : 'text-emerald-700'}`}>
                {signed(m.quantity_delta)}
              </td>
              <td className="text-right">{m.balance_after}</td>
              {costs && <td className="text-right">{brl(m.value_delta)}</td>}
              <td>{m.created_by}</td>
              <td className="max-w-48 truncate text-stone-500" title={m.note}>
                {m.note}
              </td>
            </tr>
          ))}
        </Table>
      )}
    </div>
  );
}

/**
 * Pieces found or missing, outside a count. A manager adjusts their own store; anyone else
 * needs a manager's approval, given on this screen.
 */
function Adjustment({ locationId, onDone }: { locationId: number; onDone: () => void }) {
  const [lines, setLines] = useState<ScanLine[]>([]);
  const [reason, setReason] = useState<AdjustmentReason>('damaged');
  const [note, setNote] = useState('');
  const [needsApproval, setNeedsApproval] = useState(false);
  const adjust = useMutation({
    mutationFn: (approval?: number) =>
      api.post('/stock/adjustments', {
        location: locationId,
        reason,
        note,
        lines: lines.map((l) => ({ variant: l.item.id, quantity_delta: l.quantity })),
        ...(approval && { approval }),
      }),
    onSuccess: onDone,
    onError: (error) => setNeedsApproval(error instanceof ApiError && error.code === 'adjustment_needs_approval'),
  });
  return (
    <Card className="max-w-3xl space-y-4">
      <p className="text-sm text-stone-600">
        Quantidade positiva para peças encontradas (entram pelo custo médio), negativa para as que faltam (saem para
        perdas).
      </p>
      <ScanLines lines={lines} onChange={setLines} signed locationId={locationId} />
      <div className="grid gap-3 sm:grid-cols-[12rem_1fr]">
        <Field label="Motivo">
          {(id) => (
            <Select id={id} value={reason} onChange={(e) => setReason(e.target.value as AdjustmentReason)}>
              {Object.entries(REASONS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Observação">{(id) => <Input id={id} value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} />}</Field>
      </div>
      {!needsApproval && <ErrorAlert error={adjust.error} />}
      <div className="flex justify-end">
        <Button disabled={!lines.length || lines.some((l) => l.quantity === 0)} busy={adjust.isPending} onClick={() => adjust.mutate(undefined)}>
          Lançar ajuste
        </Button>
      </div>
      {needsApproval && (
        <ApprovalDialog
          action="stock_adjustment"
          location={locationId}
          detail={`${REASONS[reason]}: ${lines.map((l) => `${signed(l.quantity)} ${l.item.sku}`).join(', ')}`}
          onClose={() => setNeedsApproval(false)}
          onApproved={(approval) => {
            setNeedsApproval(false);
            adjust.mutate(approval.id);
          }}
        />
      )}
    </Card>
  );
}
