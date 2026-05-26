"use client";
import { useState } from 'react';
import { Loader2, AlertTriangle } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Checkbox } from '@/components/ui/checkbox';
import { paiseToRupees } from '@/lib/format';
import { apiFetch } from '@/lib/api';
import { toast } from 'sonner';

type Kind = 'wallet' | 'bottle';

export function AdjustmentModal({
  open,
  onOpenChange,
  kind,
  customerId,
  currentBalance,
  onDone,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  kind: Kind;
  customerId: string;
  currentBalance: number;
  onDone: () => void;
}) {
  const [amount, setAmount] = useState<string>('');
  const [reason, setReason] = useState('');
  const [force, setForce] = useState(false);
  const [confirmText, setConfirmText] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const numAmount = parseInt(amount, 10);
  const amountValid = !Number.isNaN(numAmount) && numAmount !== 0;
  const reasonValid = reason.trim().length >= 10;
  const newBalance = amountValid ? currentBalance + numAmount : currentBalance;
  const wouldGoNegative = amountValid && newBalance < 0;
  const forceUnlocked = wouldGoNegative ? force && confirmText === 'I UNDERSTAND' : true;
  const canSubmit = amountValid && reasonValid && forceUnlocked && !submitting;

  const unitLabel = kind === 'wallet' ? 'paise (₹ × 100)' : 'bottles';
  const fmt = (n: number) => (kind === 'wallet' ? paiseToRupees(n) : `${n} bottle${Math.abs(n) === 1 ? '' : 's'}`);

  function reset() {
    setAmount('');
    setReason('');
    setForce(false);
    setConfirmText('');
    setError(null);
    setSubmitting(false);
  }

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      const body =
        kind === 'wallet'
          ? { amount_paise: numAmount, reason: reason.trim(), force }
          : { change: numAmount, reason: reason.trim(), force };
      await apiFetch(`/admin/customers/${customerId}/${kind}-adjustment`, {
        method: 'POST',
        body,
      });
      toast.success(`${kind === 'wallet' ? 'Wallet' : 'Bottle'} adjusted`, {
        description: `${fmt(currentBalance)} → ${fmt(newBalance)}`,
      });
      reset();
      onOpenChange(false);
      onDone();
    } catch (e: any) {
      setError(e.message || 'Adjustment failed');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) reset(); onOpenChange(v); }}>
      <DialogContent data-testid={`adjust-${kind}-modal`} className="max-w-md">
        <DialogHeader>
          <DialogTitle className="font-display">
            Adjust {kind === 'wallet' ? 'Wallet Balance' : 'Bottle Ledger'}
          </DialogTitle>
          <DialogDescription>
            This change will be permanent and recorded in the audit log.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Current balance */}
          <div className="p-3 rounded-lg bg-muted">
            <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Current balance</div>
            <div className="font-display text-2xl font-bold tabular-nums mt-1" data-testid="adjust-current-balance">
              {fmt(currentBalance)}
            </div>
          </div>

          {/* Amount */}
          <div>
            <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Change ({unitLabel})
            </label>
            <Input
              data-testid="adjust-amount-input"
              type="number"
              inputMode="numeric"
              placeholder={kind === 'wallet' ? 'e.g. 10000 (credit) or -5000 (debit)' : 'e.g. +2 or -1'}
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="mt-1"
            />
            <div className="text-[11px] text-muted-foreground mt-1">
              Positive = credit / owe more · Negative = debit / return
            </div>
          </div>

          {/* Reason */}
          <div>
            <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Reason <span className="text-accent">*</span>
            </label>
            <Textarea
              data-testid="adjust-reason-input"
              placeholder="Detailed business reason — at least 10 characters"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              className="mt-1"
              maxLength={500}
            />
            <div className="text-[11px] text-muted-foreground mt-1 flex justify-between">
              <span className={reason.length > 0 && reason.length < 10 ? 'text-accent' : ''}>
                {reason.trim().length} / 10 min
              </span>
              <span>{reason.length} / 500</span>
            </div>
          </div>

          {/* Preview */}
          {amountValid && (
            <div
              data-testid="adjust-preview"
              className={`p-3 rounded-lg border text-sm ${
                wouldGoNegative ? 'bg-accent/10 border-accent/30' : 'bg-secondary/10 border-secondary/30'
              }`}
            >
              <div className="text-[10px] uppercase tracking-widest font-semibold text-muted-foreground">
                Resulting balance
              </div>
              <div className="font-display text-xl font-bold tabular-nums mt-1" data-testid="adjust-preview-balance">
                {fmt(newBalance)}
              </div>
            </div>
          )}

          {/* Negative warning */}
          {wouldGoNegative && (
            <div className="p-3 rounded-lg bg-accent/10 border border-accent/30 text-sm space-y-2">
              <div className="flex items-start gap-2">
                <AlertTriangle className="w-4 h-4 text-accent mt-0.5 flex-shrink-0" />
                <div>
                  <div className="font-semibold text-accent">This will make the balance negative.</div>
                  <div className="text-muted-foreground mt-1 text-xs">
                    {kind === 'wallet'
                      ? 'Customer will owe money. Only allowed for reconciliation / refund edge cases.'
                      : 'Customer has returned more bottles than owed (promo credit, etc.).'}
                  </div>
                </div>
              </div>
              <label className="flex items-center gap-2 cursor-pointer">
                <Checkbox
                  data-testid="adjust-force-checkbox"
                  checked={force}
                  onCheckedChange={(v) => {
                    setForce(!!v);
                    if (!v) setConfirmText('');
                  }}
                />
                <span className="text-sm">Apply anyway (force)</span>
              </label>
              {force && (
                <div>
                  <label className="text-[10px] uppercase tracking-widest font-semibold text-muted-foreground">
                    Type <span className="font-mono text-foreground">I UNDERSTAND</span> to unlock
                  </label>
                  <Input
                    data-testid="adjust-confirm-text"
                    value={confirmText}
                    onChange={(e) => setConfirmText(e.target.value)}
                    className="mt-1 font-mono"
                    placeholder="I UNDERSTAND"
                  />
                </div>
              )}
            </div>
          )}

          {error && (
            <div data-testid="adjust-error" className="p-3 rounded-lg bg-accent/10 border border-accent/30 text-sm text-accent">
              {error}
            </div>
          )}
        </div>

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting} data-testid="adjust-cancel">
            Cancel
          </Button>
          <Button onClick={submit} disabled={!canSubmit} data-testid="adjust-submit">
            {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Apply adjustment'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
