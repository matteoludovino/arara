import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Badge, Button, Card, Dialog, ErrorAlert, Field, formData, Input, Loading, PageHeader, Select, Table } from '../components/ui';
import { api, type Page } from '../lib/api';
import { useSession } from '../lib/session';
import type { Location, Register, Role, User } from '../lib/types';

const ROLES: { value: Role; label: string; does: string }[] = [
  { value: 'owner', label: 'Proprietário(a)', does: 'tudo, em todas as lojas' },
  { value: 'manager', label: 'Gerente', does: 'a(s) própria(s) loja(s): estoque, compras, aprovações e relatórios' },
  { value: 'cashier', label: 'Caixa', does: 'vende e opera o próprio caixa; não vê custo' },
  { value: 'stockist', label: 'Estoquista', does: 'recebe, transfere e conta; não vende' },
];

export function TeamPage() {
  const { can } = useSession();
  return (
    <div className="space-y-8">
      <PageHeader title="Equipe e lojas" description="Cada pessoa vê e faz o que o papel permite, só nas lojas em que trabalha." />
      {can('users.manage') && <People />}
      {can('locations.manage') && <Places />}
    </div>
  );
}

function useLocations() {
  return useQuery({ queryKey: ['locations'], queryFn: () => api.get<Page<Location>>('/locations?limit=100') });
}

function People() {
  const users = useQuery({ queryKey: ['users'], queryFn: () => api.get<Page<User>>('/users?limit=200') });
  const locations = useLocations();
  const [editing, setEditing] = useState<User | 'new' | null>(null);
  const codes = (ids: number[]) =>
    ids.map((id) => locations.data?.results.find((l) => l.id === id)?.code ?? '?').join(', ') || '—';
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-stone-900">Pessoas</h2>
        <Button onClick={() => setEditing('new')}>Nova pessoa</Button>
      </div>
      {users.isPending ? (
        <Loading />
      ) : (
        <Table head={['Nome', 'E-mail', 'Papel', 'Lojas', '', '']}>
          {users.data?.results.map((u) => (
            <tr key={u.id} className={u.is_active ? '' : 'text-stone-400'}>
              <td className="font-medium">{u.name}</td>
              <td>{u.email}</td>
              <td>{u.role_label}</td>
              <td>{u.role === 'owner' ? 'todas' : codes(u.locations)}</td>
              <td>{!u.is_active && <Badge tone="red">inativa</Badge>}</td>
              <td>
                <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => setEditing(u)}>
                  Editar
                </Button>
              </td>
            </tr>
          ))}
        </Table>
      )}
      {editing && <PersonDialog user={editing === 'new' ? null : editing} locations={locations.data?.results ?? []} onClose={() => setEditing(null)} />}
    </section>
  );
}

