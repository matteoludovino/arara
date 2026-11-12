import { useMutation, useQuery } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { Alert, Badge, Button, Card, Dialog, Empty, ErrorAlert, Field, Input, Loading, PageHeader, Select, Table } from '../components/ui';
import { api, type Page, qs } from '../lib/api';
import { dateTime, signed } from '../lib/format';
import { useSession } from '../lib/session';
import type { Count, CountEntry, CountStatus, Named } from '../lib/types';

interface ReviewRow {
  variant_id: number;
  sku: string;
  product: string;
  counted: number | null;
  expected: number;
  current: number;
  difference: number | null;
  moved_during_count: boolean;
  needs_recount: boolean;
  areas: Record<string, number>;
}

const TONE: Record<CountStatus, 'blue' | 'amber' | 'green' | 'red'> = {
  counting: 'blue',
  review: 'amber',
  applied: 'green',
  cancelled: 'red',
};

export function CountsPage() {
  const { location, can } = useSession();
  const [opening, setOpening] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const counts = useQuery({
    queryKey: ['counts', location?.id],
    queryFn: () => api.get<Page<Count>>(`/counts${qs({ location: location?.id, limit: 30 })}`),
    enabled: !!location,
  });
  if (!location) return <Alert tone="info">Você não tem loja ou depósito atribuído.</Alert>;
  if (open !== null) return <CountScreen countId={open} onBack={() => setOpen(null)} />;
  return (
    <div>
      <PageHeader
        title="Inventário"
        description={`${location.name}: contagem cega, por área. A loja continua vendendo durante a contagem.`}
        actions={can('stock.count_apply') && <Button onClick={() => setOpening(true)}>Abrir contagem</Button>}
      />
      {counts.isPending ? (
        <Loading />
      ) : counts.error ? (
        <ErrorAlert error={counts.error} />
      ) : !counts.data.results.length ? (
        <Empty>Nenhuma contagem nesta loja.</Empty>
      ) : (
        <Table head={['Aberta', 'Escopo', 'Situação', 'SKUs contados', 'Por', '']} num={[3]}>
          {counts.data.results.map((c) => (
            <tr key={c.id}>
              <td>{dateTime(c.opened_at)}</td>
              <td>{c.scope_label}</td>
              <td>
                <Badge tone={TONE[c.status]}>{c.status_label}</Badge>
              </td>
              <td className="text-right">
                {c.counted_skus} / {c.scope_size}
              </td>
              <td>{c.opened_by}</td>
              <td>
                {(c.status === 'counting' || c.status === 'review') && (
                  <Button variant="secondary" className="py-1" onClick={() => setOpen(c.id)}>
                    {c.status === 'counting' ? 'Contar' : 'Revisar'}
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </Table>
      )}
      {opening && <OpenCount locationId={location.id} onClose={() => setOpening(false)} onOpened={(id) => (setOpening(false), setOpen(id))} />}
    </div>
  );
}

function OpenCount({ locationId, onClose, onOpened }: { locationId: number; onClose: () => void; onOpened: (id: number) => void }) {
  const categories = useQuery({ queryKey: ['categories'], queryFn: () => api.get<Page<Named>>('/catalog/categories?limit=200') });
  const [picked, setPicked] = useState<number[]>([]);
  const [tolerance, setTolerance] = useState('0');
  const [note, setNote] = useState('');
  const create = useMutation({
    mutationFn: () => api.post<Count>('/counts', { location: locationId, categories: picked, tolerance: Number(tolerance), note }),
    onSuccess: (count) => onOpened(count.id),
  });
  return (
    <Dialog open onClose={onClose} title="Abrir contagem">
      <div className="space-y-4">
        <fieldset>
          <legend className="text-sm font-medium text-stone-700">O que contar</legend>
          <p className="text-xs text-stone-500">Sem categoria marcada: a loja inteira.</p>
          <div className="mt-2 flex flex-wrap gap-3">
            {categories.data?.results.map((c) => (
              <label key={c.id} className="inline-flex items-center gap-1.5 text-sm">
                <input
                  type="checkbox"
                  checked={picked.includes(c.id)}
                  onChange={(e) => setPicked((ps) => (e.target.checked ? [...ps, c.id] : ps.filter((x) => x !== c.id)))}
                />
                {c.name}
              </label>
            ))}
          </div>
        </fieldset>
        <div className="grid grid-cols-[8rem_1fr] gap-3">
          <Field label="Tolerância (peças)" hint="Diferença acima disso pede recontagem.">
            {(id) => <Input id={id} type="number" min={0} max={100} value={tolerance} onChange={(e) => setTolerance(e.target.value)} />}
          </Field>
          <Field label="Observação">{(id) => <Input id={id} value={note} onChange={(e) => setNote(e.target.value)} />}</Field>
        </div>
        <ErrorAlert error={create.error} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            Cancelar
          </Button>
          <Button busy={create.isPending} onClick={() => create.mutate()}>
            Abrir
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

function CountScreen({ countId, onBack }: { countId: number; onBack: () => void }) {
  const { can } = useSession();
  const count = useQuery({ queryKey: ['count', countId], queryFn: () => api.get<Count>(`/counts/${countId}`) });
  if (!count.data) return <Loading />;
  const c = count.data;
  return (
    <div>
      <PageHeader
        title={`Contagem · ${c.location_code}`}
        description={
          <>
            <button type="button" className="text-brand-700 hover:underline" onClick={onBack}>
              Inventário
            </button>{' '}
            · {c.scope_label} · <Badge tone={TONE[c.status]}>{c.status_label}</Badge> · {c.counted_skus} de {c.scope_size} SKUs contados
          </>
        }
      />
      {c.status === 'counting' && <Counting count={c} />}
      {c.status === 'review' && (can('stock.count_apply') ? <Review count={c} onApplied={onBack} /> : <Alert tone="info">Contagem encerrada: aguardando a revisão do gerente.</Alert>)}
    </div>
  );
}

/** Blind: the person counting never sees what the system expects, only what they've entered. */
function Counting({ count }: { count: Count }) {
  const { can } = useSession();
  const [area, setArea] = useState('');
  const [code, setCode] = useState('');
  const [quantity, setQuantity] = useState('1');
  const codeRef = useRef<HTMLInputElement>(null);
  const entries = useQuery({ queryKey: ['entries', count.id], queryFn: () => api.get<CountEntry[]>(`/counts/${count.id}/entries`) });
  const add = useMutation({
    mutationFn: () => api.post<CountEntry>(`/counts/${count.id}/entries`, { code: code.trim(), quantity: Number(quantity), area }),
    onSuccess: () => {
      setCode('');
      setQuantity('1');
      codeRef.current?.focus();
    },
  });
  const remove = useMutation({ mutationFn: (id: number) => api.delete(`/counts/${count.id}/entries/${id}`) });
  const finish = useMutation({ mutationFn: () => api.post(`/counts/${count.id}/finish`) });
  return (
    <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
      <Card className="h-fit">
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            add.mutate();
          }}
        >
          <Field label="Área" hint="Onde as peças estão: arara da frente, vitrine, estoque…">
            {(id) => <Input id={id} value={area} onChange={(e) => setArea(e.target.value)} placeholder="Arara da frente" />}
          </Field>
          <Field label="Código de barras ou SKU">
            {(id) => <Input id={id} ref={codeRef} value={code} onChange={(e) => setCode(e.target.value)} required autoFocus autoComplete="off" />}
          </Field>
          <Field label="Quantidade">{(id) => <Input id={id} type="number" min={0} value={quantity} onChange={(e) => setQuantity(e.target.value)} required />}</Field>
          <ErrorAlert error={add.error} />
          <Button type="submit" className="w-full" busy={add.isPending}>
            Registrar
          </Button>
        </form>
        {can('stock.count_apply') && (
          <div className="mt-4 border-t border-stone-200 pt-4">
            <ErrorAlert error={finish.error} />
            <Button variant="secondary" className="w-full" busy={finish.isPending} onClick={() => finish.mutate()}>
              Encerrar contagem e revisar
            </Button>
          </div>
        )}
      </Card>
      <div>
        <h2 className="mb-2 text-sm font-medium text-stone-700">Lançamentos</h2>
        {!entries.data?.length ? (
          <Empty>Nenhum lançamento ainda.</Empty>
        ) : (
          <Table head={['Quando', 'Área', 'SKU', 'Qtd.', 'Por', '']} num={[3]}>
            {entries.data.map((e) => (
              <tr key={e.id}>
                <td>{dateTime(e.created_at)}</td>
                <td>{e.area || '—'}</td>
                <td className="font-mono text-xs">{e.sku}</td>
                <td className="text-right">{e.quantity}</td>
                <td>{e.counted_by}</td>
                <td>
                  <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => remove.mutate(e.id)}>
                    Desfazer
                  </Button>
                </td>
              </tr>
            ))}
          </Table>
        )}
      </div>
    </div>
  );
}

/**
 * The manager sees counted against expected. Applying adds the difference to the stock (it
 * never sets the balance), so sales made during the count are kept.
 */
function Review({ count, onApplied }: { count: Count; onApplied: () => void }) {
  const rows = useQuery({ queryKey: ['review', count.id], queryFn: () => api.get<ReviewRow[]>(`/counts/${count.id}/review`) });
  const [uncounted, setUncounted] = useState<'keep' | 'zero'>('keep');
  const recount = useMutation({
    mutationFn: (variants: number[]) => api.post(`/counts/${count.id}/recount`, { variants }),
  });
  const apply = useMutation({
    mutationFn: () => api.post(`/counts/${count.id}/apply`, { uncounted }),
    onSuccess: onApplied,
  });
  if (rows.isPending) return <Loading />;
  if (rows.error) return <ErrorAlert error={rows.error} />;
  const flagged = rows.data.filter((r) => r.needs_recount).map((r) => r.variant_id);
  // Uncounted with nothing expected: nothing to decide.
  const unsettled = (r: ReviewRow) => r.counted === null && r.expected > 0;
  const missing = rows.data.filter(unsettled).length;
  const differences = rows.data.filter((r) => r.difference);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2 text-sm">
        <Badge tone={differences.length ? 'amber' : 'green'}>{differences.length} SKU(s) com diferença</Badge>
        {flagged.length > 0 && <Badge tone="red">{flagged.length} pedem recontagem</Badge>}
        {missing > 0 && <Badge>{missing} com saldo e não contados</Badge>}
      </div>
      <Table head={['SKU', 'Produto', 'Esperado', 'Contado', 'Diferença', 'Agora', '']} num={[2, 3, 4, 5]}>
        {rows.data
          .filter((r) => r.difference || unsettled(r) || r.needs_recount)
          .map((r) => (
            <tr key={r.variant_id}>
              <td className="font-mono text-xs">{r.sku}</td>
              <td>{r.product}</td>
              <td className="text-right">{r.expected}</td>
              <td className="text-right">{r.counted ?? '—'}</td>
              <td className={`text-right font-medium ${(r.difference ?? 0) < 0 ? 'text-red-700' : 'text-emerald-700'}`}>
                {r.difference === null ? '—' : signed(r.difference)}
              </td>
              <td className="text-right">{r.current}</td>
              <td>
                {r.needs_recount && <Badge tone="red">recontar</Badge>}
                {r.moved_during_count && <Badge tone="blue">vendeu durante</Badge>}
              </td>
            </tr>
          ))}
      </Table>
      <p className="text-xs text-stone-500">
        “Esperado” é o saldo no momento em que o SKU foi contado; “agora” inclui o que vendeu depois. O ajuste soma a diferença ao
        saldo de agora.
      </p>
      {missing > 0 && (
        <Field label={`${missing} SKU(s) com saldo ninguém contou`}>
          {(id) => (
            <Select id={id} className="w-80" value={uncounted} onChange={(e) => setUncounted(e.target.value as 'keep' | 'zero')}>
              <option value="keep">Manter o saldo do sistema</option>
              <option value="zero">Zerar: não existem na loja</option>
            </Select>
          )}
        </Field>
      )}
      <ErrorAlert error={recount.error ?? apply.error} />
      <div className="flex flex-wrap justify-end gap-2">
        {flagged.length > 0 && (
          <Button variant="secondary" busy={recount.isPending} onClick={() => recount.mutate(flagged)}>
            Mandar recontar {flagged.length}
          </Button>
        )}
        <Button busy={apply.isPending} onClick={() => apply.mutate()}>
          Aplicar ajustes
        </Button>
      </div>
    </div>
  );
}
