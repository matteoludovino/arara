import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { VariantGrid } from '../components/ProductPicker';
import {
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
import { dateTime } from '../lib/format';
import { brl, fromCents, toCents } from '../lib/money';
import { useSession } from '../lib/session';
import type { Collection, Color, Named, Price, Product, ProductListItem, SizeGrid } from '../lib/types';

const all = <T,>(path: string) => api.get<Page<T>>(`${path}?limit=200`).then((p) => p.results);

function useCatalogLists() {
  const categories = useQuery({ queryKey: ['categories'], queryFn: () => all<Named>('/catalog/categories') });
  const brands = useQuery({ queryKey: ['brands'], queryFn: () => all<Named>('/catalog/brands') });
  const collections = useQuery({ queryKey: ['collections'], queryFn: () => all<Collection>('/catalog/collections') });
  const colors = useQuery({ queryKey: ['colors'], queryFn: () => all<Color>('/catalog/colors') });
  const grids = useQuery({ queryKey: ['grids'], queryFn: () => all<SizeGrid>('/catalog/size-grids') });
  return { categories, brands, collections, colors, grids };
}

export function ProductsPage() {
  const { can } = useSession();
  const [tab, setTab] = useState<'products' | 'setup'>('products');
  const [creating, setCreating] = useState(false);
  return (
    <div>
      <PageHeader
        title="Produtos"
        description="Cada produto vira uma grade de SKUs: uma cor em um tamanho, com código de barras próprio."
        actions={can('catalog.manage') && <Button onClick={() => setCreating(true)}>Novo produto</Button>}
      />
      {can('catalog.manage') && (
        <Tabs
          value={tab}
          onChange={setTab}
          options={[
            { value: 'products', label: 'Produtos' },
            { value: 'setup', label: 'Cadastros' },
          ]}
        />
      )}
      {tab === 'products' ? <ProductList /> : <CatalogSetup />}
      {creating && <NewProduct onClose={() => setCreating(false)} />}
    </div>
  );
}

function ProductList() {
  const [q, setQ] = useState('');
  const [category, setCategory] = useState('');
  const { categories } = useCatalogLists();
  const products = useQuery({
    queryKey: ['products', q, category],
    queryFn: () => api.get<Page<ProductListItem>>(`/catalog/products${qs({ q, category, limit: 100 })}`),
  });
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Input className="w-64" placeholder="Buscar por nome ou referência" value={q} onChange={(e) => setQ(e.target.value)} />
        <Select className="w-48" aria-label="Categoria" value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">Todas as categorias</option>
          {categories.data?.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </Select>
      </div>
      {products.isPending ? (
        <Loading />
      ) : products.error ? (
        <ErrorAlert error={products.error} />
      ) : !products.data.results.length ? (
        <Empty>Nenhum produto.</Empty>
      ) : (
        <Table head={['Referência', 'Produto', 'Categoria', 'Marca', 'Coleção', 'SKUs', 'Preço']} num={[5, 6]}>
          {products.data.results.map((p) => (
            <tr key={p.id} className={p.is_active ? '' : 'text-stone-400'}>
              <td className="font-mono text-xs">{p.reference}</td>
              <td>
                <Link to={`/produtos/${p.id}`} className="font-medium text-brand-700 hover:underline">
                  {p.name}
                </Link>
                {!p.is_active && <Badge>inativo</Badge>}
              </td>
              <td>{p.category}</td>
              <td>{p.brand ?? '—'}</td>
              <td>{p.collection ?? '—'}</td>
              <td className="text-right">{p.variant_count}</td>
              <td className="text-right">{brl(p.current_price)}</td>
            </tr>
          ))}
        </Table>
      )}
    </div>
  );
}

function NewProduct({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const lists = useCatalogLists();
  const [colors, setColors] = useState<number[]>([]);
  const create = useMutation({
    mutationFn: (v: Record<string, string>) =>
      api.post<Product>('/catalog/products', {
        reference: v.reference,
        name: v.name,
        category: Number(v.category),
        brand: v.brand ? Number(v.brand) : null,
        collection: v.collection ? Number(v.collection) : null,
        size_grid: Number(v.size_grid),
        ncm: v.ncm,
        colors,
        price: fromCents(toCents(v.price)),
      }),
    onSuccess: (product) => navigate(`/produtos/${product.id}`),
  });
  const grid = (id: string) => lists.grids.data?.find((g) => g.id === Number(id));
  const [gridId, setGridId] = useState('');
  return (
    <Dialog open onClose={onClose} title="Novo produto" wide>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate(formData(e.currentTarget));
        }}
      >
        <div className="grid gap-3 sm:grid-cols-[10rem_1fr]">
          <Field label="Referência">{(id) => <Input id={id} name="reference" required maxLength={20} placeholder="CAM-003" data-autofocus />}</Field>
          <Field label="Nome">{(id) => <Input id={id} name="name" required maxLength={120} />}</Field>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Categoria">
            {(id) => (
              <Select id={id} name="category" required>
                {lists.categories.data?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Marca">
            {(id) => (
              <Select id={id} name="brand">
                <option value="">—</option>
                {lists.brands.data?.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Coleção">
            {(id) => (
              <Select id={id} name="collection">
                <option value="">—</option>
                {lists.collections.data?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Grade de tamanhos" hint={grid(gridId)?.sizes.map((s) => s.label).join(' · ')}>
            {(id) => (
              <Select id={id} name="size_grid" required value={gridId} onChange={(e) => setGridId(e.target.value)}>
                <option value="" disabled>
                  Escolha
                </option>
                {lists.grids.data?.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Preço de venda (R$)">{(id) => <Input id={id} name="price" inputMode="decimal" required />}</Field>
          <Field label="NCM" hint="Opcional por enquanto.">
            {(id) => <Input id={id} name="ncm" inputMode="numeric" maxLength={8} />}
          </Field>
        </div>
        <fieldset>
          <legend className="text-sm font-medium text-stone-700">Cores</legend>
          <div className="mt-2 flex flex-wrap gap-2">
            {lists.colors.data?.map((c) => {
              const on = colors.includes(c.id);
              return (
                <button
                  key={c.id}
                  type="button"
                  aria-pressed={on}
                  onClick={() => setColors((cs) => (on ? cs.filter((x) => x !== c.id) : [...cs, c.id]))}
                  className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm ${on ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-stone-300 text-stone-700'}`}
                >
                  <span className="size-3 rounded-full border border-stone-300" style={{ background: c.hex || '#fff' }} />
                  {c.name}
                </button>
              );
            })}
          </div>
        </fieldset>
        {gridId && colors.length > 0 && (
          <p className="text-sm text-stone-600">
            Serão criados {(grid(gridId)?.sizes.length ?? 0) * colors.length} SKUs, cada um com código de barras interno.
          </p>
        )}
        <ErrorAlert error={create.error} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" disabled={!colors.length} busy={create.isPending}>
            Criar produto
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

export function ProductDetailPage() {
  const { id } = useParams();
  const { can, location } = useSession();
  const [adding, setAdding] = useState(false);
  const product = useQuery({ queryKey: ['product', Number(id)], queryFn: () => api.get<Product>(`/catalog/products/${id}`) });
  if (product.isPending) return <Loading />;
  if (product.error) return <ErrorAlert error={product.error} />;
  const p = product.data;
  return (
    <div className="space-y-6">
      <PageHeader
        title={p.name}
        description={
          <>
            <Link to="/produtos" className="text-brand-700 hover:underline">
              Produtos
            </Link>{' '}
            · {p.reference} · {brl(p.current_price)}
          </>
        }
        actions={can('catalog.manage') && <Button variant="secondary" onClick={() => setAdding(true)}>Adicionar cor</Button>}
      />
      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <h2 className="mb-3 font-medium text-stone-900">Estoque em {location?.name ?? 'todas as lojas'}</h2>
          <VariantGrid product={p} locationId={location?.id} />
        </Card>
        {can('stock.view') && <Prices product={p} />}
      </div>
      <Card className="p-0">
        <Table head={['SKU', 'Cor', 'Tamanho', 'Códigos de barras', 'Preço']} num={[4]}>
          {p.variants.map((v) => (
            <tr key={v.id}>
              <td className="font-mono text-xs">{v.sku}</td>
              <td>{v.color.name}</td>
              <td>{v.size}</td>
              <td className="space-x-2">
                {v.barcodes.map((b) => (
                  <span key={b.code} className="font-mono text-xs" title={b.kind === 'internal' ? 'Interno' : 'Do fornecedor'}>
                    {b.code}
                    {b.kind === 'supplier' && <Badge tone="blue">fornecedor</Badge>}
                  </span>
                ))}
              </td>
              <td className="text-right">{brl(v.current_price)}</td>
            </tr>
          ))}
        </Table>
      </Card>
      {adding && <AddColors product={p} onClose={() => setAdding(false)} />}
    </div>
  );
}

/** Prices are never edited: a change is a new price from a date on, so history stays true. */
function Prices({ product }: { product: Product }) {
  const { can } = useSession();
  const prices = useQuery({
    queryKey: ['prices', product.id],
    queryFn: () => api.get<Price[]>(`/catalog/products/${product.id}/prices`),
  });
  const schedule = useMutation({
    mutationFn: (v: Record<string, string>) =>
      api.post<Price>(`/catalog/products/${product.id}/prices`, {
        amount: fromCents(toCents(v.amount)),
        valid_from: v.valid_from ? new Date(v.valid_from).toISOString() : undefined,
      }),
  });
  const withdraw = useMutation({ mutationFn: (id: number) => api.delete(`/catalog/prices/${id}`) });
  const now = Date.now();
  return (
    <Card>
      <h2 className="mb-3 font-medium text-stone-900">Preços</h2>
      {can('prices.change') && (
        <form
          className="mb-4 flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            schedule.mutate(formData(e.currentTarget));
            e.currentTarget.reset();
          }}
        >
          <Field label="Novo preço (R$)">{(id) => <Input id={id} name="amount" inputMode="decimal" required className="w-32" />}</Field>
          <Field label="A partir de" hint="Vazio: agora.">
            {(id) => <Input id={id} name="valid_from" type="datetime-local" className="w-56" />}
          </Field>
          <Button type="submit" variant="secondary" busy={schedule.isPending}>
            Definir
          </Button>
        </form>
      )}
      <ErrorAlert error={schedule.error ?? withdraw.error} />
      <ul className="divide-y divide-stone-100 text-sm">
        {prices.data?.map((price) => {
          const future = new Date(price.valid_from).getTime() > now;
          return (
            <li key={price.id} className="flex items-center justify-between gap-3 py-1.5">
              <span>
                <span className="font-medium">{brl(price.amount)}</span>
                {price.sku && <span className="text-stone-500"> · só {price.sku}</span>}
                <span className="block text-xs text-stone-500">
                  desde {dateTime(price.valid_from)} · {price.created_by}
                </span>
              </span>
              {future && (
                <span className="flex items-center gap-2">
                  <Badge tone="blue">agendado</Badge>
                  {can('prices.change') && (
                    <Button variant="ghost" className="px-2 text-xs" onClick={() => withdraw.mutate(price.id)}>
                      Retirar
                    </Button>
                  )}
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

function AddColors({ product, onClose }: { product: Product; onClose: () => void }) {
  const { colors } = useCatalogLists();
  const have = new Set(product.variants.map((v) => v.color.id));
  const [picked, setPicked] = useState<number[]>([]);
  const add = useMutation({
    mutationFn: () => api.post<Product>(`/catalog/products/${product.id}/colors`, { colors: picked }),
    onSuccess: onClose,
  });
  return (
    <Dialog open onClose={onClose} title="Adicionar cor">
      <div className="space-y-4">
        <p className="text-sm text-stone-600">A grade completa da cor é criada: um SKU por tamanho.</p>
        <div className="flex flex-wrap gap-2">
          {colors.data
            ?.filter((c) => !have.has(c.id))
            .map((c) => (
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
        <ErrorAlert error={add.error} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            Cancelar
          </Button>
          <Button disabled={!picked.length} busy={add.isPending} onClick={() => add.mutate()}>
            Adicionar
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

/** The lists products are built from: categories, brands, collections, colors and size grids. */
function CatalogSetup() {
  const lists = useCatalogLists();
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      <SimpleList title="Categorias" path="/catalog/categories" items={lists.categories.data?.map((c) => c.name)} />
      <SimpleList title="Marcas" path="/catalog/brands" items={lists.brands.data?.map((c) => c.name)} />
      <SimpleList
        title="Coleções"
        path="/catalog/collections"
        items={lists.collections.data?.map((c) => `${c.name}${c.starts_on ? ` (${c.starts_on.slice(0, 7)})` : ''}`)}
      />
      <SimpleList
        title="Cores"
        path="/catalog/colors"
        items={lists.colors.data?.map((c) => `${c.name} · ${c.code}`)}
        extra={[{ name: 'code', label: 'Sigla (3 letras)', maxLength: 4 }]}
      />
      <SimpleList
        title="Grades de tamanho"
        path="/catalog/size-grids"
        items={lists.grids.data?.map((g) => `${g.name}: ${g.sizes.map((s) => s.label).join(' ')}`)}
        extra={[{ name: 'labels', label: 'Tamanhos, na ordem (ex.: P M G)' }]}
      />
    </div>
  );
}

function SimpleList({
  title,
  path,
  items,
  extra = [],
}: {
  title: string;
  path: string;
  items: string[] | undefined;
  extra?: { name: string; label: string; maxLength?: number }[];
}) {
  const add = useMutation({
    mutationFn: (v: Record<string, string>) =>
      api.post(path, { ...v, ...(v.labels !== undefined && { labels: v.labels.split(/[\s,]+/).filter(Boolean) }) }),
  });
  return (
    <Card>
      <h2 className="mb-2 font-medium text-stone-900">{title}</h2>
      <ul className="mb-3 space-y-0.5 text-sm text-stone-700">{items?.map((i) => <li key={i}>{i}</li>) ?? <Loading />}</ul>
      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault();
          const form = e.currentTarget;
          add.mutate(formData(form), { onSuccess: () => form.reset() });
        }}
      >
        <Input name="name" placeholder="Nome" required aria-label={`Nome (${title})`} />
        {extra.map((f) => (
          <Input key={f.name} name={f.name} placeholder={f.label} aria-label={f.label} required maxLength={f.maxLength} />
        ))}
        <ErrorAlert error={add.error} />
        <Button type="submit" variant="secondary" busy={add.isPending}>
          Adicionar
        </Button>
      </form>
    </Card>
  );
}
