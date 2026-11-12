import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router';
import { ApprovalDialog } from '../components/ApprovalDialog';
import { ProductPicker } from '../components/ProductPicker';
import { Alert, Button, Card, ErrorAlert, Field, formData, Input, Loading, PageHeader, Select } from '../components/ui';
import { api, ApiError, type Page } from '../lib/api';
import { time } from '../lib/format';
import { brl, brlCents, fromCents, toCents } from '../lib/money';
import { useSession } from '../lib/session';
import type { CashSession, Lookup, Register, Sale } from '../lib/types';
import { addToCart, type CartLine, discountCents, lineCents, parseScan, pieces, setQuantity, subtotalCents } from './cart';
import { type PaymentInput, PaymentDialog } from './PaymentDialog';
import { CashMovementDialog, ClosedTillDialog, CloseTillDialog, ReceiptDialog } from './TillDialogs';

function useTill() {
  return useQuery({
    queryKey: ['till'],
    queryFn: async (): Promise<CashSession | null> => {
      try {
        return await api.get<CashSession>('/pos/sessions/current');
      } catch (error) {
        if (error instanceof ApiError && error.code === 'session_not_open') return null;
        throw error;
      }
    },
  });
}

export function PosPage() {
  const till = useTill();
  // Kept here: closing the till unmounts the selling screen, and the result must still show.
  const [closed, setClosed] = useState<CashSession | null>(null);
  if (till.isPending) return <Loading />;
  if (till.error) return <ErrorAlert error={till.error} />;
  return (
    <>
      {till.data ? <Till session={till.data} onClosed={setClosed} /> : <OpenTill />}
      {closed && <ClosedTillDialog closed={closed} onClose={() => setClosed(null)} />}
    </>
  );
}

