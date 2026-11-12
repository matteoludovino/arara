import { useMutation } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Approval } from '../lib/types';
import { Alert, Button, Dialog, Field, formData, Input } from './ui';

const WHAT: Record<Approval['action'], string> = {
  discount: 'Desconto acima do limite do caixa',
  return_without_receipt: 'Devolução sem cupom',
  stock_adjustment: 'Ajuste de estoque',
};

/**
 * A manager approves on this screen with their own e-mail and password. The approval is
 * single-use, expires in minutes, and is bound to this person, action and store.
 */
export function ApprovalDialog({
  action,
  location,
  limit,
  detail,
  onApproved,
  onClose,
}: {
  action: Approval['action'];
  location: number;
  limit?: string;
  detail?: string;
  onApproved: (approval: Approval) => void;
  onClose: () => void;
}) {
  const grant = useMutation({
    mutationFn: (values: Record<string, string>) =>
      api.post<Approval>('/approvals', { action, location, limit, ...values }),
    onSuccess: onApproved,
  });
  return (
    <Dialog open onClose={onClose} title="Aprovação do gerente">
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          grant.mutate(formData(e.currentTarget));
        }}
      >
        <Alert tone="warning">
          <strong>{WHAT[action]}</strong>
          {detail && <span className="block">{detail}</span>}
        </Alert>
        <Field label="E-mail do gerente">
          {(id) => <Input id={id} name="approver_email" type="email" autoComplete="off" required data-autofocus />}
        </Field>
        <Field label="Senha do gerente">
          {(id) => <Input id={id} name="approver_password" type="password" autoComplete="off" required />}
        </Field>
        <Field label="Motivo">{(id) => <Input id={id} name="reason" required maxLength={200} />}</Field>
        {grant.error && <Alert>{grant.error.message}</Alert>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" busy={grant.isPending}>
            Aprovar
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
