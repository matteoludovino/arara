import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useLocation, useNavigate } from 'react-router';
import { Alert, Button, Field, formData, Input } from '../components/ui';
import { api } from '../lib/api';
import type { Me } from '../lib/types';

/** The demo deployment (VITE_DEMO_MODE=true) offers its shared accounts; they mirror demo/seed.py. */
const DEMO = import.meta.env.VITE_DEMO_MODE === 'true';
const DEMO_PASSWORD = 'arara-demo-2026';
const DEMO_ACCOUNTS = [
  { email: 'marta@arara.test', name: 'Marta', role: 'Proprietária', sees: 'as duas lojas e o depósito, custos e margem' },
  { email: 'rafael@arara.test', name: 'Rafael', role: 'Gerente', sees: 'Loja Centro e depósito; aprova descontos e ajustes' },
  { email: 'bia@arara.test', name: 'Bia', role: 'Caixa', sees: 'a frente de caixa da Loja Centro, sem custos' },
  { email: 'joao@arara.test', name: 'João', role: 'Estoquista', sees: 'recebimento, transferências e inventário' },
];

function DemoAccounts({ busy, onPick }: { busy: boolean; onPick: (email: string) => void }) {
  return (
    <div className="mt-6 border-t border-stone-200 pt-5">
      <p className="text-sm font-medium text-stone-800">Demonstração: entre com um clique</p>
      <p className="mt-0.5 text-xs text-stone-500">
        Loja fictícia, que volta ao estado inicial toda madrugada. Para aprovar um desconto, use o gerente: rafael@arara.test,
        senha {DEMO_PASSWORD}.
      </p>
      <div className="mt-3 grid gap-2">
        {DEMO_ACCOUNTS.map((a) => (
          <button
            key={a.email}
            type="button"
            disabled={busy}
            onClick={() => onPick(a.email)}
            className="rounded-lg border border-stone-200 px-3 py-2 text-left text-sm hover:border-brand-500 hover:bg-brand-50 disabled:opacity-50"
          >
            <span className="font-medium text-stone-900">{a.name}</span> <span className="text-stone-500">· {a.role}</span>
            <span className="block text-xs text-stone-500">Vê {a.sees}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

export function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const client = useQueryClient();
  const login = useMutation({
    mutationFn: (body: Record<string, string>) => api.post<Me>('/auth/login', body),
    onSuccess: (me) => {
      // The answer is who signed in: no second request, and no stale "signed out" in the cache.
      client.setQueryData(['me'], me);
      navigate((location.state as { from?: string } | null)?.from ?? '/', { replace: true });
    },
  });
  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <p className="text-2xl font-bold tracking-tight text-brand-700">Arara</p>
          <h1 className="mt-4 text-xl font-semibold text-stone-900">Entrar</h1>
          <p className="mt-1 text-sm text-stone-500">Estoque, vendas e caixa da sua loja</p>
        </div>
        <div className="rounded-2xl border border-stone-200 bg-white p-6 shadow-sm">
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              login.mutate(formData(e.currentTarget));
            }}
          >
            <Field label="E-mail">{(id) => <Input id={id} name="email" type="email" autoComplete="email" required />}</Field>
            <Field label="Senha">
              {(id) => <Input id={id} name="password" type="password" autoComplete="current-password" required />}
            </Field>
            {login.error && <Alert>{login.error.message}</Alert>}
            <Button type="submit" className="w-full" busy={login.isPending}>
              Entrar
            </Button>
          </form>
          {DEMO && <DemoAccounts busy={login.isPending} onPick={(email) => login.mutate({ email, password: DEMO_PASSWORD })} />}
        </div>
      </div>
    </main>
  );
}