function OpenTill() {
  const { location } = useSession();
  const client = useQueryClient();
  const registers = useQuery({
    queryKey: ['registers'],
    queryFn: () => api.get<Page<Register>>('/pos/registers?limit=200'),
  });
  const open = useMutation({
    mutationFn: (v: Record<string, string>) =>
      api.post<CashSession>('/pos/sessions', { register: Number(v.register), opening_float: fromCents(toCents(v.opening_float)) }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['till'] }),
  });
  if (!location || location.kind !== 'store') {
    return <Alert tone="info">Escolha uma loja no menu para abrir o caixa.</Alert>;
  }
  const here = registers.data?.results.filter((r) => r.location === location.id && r.is_active) ?? [];
  const free = here.filter((r) => !r.open_session);
  return (
    <div className="mx-auto max-w-md">
      <PageHeader title="Abrir caixa" description={location.name} />
      <Card>
        {registers.isPending ? (
          <Loading />
        ) : here.length === 0 ? (
          <Alert tone="info">Esta loja não tem caixa cadastrado.</Alert>
        ) : (
          <form
            key={free.map((r) => r.id).join()} // a till freed meanwhile becomes the default
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              open.mutate(formData(e.currentTarget));
            }}
          >
            <Field label="Caixa">
              {(id) => (
                <Select id={id} name="register" defaultValue={free[0]?.id} required>
                  {here.map((r) => (
                    <option key={r.id} value={r.id} disabled={!!r.open_session}>
                      {r.name}
                      {r.open_session ? ` (aberto por ${r.open_session.opened_by})` : ''}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label="Troco inicial (R$)" hint="O dinheiro que já está na gaveta.">
              {(id) => <Input id={id} name="opening_float" inputMode="decimal" defaultValue="100,00" required />}
            </Field>
            <ErrorAlert error={open.error} />
            <Button type="submit" className="w-full" busy={open.isPending} disabled={free.length === 0}>
              Abrir caixa
            </Button>
          </form>
        )}
      </Card>
    </div>
  );
}

/** The cart survives a reload of the tab (an F5 by mistake), for this till session only. */
function useSavedCart(sessionId: number) {
  const key = `arara.cart.${sessionId}`;
  const [lines, setLines] = useState<CartLine[]>(() => {
    try {
      return JSON.parse(sessionStorage.getItem(key) ?? '[]') as CartLine[];
    } catch {
      return [];
    }
  });
  useEffect(() => {
    try {
      sessionStorage.setItem(key, JSON.stringify(lines));
    } catch {
      // Storage unavailable: the cart just isn't kept across reloads.
    }
  }, [key, lines]);
  return [lines, setLines] as const;
}

type Overlay = 'search' | 'pay' | 'withdrawal' | 'supply' | 'close' | null;

function Till({ session, onClosed }: { session: CashSession; onClosed: (closed: CashSession) => void }) {
  const client = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [lines, setLines] = useSavedCart(session.id);
  const [discount, setDiscount] = useState('');
  const [salesperson, setSalesperson] = useState('');
  const [overlay, setOverlay] = useState<Overlay>(null);
  const [approval, setApproval] = useState<{ percent: string; payments: PaymentInput[] } | null>(null);
  const [receipt, setReceipt] = useState<Sale | null>(null);
  const [scanError, setScanError] = useState<string | null>(null);
  const scanRef = useRef<HTMLInputElement>(null);
  // One id per sale being rung up: a retry after a dropped connection can't charge twice.
  const requestId = useRef(crypto.randomUUID());
  // A store credit just issued by an exchange (see Vendas e trocas) pays first.
  const credit = params.get('vale') ?? undefined;

  const salespeople = useQuery({
    queryKey: ['salespeople', session.location],
    queryFn: () => api.get<{ id: number; name: string }[]>(`/pos/salespeople?location=${session.location}`),
  });

  const subtotal = subtotalCents(lines);
  const off = discountCents(discount, subtotal);
  const discountInvalid = Number.isNaN(off) || off < 0 || off > subtotal;
  const total = subtotal - (discountInvalid ? 0 : off);

  const focusScan = () => setTimeout(() => scanRef.current?.focus(), 0);
  const closeOverlay = () => {
    setOverlay(null);
    focusScan();
  };

  const sell = useMutation({
    mutationFn: ({ payments, approvalId }: { payments: PaymentInput[]; approvalId?: number }) =>
      api.post<Sale>('/pos/sales', {
        client_request_id: requestId.current,
        items: lines.map((l) => ({ variant: l.variant, quantity: l.quantity })),
        payments,
        discount: fromCents(off),
        salesperson: salesperson ? Number(salesperson) : null,
        approval: approvalId ?? null,
      }),
    onSuccess: (sale) => {
      requestId.current = crypto.randomUUID();
      setReceipt(sale);
      setOverlay(null);
      setApproval(null);
      setLines([]);
      setDiscount('');
      setSalesperson('');
      if (credit) setParams({}, { replace: true });
    },
    onError: (error, variables) => {
      if (error instanceof ApiError && error.code === 'discount_needs_approval') {
        setApproval({ percent: String(error.data.percent ?? ''), payments: variables.payments });
      }
    },
  });

  const scan = async (text: string) => {
    const parsed = parseScan(text);
    if (!parsed) return;
    setScanError(null);
    try {
      const item = await api.get<Lookup>(`/catalog/lookup?code=${encodeURIComponent(parsed.code)}`);
      add(item, parsed.quantity);
    } catch (error) {
      setScanError(error instanceof Error ? error.message : 'Código não encontrado.');
    }
  };
  const add = (item: Lookup, quantity = 1) => {
    if (!item.is_active) return setScanError(`${item.sku} está inativo.`);
    if (item.current_price === null) return setScanError(`${item.sku} está sem preço.`);
    setScanError(null);
    setLines((ls) => addToCart(ls, item, quantity));
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (overlay || receipt) return;
      if (e.key === 'F2') {
        e.preventDefault();
        setOverlay('search');
      }
      if (e.key === 'F8' && lines.length && !discountInvalid) {
        e.preventDefault();
        setOverlay('pay');
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [overlay, receipt, lines.length, discountInvalid]);

  return (
    <div>
      <PageHeader
        title="Frente de caixa"
        description={`${session.register_name} · aberto por ${session.opened_by} às ${time(session.opened_at)} · ${session.summary?.sales ?? 0} venda(s) no turno`}
        actions={
          <>
            <Button variant="secondary" onClick={() => setOverlay('withdrawal')}>
              Sangria
            </Button>
            <Button variant="secondary" onClick={() => setOverlay('supply')}>
              Suprimento
            </Button>
            <Button variant="danger" onClick={() => setOverlay('close')} disabled={lines.length > 0}>
              Fechar caixa
            </Button>
          </>
        }
      />
      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <div className="space-y-3">
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              const input = scanRef.current!;
              void scan(input.value);
              input.value = '';
            }}
          >
            <Input
              ref={scanRef}
              autoFocus
              aria-label="Código de barras ou SKU"
              placeholder="Leia o código de barras ou digite o SKU (3*código para três peças)"
              className="text-base"
              autoComplete="off"
            />
            <Button variant="secondary" onClick={() => setOverlay('search')} className="whitespace-nowrap">
              Buscar (F2)
            </Button>
          </form>
          {scanError && <Alert>{scanError}</Alert>}
          {credit && <Alert tone="info">Vale-troca {credit} será usado no pagamento.</Alert>}
          <Card className="p-0">
            {lines.length === 0 ? (
              <p className="py-16 text-center text-sm text-stone-500">Leia uma peça para começar.</p>
            ) : (
              <ul className="divide-y divide-stone-100">
                {lines.map((line) => (
                  <li key={line.variant} className="flex items-center gap-3 px-4 py-2.5">
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium text-stone-900">{line.name}</p>
                      <p className="text-xs text-stone-500">
                        {line.color} · {line.size} · {line.sku} · {brl(line.unitPrice)}
                      </p>
                    </div>
                    <div className="flex items-center gap-1">
                      <Button variant="ghost" className="px-2" aria-label="Menos uma" onClick={() => setLines((ls) => setQuantity(ls, line.variant, line.quantity - 1))}>
                        −
                      </Button>
                      <span className="w-8 text-center tabular-nums">{line.quantity}</span>
                      <Button variant="ghost" className="px-2" aria-label="Mais uma" onClick={() => setLines((ls) => setQuantity(ls, line.variant, line.quantity + 1))}>
                        +
                      </Button>
                    </div>
                    <span className="w-24 text-right font-medium tabular-nums">{brlCents(lineCents(line))}</span>
                    <Button variant="ghost" className="px-2 text-stone-400" aria-label="Tirar da venda" onClick={() => setLines((ls) => setQuantity(ls, line.variant, 0))}>
                      ✕
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
        <Card className="h-fit space-y-4">
          <Field label="Vendedor(a)">
            {(id) => (
              <Select id={id} value={salesperson} onChange={(e) => setSalesperson(e.target.value)}>
                <option value="">Sem vendedor</option>
                {salespeople.data?.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Desconto" hint="Em reais (15,00) ou em porcentagem (10%).">
            {(id) => <Input id={id} value={discount} onChange={(e) => setDiscount(e.target.value)} inputMode="decimal" />}
          </Field>
          {discountInvalid && <Alert tone="warning">Desconto inválido.</Alert>}
          <dl className="space-y-1 text-sm">
            <div className="flex justify-between">
              <dt className="text-stone-500">{pieces(lines)} peça(s)</dt>
              <dd>{brlCents(subtotal)}</dd>
            </div>
            {off > 0 && !discountInvalid && (
              <div className="flex justify-between">
                <dt className="text-stone-500">Desconto</dt>
                <dd>− {brlCents(off)}</dd>
              </div>
            )}
            <div className="flex items-baseline justify-between border-t border-stone-200 pt-2">
              <dt className="font-medium">Total</dt>
              <dd className="text-2xl font-semibold text-stone-900">{brlCents(total)}</dd>
            </div>
          </dl>
          <Button className="w-full py-3 text-base" disabled={!lines.length || discountInvalid} onClick={() => setOverlay('pay')}>
            Pagamento (F8)
          </Button>
          {lines.length > 0 && (
            <Button variant="ghost" className="w-full" onClick={() => (setLines([]), setDiscount(''), focusScan())}>
              Limpar venda
            </Button>
          )}
        </Card>
      </div>

      {overlay === 'search' && (
        <ProductPicker locationId={session.location} onClose={closeOverlay} onPick={(item) => (add(item), closeOverlay())} />
      )}
      {overlay === 'pay' && !approval && (
        <PaymentDialog
          total={total}
          busy={sell.isPending}
          error={sell.error instanceof ApiError && sell.error.code === 'discount_needs_approval' ? null : sell.error}
          initialCredit={credit}
          onConfirm={(payments) => sell.mutate({ payments })}
          onClose={() => (sell.reset(), closeOverlay())}
        />
      )}
      {approval && (
        <ApprovalDialog
          action="discount"
          location={session.location}
          limit={approval.percent}
          detail={`Desconto de ${approval.percent.replace('.', ',')}% nesta venda.`}
          onClose={() => setApproval(null)}
          onApproved={(granted) => sell.mutate({ payments: approval.payments, approvalId: granted.id })}
        />
      )}
      {(overlay === 'withdrawal' || overlay === 'supply') && <CashMovementDialog session={session} kind={overlay} onClose={closeOverlay} />}
      {overlay === 'close' && (
        <CloseTillDialog
          session={session}
          onClose={closeOverlay}
          onClosed={(closed) => {
            onClosed(closed);
            void client.invalidateQueries({ queryKey: ['till'] });
          }}
        />
      )}
      {receipt && <ReceiptDialog sale={receipt} onClose={() => (setReceipt(null), focusScan())} />}
    </div>
  );
}