function PersonDialog({ user, locations, onClose }: { user: User | null; locations: Location[]; onClose: () => void }) {
  const [role, setRole] = useState<Role>(user?.role ?? 'cashier');
  const [places, setPlaces] = useState<number[]>(user?.locations ?? []);
  const [active, setActive] = useState(user?.is_active ?? true);
  const save = useMutation({
    mutationFn: (v: Record<string, string>) => {
      const body = { name: v.name, email: v.email, role, locations: places, is_active: active, ...(v.password && { password: v.password }) };
      return user ? api.patch(`/users/${user.id}`, body) : api.post('/users', body);
    },
    onSuccess: onClose,
  });
  return (
    <Dialog open onClose={onClose} title={user ? user.name : 'Nova pessoa'}>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate(formData(e.currentTarget));
        }}
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Nome">{(id) => <Input id={id} name="name" defaultValue={user?.name} required data-autofocus />}</Field>
          <Field label="E-mail">{(id) => <Input id={id} name="email" type="email" defaultValue={user?.email} required />}</Field>
        </div>
        <Field label="Papel" hint={ROLES.find((r) => r.value === role)?.does}>
          {(id) => (
            <Select id={id} value={role} onChange={(e) => setRole(e.target.value as Role)}>
              {ROLES.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </Select>
          )}
        </Field>
        {role !== 'owner' && (
          <fieldset>
            <legend className="text-sm font-medium text-stone-700">Trabalha em</legend>
            <div className="mt-2 flex flex-wrap gap-3">
              {locations.map((l) => (
                <label key={l.id} className="inline-flex items-center gap-1.5 text-sm">
                  <input
                    type="checkbox"
                    checked={places.includes(l.id)}
                    onChange={(e) => setPlaces((ps) => (e.target.checked ? [...ps, l.id] : ps.filter((x) => x !== l.id)))}
                  />
                  {l.name}
                </label>
              ))}
            </div>
          </fieldset>
        )}
        <Field label={user ? 'Nova senha' : 'Senha inicial'} hint={user ? 'Vazio: mantém a atual.' : 'A pessoa pode trocá-la depois.'}>
          {(id) => <Input id={id} name="password" type="password" autoComplete="new-password" required={!user} />}
        </Field>
        {user && (
          <label className="inline-flex items-center gap-2 text-sm">
            <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
            Ativa (desativar encerra a sessão na hora)
          </label>
        )}
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

function Places() {
  const locations = useLocations();
  const registers = useQuery({ queryKey: ['registers'], queryFn: () => api.get<Page<Register>>('/pos/registers?limit=200') });
  const addPlace = useMutation({ mutationFn: (v: Record<string, string>) => api.post('/locations', v) });
  const addRegister = useMutation({
    mutationFn: (v: Record<string, string>) => api.post('/pos/registers', { location: Number(v.location), name: v.name }),
  });
  const stores = locations.data?.results.filter((l) => l.kind === 'store') ?? [];
  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold text-stone-900">Lojas, depósitos e caixas</h2>
      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <Table head={['Código', 'Nome', 'Tipo', 'CNPJ', 'Caixas']}>
          {locations.data?.results.map((l) => (
            <tr key={l.id}>
              <td className="font-mono text-xs">{l.code}</td>
              <td>{l.name}</td>
              <td>{l.kind === 'store' ? 'Loja' : 'Depósito'}</td>
              <td className="font-mono text-xs">{l.cnpj || '—'}</td>
              <td>
                {registers.data?.results
                  .filter((r) => r.location === l.id)
                  .map((r) => r.name)
                  .join(', ') || '—'}
              </td>
            </tr>
          ))}
        </Table>
        <div className="space-y-4">
          <Card>
            <h3 className="mb-3 font-medium text-stone-900">Novo local</h3>
            <form
              className="space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                const form = e.currentTarget;
                addPlace.mutate(formData(form), { onSuccess: () => form.reset() });
              }}
            >
              <div className="grid grid-cols-[6rem_1fr] gap-2">
                <Input name="code" placeholder="Código" required maxLength={12} aria-label="Código" />
                <Input name="name" placeholder="Nome" required aria-label="Nome" />
              </div>
              <Select name="kind" aria-label="Tipo">
                <option value="store">Loja</option>
                <option value="warehouse">Depósito</option>
              </Select>
              <Input name="cnpj" placeholder="CNPJ (opcional)" aria-label="CNPJ" />
              <ErrorAlert error={addPlace.error} />
              <Button type="submit" variant="secondary" busy={addPlace.isPending}>
                Cadastrar local
              </Button>
            </form>
          </Card>
          <Card>
            <h3 className="mb-3 font-medium text-stone-900">Novo caixa</h3>
            <form
              className="space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                const form = e.currentTarget;
                addRegister.mutate(formData(form), { onSuccess: () => form.reset() });
              }}
            >
              <Select name="location" aria-label="Loja" required>
                {stores.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name}
                  </option>
                ))}
              </Select>
              <Input name="name" placeholder="Ex.: Caixa 3" required aria-label="Nome do caixa" />
              <ErrorAlert error={addRegister.error} />
              <Button type="submit" variant="secondary" busy={addRegister.isPending}>
                Cadastrar caixa
              </Button>
            </form>
          </Card>
        </div>
      </div>
    </section>
  );
}
