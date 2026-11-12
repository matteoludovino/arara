import { useQuery } from '@tanstack/react-query';
import { useLayoutEffect, useRef, useState } from 'react';
import { ProductPicker } from '../components/ProductPicker';
import { Alert, Badge, Button, Card, Empty, ErrorAlert, Field, Input, Loading, PageHeader, Select, Stat, Table, Tabs } from '../components/ui';
import { api, qs } from '../lib/api';
import { day as dayLabel, int, percent, today } from '../lib/format';
import { brl, toCents } from '../lib/money';
import { useSession } from '../lib/session';
import type { Lookup } from '../lib/types';

interface DayTotals {
  day?: string;
  sales: number;
  units: number;
  gross: string;
  discounts: string;
  returns: string;
  net: string;
  average_ticket: string | null;
  cogs?: string;
  margin?: string;
  margin_percent?: string | null;
}

interface Filters {
  from: string;
  to: string;
  location: string;
}

type Tab = 'sales' | 'people' | 'abc' | 'grid' | 'valuation' | 'turnover' | 'stale';

export function ReportsPage() {
  const { me, can } = useSession();
  const [tab, setTab] = useState<Tab>('sales');
  const [filters, setFilters] = useState<Filters>({ from: today(-29), to: today(), location: '' });
  const stock = can('costs.view');
  const set = (patch: Partial<Filters>) => setFilters((f) => ({ ...f, ...patch }));
  const usesPeriod = tab !== 'valuation' && tab !== 'stale';
  return (
    <div>
      <PageHeader title="Relatórios" description="Vendas líquidas de devoluções; estoque valorizado pelo custo médio, a partir do razão." />
      <Tabs
        value={tab}
        onChange={setTab}
        options={[
          { value: 'sales', label: 'Vendas' },
          { value: 'people', label: 'Vendedores' },
          { value: 'abc', label: 'Curva ABC' },
          { value: 'grid', label: 'Tamanho × cor' },
          ...(stock
            ? ([
                { value: 'valuation', label: 'Valor do estoque' },
                { value: 'turnover', label: 'Giro e cobertura' },
                { value: 'stale', label: 'Parados' },
              ] as const)
            : []),
        ]}
      />
      <div className="mb-5 flex flex-wrap items-end gap-3">
        {me.locations.length > 1 && (
          <Field label="Onde">
            {(id) => (
              <Select id={id} className="w-48" value={filters.location} onChange={(e) => set({ location: e.target.value })}>
                <option value="">Todas as minhas lojas</option>
                {me.locations.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        )}
        {usesPeriod && (
          <>
            <Field label="De">{(id) => <Input id={id} type="date" className="w-40" value={filters.from} onChange={(e) => set({ from: e.target.value })} />}</Field>
            <Field label="Até">{(id) => <Input id={id} type="date" className="w-40" value={filters.to} onChange={(e) => set({ to: e.target.value })} />}</Field>
            <div className="flex gap-1">
              {[7, 30, 90].map((n) => (
                <Button key={n} variant="ghost" onClick={() => set({ from: today(-(n - 1)), to: today() })}>
                  {n} dias
                </Button>
              ))}
            </div>
          </>
        )}
      </div>
      {tab === 'sales' && <Sales filters={filters} />}
      {tab === 'people' && <People filters={filters} />}
      {tab === 'abc' && <Abc filters={filters} />}
      {tab === 'grid' && <SizeColor filters={filters} />}
      {tab === 'valuation' && <Valuation location={filters.location} />}
      {tab === 'turnover' && <Turnover filters={filters} />}
      {tab === 'stale' && <Stale location={filters.location} />}
    </div>
  );
}

function useReport<T>(name: string, params: Record<string, string | number | undefined>) {
  return useQuery({
    queryKey: ['report', name, params],
    queryFn: () => api.get<T>(`/reports/${name}${qs(params)}`),
  });
}

const period = (f: Filters) => ({ from: f.from, to: f.to, location: f.location || undefined });

function Sales({ filters }: { filters: Filters }) {
  const report = useReport<{ days: DayTotals[]; total: DayTotals }>('sales', period(filters));
  if (report.isPending) return <Loading />;
  if (report.error) return <ErrorAlert error={report.error} />;
  const { days, total } = report.data;
  const margin = total.margin !== undefined;
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Vendas líquidas" value={brl(total.net)} hint={`${int(total.sales)} vendas · ${int(total.units)} peças`} />
        <Stat label="Ticket médio" value={brl(total.average_ticket)} hint={`descontos ${brl(total.discounts)}`} />
        <Stat label="Devoluções" value={brl(total.returns)} />
        {margin && <Stat label="Margem bruta" value={brl(total.margin)} hint={`${percent(total.margin_percent)} · CMV ${brl(total.cogs)}`} />}
      </div>
      <Card>
        <h2 className="mb-1 font-medium text-stone-900">Vendas líquidas por dia</h2>
        <p className="mb-4 text-xs text-stone-500">Dias sem venda ficam vazios. Passe o mouse numa coluna para ver o valor.</p>
        <DailyColumns days={days} from={filters.from} to={filters.to} />
      </Card>
      {days.length ? (
        <Table
          head={['Dia', 'Vendas', 'Peças', 'Bruto', 'Descontos', 'Devoluções', 'Líquido', ...(margin ? ['CMV', 'Margem'] : [])]}
          num={[1, 2, 3, 4, 5, 6, 7, 8]}
        >
          {[...days].reverse().map((d) => (
            <tr key={d.day}>
              <td>{dayLabel(d.day)}</td>
              <td className="text-right">{d.sales}</td>
              <td className="text-right">{d.units}</td>
              <td className="text-right">{brl(d.gross)}</td>
              <td className="text-right">{brl(d.discounts)}</td>
              <td className="text-right">{brl(d.returns)}</td>
              <td className="text-right font-medium">{brl(d.net)}</td>
              {margin && <td className="text-right">{brl(d.cogs)}</td>}
              {margin && <td className="text-right">{percent(d.margin_percent)}</td>}
            </tr>
          ))}
        </Table>
      ) : (
        <Empty>Nenhuma venda no período.</Empty>
      )}
    </div>
  );
}

/** A clean axis: 0 and up to four even steps of 1, 2 or 5 × a power of ten. */
function ticks(max: number): number[] {
  if (max <= 0) return [0];
  const rough = max / 4;
  const power = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 5, 10].map((m) => m * power).find((s) => s >= rough) ?? power * 10;
  return Array.from({ length: Math.ceil(max / step) + 1 }, (_, i) => i * step);
}

const compact = new Intl.NumberFormat('pt-BR', { notation: 'compact', maximumFractionDigits: 1 });

/** One column per calendar day of the period; the net can be negative (more returned than sold). */
function DailyColumns({ days, from, to }: { days: DayTotals[]; from: string; to: string }) {
  const [hover, setHover] = useState<number | null>(null);
  // Drawn at the container's real width: text stays at its true size instead of scaling.
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(720);
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => entry && setWidth(Math.max(320, Math.round(entry.contentRect.width))));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const byDay = new Map(days.map((d) => [d.day, d]));
  const all: { day: string; net: number; data?: DayTotals }[] = [];
  for (let t = Date.parse(`${from}T12:00:00Z`); t <= Date.parse(`${to}T12:00:00Z`); t += 86_400_000) {
    const key = new Date(t).toISOString().slice(0, 10);
    const data = byDay.get(key);
    all.push({ day: key, net: data ? toCents(data.net) / 100 : 0, data });
  }
  const scale = ticks(Math.max(...all.map((d) => d.net), 0));
  const top = scale[scale.length - 1] || 1;
  const height = 220;
  const left = 48;
  const bottom = 24;
  const plot = { w: width - left - 8, h: height - bottom - 8 };
  const band = plot.w / Math.max(all.length, 1);
  const bar = Math.min(24, Math.max(2, band - 2));
  const y = (v: number) => 8 + plot.h - (Math.max(v, 0) / top) * plot.h;
  const every = Math.ceil(all.length / 10);
  const current = hover !== null ? all[hover] : undefined;
  return (
    <div className="relative" ref={box}>
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="block" role="img" aria-label="Vendas líquidas por dia">
        {scale.map((v) => (
          <g key={v}>
            <line x1={left} x2={width - 8} y1={y(v)} y2={y(v)} stroke="#e7e5e4" strokeWidth={1} />
            <text x={left - 6} y={y(v) + 4} textAnchor="end" className="fill-stone-500 text-[11px]">
              {top >= 10_000 ? compact.format(v) : int(v)}
            </text>
          </g>
        ))}
        {all.map((d, i) => {
          const x = left + i * band + (band - bar) / 2;
          const h = Math.max(0, y(0) - y(d.net));
          const r = Math.min(4, h, bar / 2);
          return (
            <g key={d.day} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={left + i * band} y={8} width={band} height={plot.h} fill="transparent" />
              {h > 0 && (
                <path
                  d={`M${x},${y(0)} v${-(h - r)} q0,${-r} ${r},${-r} h${bar - 2 * r} q${r},0 ${r},${r} v${h - r} z`}
                  className={hover === i ? 'fill-brand-700' : 'fill-brand-600'}
                />
              )}
              {i % every === 0 && (
                <text x={left + i * band + band / 2} y={height - 6} textAnchor="middle" className="fill-stone-500 text-[11px]">
                  {d.day.slice(8, 10)}/{d.day.slice(5, 7)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      {current && hover !== null && (
        <div
          className="pointer-events-none absolute top-0 z-10 rounded-lg border border-stone-200 bg-white px-3 py-2 text-xs shadow-md"
          style={{ left: `${((left + hover * band + band / 2) / width) * 100}%`, transform: 'translateX(-50%)' }}
        >
          <p className="font-medium text-stone-900">{dayLabel(current.day)}</p>
          {current.data ? (
            <p className="text-stone-600">
              {brl(current.data.net)} · {current.data.sales} venda(s)
            </p>
          ) : (
            <p className="text-stone-500">Sem vendas</p>
          )}
        </div>
      )}
    </div>
  );
}

function People({ filters }: { filters: Filters }) {
  const report = useReport<{ salesperson: number | null; name: string; sales: number; net: string; average_ticket: string }[]>(
    'salespeople',
    period(filters),
  );
  if (report.isPending) return <Loading />;
  if (report.error) return <ErrorAlert error={report.error} />;
  if (!report.data.length) return <Empty>Nenhuma venda no período.</Empty>;
  return (
    <div className="max-w-3xl space-y-2">
      <Table head={['Vendedor(a)', 'Vendas', 'Líquido', 'Ticket médio']} num={[1, 2, 3]}>
        {report.data.map((r) => (
          <tr key={r.salesperson ?? 0}>
            <td className={r.salesperson ? 'font-medium' : 'text-stone-500'}>{r.name}</td>
            <td className="text-right">{r.sales}</td>
            <td className="text-right">{brl(r.net)}</td>
            <td className="text-right">{brl(r.average_ticket)}</td>
          </tr>
        ))}
      </Table>
      <p className="text-xs text-stone-500">Devoluções descontam de quem fez a venda original.</p>
    </div>
  );
}

const CLASS_TONE = { A: 'green', B: 'amber', C: 'neutral' } as const;

function Abc({ filters }: { filters: Filters }) {
  const report = useReport<
    { product: number; reference: string; name: string; units: number; revenue: string; share: string; cumulative_share: string; class: 'A' | 'B' | 'C' }[]
  >('abc', period(filters));
  if (report.isPending) return <Loading />;
  if (report.error) return <ErrorAlert error={report.error} />;
  if (!report.data.length) return <Empty>Nenhuma venda no período.</Empty>;
  const count = (k: string) => report.data.filter((r) => r.class === k).length;
  return (
    <div className="space-y-3">
      <p className="text-sm text-stone-600">
        Classe A: os {count('A')} produtos que fazem 80% da receita. B: os {count('B')} seguintes até 95%. C: os {count('C')} restantes.
      </p>
      <Table head={['', 'Referência', 'Produto', 'Peças', 'Receita líquida', 'Participação', 'Acumulado']} num={[3, 4, 5, 6]}>
        {report.data.map((r) => (
          <tr key={r.product}>
            <td>
              <Badge tone={CLASS_TONE[r.class]}>{r.class}</Badge>
            </td>
            <td className="font-mono text-xs">{r.reference}</td>
            <td>{r.name}</td>
            <td className="text-right">{r.units}</td>
            <td className="text-right">{brl(r.revenue)}</td>
            <td className="text-right">{percent(r.share)}</td>
            <td className="text-right">{percent(r.cumulative_share)}</td>
          </tr>
        ))}
      </Table>
    </div>
  );
}

/** Which sizes and colors of a product actually sell: what to buy more (and less) of next time. */
function SizeColor({ filters }: { filters: Filters }) {
  const [product, setProduct] = useState<Lookup['product'] | null>(null);
  const [picking, setPicking] = useState(false);
  const report = useQuery({
    queryKey: ['report', 'size-color', product?.id, filters],
    queryFn: () =>
      api.get<{ sizes: string[]; rows: { color: string; units: number[] }[]; by_size: number[]; total: number }>(
        `/reports/size-color${qs({ ...period(filters), product: product?.id })}`,
      ),
    enabled: !!product,
  });
  const max = Math.max(1, ...(report.data?.rows.flatMap((r) => r.units) ?? [1]));
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Button variant="secondary" onClick={() => setPicking(true)}>
          {product ? 'Trocar produto' : 'Escolher produto'}
        </Button>
        {product && (
          <span className="text-sm text-stone-700">
            {product.name} <span className="text-stone-500">· {product.reference}</span>
          </span>
        )}
      </div>
      {!product ? (
        <Empty>Escolha um produto para ver a grade que vende.</Empty>
      ) : report.isPending ? (
        <Loading />
      ) : report.error ? (
        <ErrorAlert error={report.error} />
      ) : (
        <Card className="w-fit">
          <table className="text-sm">
            <thead>
              <tr>
                <th />
                {report.data.sizes.map((s) => (
                  <th key={s} className="px-2 py-1 text-center font-medium text-stone-600">
                    {s}
                  </th>
                ))}
                <th className="px-2 text-right font-medium text-stone-600">Total</th>
              </tr>
            </thead>
            <tbody>
              {report.data.rows.map((row) => (
                <tr key={row.color}>
                  <th className="py-1 pr-3 text-left font-medium text-stone-700">{row.color}</th>
                  {row.units.map((u, i) => (
                    <td key={i} className="p-0.5">
                      {/* One hue, light to dark with the units sold; the number is always printed. */}
                      <div
                        className="flex h-10 w-14 items-center justify-center rounded-md tabular-nums"
                        style={{
                          background: u > 0 ? `color-mix(in oklab, var(--color-brand-600) ${12 + (u / max) * 70}%, white)` : '#f5f5f4',
                          color: u / max > 0.55 ? 'white' : '#292524',
                        }}
                        title={`${row.color} ${report.data.sizes[i]}: ${u} peça(s)`}
                      >
                        {u}
                      </div>
                    </td>
                  ))}
                  <td className="px-2 text-right font-medium">{row.units.reduce((a, b) => a + b, 0)}</td>
                </tr>
              ))}
              <tr>
                <th className="pt-2 pr-3 text-left font-medium text-stone-700">Total</th>
                {report.data.by_size.map((u, i) => (
                  <td key={i} className="pt-2 text-center font-medium">
                    {u}
                  </td>
                ))}
                <td className="px-2 pt-2 text-right font-semibold">{report.data.total}</td>
              </tr>
            </tbody>
          </table>
        </Card>
      )}
      {picking && (
        <ProductPicker
          onClose={() => setPicking(false)}
          onPick={(item) => {
            setProduct(item.product);
            setPicking(false);
          }}
        />
      )}
    </div>
  );
}

function Valuation({ location }: { location: string }) {
  const [at, setAt] = useState('');
  const report = useReport<{
    at: string;
    total: string;
    by_location: { location: string; value: string }[];
    by_category: { category: string; value: string }[];
    products: { product: number; reference: string; name: string; quantity: number; value: string }[];
  }>('valuation', { at: at || undefined, location: location || undefined });
  return (
    <div className="space-y-4">
      <Field label="Na data" hint="Vazio: agora. Uma data passada mostra o estoque no fim daquele dia.">
        {(id) => <Input id={id} type="date" className="w-44" max={today()} value={at} onChange={(e) => setAt(e.target.value)} />}
      </Field>
      {report.isPending ? (
        <Loading />
      ) : report.error ? (
        <ErrorAlert error={report.error} />
      ) : (
        <>
          <div className="grid gap-3 md:grid-cols-3">
            <Stat label="Estoque a custo" value={brl(report.data.total)} hint="Soma dos locais = total do razão" />
            {(
              [
                ['Por local', report.data.by_location.map((l) => [l.location === 'TRANSITO' ? 'Em trânsito' : l.location, l.value])],
                ['Por categoria', report.data.by_category.map((c) => [c.category, c.value])],
              ] as const
            ).map(([title, rows]) => (
              <Card key={title}>
                <h3 className="mb-2 text-xs font-medium text-stone-500">{title}</h3>
                <div className="space-y-1 text-sm">
                  {rows.map(([name, value]) => (
                    <p key={name} className="flex justify-between gap-4">
                      <span className="text-stone-600">{name}</span>
                      <span className="tabular-nums">{brl(value)}</span>
                    </p>
                  ))}
                </div>
              </Card>
            ))}
          </div>
          <Table head={['Referência', 'Produto', 'Peças', 'Valor a custo']} num={[2, 3]}>
            {report.data.products.map((p) => (
              <tr key={p.product}>
                <td className="font-mono text-xs">{p.reference}</td>
                <td>{p.name}</td>
                <td className="text-right">{p.quantity}</td>
                <td className="text-right">{brl(p.value)}</td>
              </tr>
            ))}
          </Table>
        </>
      )}
    </div>
  );
}

function Turnover({ filters }: { filters: Filters }) {
  const report = useReport<
    {
      product: number;
      reference: string;
      name: string;
      units_sold: number;
      in_stock: number;
      coverage_days: number | null;
      cogs: string;
      average_stock_value: string;
      turnover: string | null;
    }[]
  >('turnover', period(filters));
  if (report.isPending) return <Loading />;
  if (report.error) return <ErrorAlert error={report.error} />;
  if (!report.data.length) return <Empty>Nada vendido nem em estoque.</Empty>;
  return (
    <div className="space-y-2">
      <Table head={['Referência', 'Produto', 'Vendidas', 'Em estoque', 'Cobertura', 'CMV', 'Estoque médio', 'Giro']} num={[2, 3, 4, 5, 6, 7]}>
        {report.data.map((r) => (
          <tr key={r.product}>
            <td className="font-mono text-xs">{r.reference}</td>
            <td>{r.name}</td>
            <td className="text-right">{r.units_sold}</td>
            <td className="text-right">{r.in_stock}</td>
            <td className="text-right">
              {r.coverage_days === null ? (
                <span className="text-stone-400">sem venda</span>
              ) : (
                <>
                  {r.coverage_days < 7 && <Badge tone="red">acabando</Badge>} {r.coverage_days} dias
                </>
              )}
            </td>
            <td className="text-right">{brl(r.cogs)}</td>
            <td className="text-right">{brl(r.average_stock_value)}</td>
            <td className="text-right">{r.turnover?.replace('.', ',') ?? '—'}</td>
          </tr>
        ))}
      </Table>
      <p className="text-xs text-stone-500">
        Cobertura: quantos dias o estoque de hoje dura no ritmo de venda do período. Giro: CMV ÷ estoque médio a custo no período.
      </p>
    </div>
  );
}

function Stale({ location }: { location: string }) {
  const [days, setDays] = useState('30');
  const report = useReport<
    {
      product: number;
      reference: string;
      name: string;
      collection: string | null;
      in_stock: number;
      stock_value: string;
      last_sale: string | null;
      last_receipt: string | null;
    }[]
  >('stale', { days, location: location || undefined });
  return (
    <div className="space-y-3">
      <Field label="Sem venda há (dias)">
        {(id) => <Input id={id} type="number" min={1} max={365} className="w-28" value={days} onChange={(e) => setDays(e.target.value)} />}
      </Field>
      {report.isPending ? (
        <Loading />
      ) : report.error ? (
        <ErrorAlert error={report.error} />
      ) : !report.data.length ? (
        <Alert tone="success">Tudo o que está em estoque vendeu nesse período.</Alert>
      ) : (
        <>
          <Table head={['Referência', 'Produto', 'Coleção', 'Em estoque', 'Valor a custo', 'Última venda', 'Último recebimento']} num={[3, 4]}>
            {report.data.map((r) => (
              <tr key={r.product}>
                <td className="font-mono text-xs">{r.reference}</td>
                <td>{r.name}</td>
                <td>{r.collection ?? '—'}</td>
                <td className="text-right">{r.in_stock}</td>
                <td className="text-right">{brl(r.stock_value)}</td>
                <td>{r.last_sale ? dayLabel(r.last_sale.slice(0, 10)) : 'nunca'}</td>
                <td>{r.last_receipt ? dayLabel(r.last_receipt.slice(0, 10)) : '—'}</td>
              </tr>
            ))}
          </Table>
          <p className="text-xs text-stone-500">Candidatos a remarcação ou a transferência para a loja onde ainda vendem.</p>
        </>
      )}
    </div>
  );
}
