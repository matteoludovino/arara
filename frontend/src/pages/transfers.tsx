import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { type ScanLine, ScanLines } from '../components/ScanLines';
import { Alert, Badge, Button, Dialog, Empty, ErrorAlert, Field, Input, Loading, PageHeader, Select, Table } from '../components/ui';
import { api, type Page, qs } from '../lib/api';
import { dateTime } from '../lib/format';
import { useSession } from '../lib/session';
import type { LocationRef, Transfer, TransferStatus } from '../lib/types';

const TONE: Record<TransferStatus, 'neutral' | 'blue' | 'green' | 'red'> = {
  draft: 'neutral',
  in_transit: 'blue',
  received: 'green',
  cancelled: 'red',
};

export function TransfersPage() {
  const { location } = useSession();
  const [creating, setCreating] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const transfers = useQuery({
    queryKey: ['transfers'],
    queryFn: () => api.get<Page<Transfer>>(`/transfers${qs({ limit: 50 })}`),
  });
  if (!location) return <Alert tone="info">Você não tem loja ou depósito atribuído.</Alert>;
  const here = (t: Transfer) => (t.origin === location.id ? 'out' : t.destination === location.id ? 'in' : null);
  return (
    <div>
      <PageHeader
        title="Transferências"
        description="Entre lojas e depósito. No caminho, as peças ficam no local “em trânsito”: não somem do estoque da empresa."
        actions={<Button onClick={() => setCreating(true)}>Nova transferência</Button>}
      />
      {transfers.isPending ? (
        <Loading />
      ) : transfers.error ? (
        <ErrorAlert error={transfers.error} />
      ) : !transfers.data.results.length ? (
        <Empty>Nenhuma transferência.</Empty>
      ) : (
        <Table head={['Número', 'De', 'Para', 'Situação', 'Peças', 'Criada', '']} num={[4]}>
          {transfers.data.results.map((t) => (
            <tr key={t.id} className="cursor-pointer hover:bg-stone-50" onClick={() => setOpen(t.id)}>
              <td className="font-medium">{t.number}</td>
              <td>{t.origin_code}</td>
              <td>{t.destination_code}</td>
              <td>
                <Badge tone={TONE[t.status]}>{t.status_label}</Badge>
              </td>
              <td className="text-right">{t.lines.reduce((n, l) => n + l.quantity_sent, 0)}</td>
              <td>{dateTime(t.created_at)}</td>
              <td>
                {t.status === 'in_transit' && here(t) === 'in' && <Badge tone="amber">chegando aqui</Badge>}
                {t.status === 'draft' && here(t) === 'out' && <Badge>a enviar</Badge>}
              </td>
            </tr>
          ))}
        </Table>
      )}
      {creating && <NewTransfer origin={location} onClose={() => setCreating(false)} />}
      {open !== null && <TransferDialog transferId={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function NewTransfer({ origin, onClose }: { origin: LocationRef; onClose: () => void }) {
  const destinations = useQuery({
    queryKey: ['destinations'],
    queryFn: () => api.get<LocationRef[]>('/transfers/destinations'),
  });
  const [destination, setDestination] = useState('');
  const [lines, setLines] = useState<ScanLine[]>([]);
  const [notes, setNotes] = useState('');
  const create = useMutation({
    mutationFn: async () => {
      const transfer = await api.post<Transfer>('/transfers', {
        origin: origin.id,
        destination: Number(destination),
        notes,
        lines: lines.map((l) => ({ variant: l.item.id, quantity: l.quantity })),
      });
      return api.post<Transfer>(`/transfers/${transfer.id}/dispatch`);
    },
    onSuccess: onClose,
  });
  return (
    <Dialog open onClose={onClose} title={`Transferir de ${origin.name}`} wide>
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Para">
            {(id) => (
              <Select id={id} value={destination} onChange={(e) => setDestination(e.target.value)} required>
                <option value="" disabled>
                  Escolha o destino
                </option>
                {destinations.data
                  ?.filter((d) => d.id !== origin.id)
                  .map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
                    </option>
                  ))}
              </Select>
            )}
          </Field>
          <Field label="Observação">{(id) => <Input id={id} value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={200} />}</Field>
        </div>
        <ScanLines lines={lines} onChange={setLines} locationId={origin.id} />
        <ErrorAlert error={create.error} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            Cancelar
          </Button>
          <Button disabled={!destination || !lines.length || lines.some((l) => l.quantity < 1)} busy={create.isPending} onClick={() => create.mutate()}>
            Enviar
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

function TransferDialog({ transferId, onClose }: { transferId: number; onClose: () => void }) {
  const { me } = useSession();
  const transfer = useQuery({ queryKey: ['transfer', transferId], queryFn: () => api.get<Transfer>(`/transfers/${transferId}`) });
  const [receiving, setReceiving] = useState(false);
  const [cancelReason, setCancelReason] = useState<string | null>(null);
  const dispatch = useMutation({ mutationFn: () => api.post(`/transfers/${transferId}/dispatch`) });
  const cancel = useMutation({
    mutationFn: () => api.post(`/transfers/${transferId}/cancel`, { reason: cancelReason }),
    onSuccess: () => setCancelReason(null),
  });
  const t = transfer.data;
  const worksAt = (id: number) => me.role === 'owner' || me.locations.some((l) => l.id === id);
  return (
    <Dialog open onClose={onClose} title={t ? `${t.number}: ${t.origin_code} → ${t.destination_code}` : 'Transferência'} wide>
      {!t ? (
        <Loading />
      ) : receiving ? (
        <Receive transfer={t} onDone={() => setReceiving(false)} />
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-stone-600">
            <Badge tone={TONE[t.status]}>{t.status_label}</Badge> · criada por {t.created_by} em {dateTime(t.created_at)}
            {t.dispatched_at && ` · enviada por ${t.dispatched_by} em ${dateTime(t.dispatched_at)}`}
            {t.received_at && ` · recebida por ${t.received_by} em ${dateTime(t.received_at)}`}
            {t.cancel_reason && ` · cancelada: ${t.cancel_reason}`}
          </p>
          <Table head={['SKU', 'Produto', 'Enviadas', 'Recebidas']} num={[2, 3]}>
            {t.lines.map((l) => (
              <tr key={l.id}>
                <td className="font-mono text-xs">{l.sku}</td>
                <td>
                  {l.product} <span className="text-stone-500">{l.color} · {l.size}</span>
                </td>
                <td className="text-right">{l.quantity_sent}</td>
                <td className={`text-right ${l.quantity_received !== null && l.quantity_received < l.quantity_sent ? 'font-medium text-red-700' : ''}`}>
                  {l.quantity_received ?? '—'}
                </td>
              </tr>
            ))}
          </Table>
          {cancelReason !== null && (
            <Field label="Motivo do cancelamento">
              {(id) => <Input id={id} value={cancelReason} onChange={(e) => setCancelReason(e.target.value)} data-autofocus />}
            </Field>
          )}
          <ErrorAlert error={dispatch.error ?? cancel.error} />
          <div className="flex flex-wrap justify-end gap-2 border-t border-stone-200 pt-4">
            {(t.status === 'draft' || t.status === 'in_transit') && worksAt(t.origin) && (
              <Button
                variant="danger"
                busy={cancel.isPending}
                disabled={cancelReason !== null && !cancelReason.trim()}
                onClick={() => (cancelReason === null ? setCancelReason('') : cancel.mutate())}
              >
                {cancelReason === null ? 'Cancelar' : 'Confirmar cancelamento'}
              </Button>
            )}
            {t.status === 'draft' && worksAt(t.origin) && (
              <Button onClick={() => dispatch.mutate()} busy={dispatch.isPending}>
                Enviar
              </Button>
            )}
            {t.status === 'in_transit' && worksAt(t.destination) && <Button onClick={() => setReceiving(true)}>Receber</Button>}
          </div>
        </div>
      )}
    </Dialog>
  );
}

/** What arrived. A shortage leaves transit as a loss, with the reason on record. */
function Receive({ transfer, onDone }: { transfer: Transfer; onDone: () => void }) {
  const [received, setReceived] = useState<Record<number, number>>(() => Object.fromEntries(transfer.lines.map((l) => [l.id, l.quantity_sent])));
  const [reason, setReason] = useState('');
  const short = transfer.lines.some((l) => (received[l.id] ?? 0) < l.quantity_sent);
  const receive = useMutation({
    mutationFn: () =>
      api.post(`/transfers/${transfer.id}/receive`, {
        lines: transfer.lines.map((l) => ({ line: l.id, quantity: received[l.id] ?? 0 })),
        missing_reason: reason,
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
      <p className="text-sm text-stone-600">Conte o que chegou. Se faltar algo, a diferença vira perda registrada, com o motivo.</p>
      <ul className="divide-y divide-stone-100">
        {transfer.lines.map((l) => (
          <li key={l.id} className="flex items-center justify-between gap-3 py-2 text-sm">
            <span>
              {l.product} <span className="text-stone-500">{l.color} · {l.size}</span>
              <span className="block text-xs text-stone-500">enviadas {l.quantity_sent}</span>
            </span>
            <Input
              type="number"
              min={0}
              max={l.quantity_sent}
              className="w-24 text-right"
              aria-label={`Chegaram de ${l.sku}`}
              value={received[l.id] ?? 0}
              onChange={(e) => setReceived((r) => ({ ...r, [l.id]: Math.min(l.quantity_sent, Math.max(0, Number(e.target.value))) }))}
            />
          </li>
        ))}
      </ul>
      {short && (
        <Field label="O que aconteceu com o que faltou?">
          {(id) => <Input id={id} value={reason} onChange={(e) => setReason(e.target.value)} required placeholder="Ex.: caixa chegou aberta" />}
        </Field>
      )}
      <ErrorAlert error={receive.error} />
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onDone}>
          Voltar
        </Button>
        <Button type="submit" busy={receive.isPending}>
          Confirmar recebimento
        </Button>
      </div>
    </form>
  );
}
