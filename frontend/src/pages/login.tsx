import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useLocation, useNavigate } from 'react-router';
import { Alert, Button, Field, formData, Input } from '../components/ui';
import { api } from '../lib/api';
import type { Me } from '../lib/types';

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
        </div>
      </div>
    </main>
  );
}
