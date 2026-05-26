"use client";
import { useState } from 'react';
import { Loader2, AlertTriangle, Lock } from 'lucide-react';
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
import { Badge } from '@/components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { toast } from 'sonner';
import { apiFetch } from '@/lib/api';
import { paiseToRupees } from '@/lib/format';

type Order = {
  id: string;
  status: string;
  quantity: number;
  delivered_quantity: number | null;
  bottles_returned: number | null;
  unit_price_paise: number;
  product_name: string;
  product_requires_bottle: boolean;
  cutoff_locked_at: string | null;
  customer_name: string | null;
  customer_phone: string;
  customer_bottle_balance: number;
};

export function OverrideModal({
  open,
  onOpenChange,
  order,
  onDone,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  order: Order | null;
  onDone: () => void;
}) {
  const [status, setStatus] = useState<string>('delivered');
  const [qty, setQty] = useState<string>('');
  const [ret, setRet] = useState<string>('0');
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const qtyNum = parseInt(qty, 10);
  const retNum = parseInt(ret, 10);
  const reasonValid = reason.trim().length >= 10;
  const isDelivered = status === 'delivered';
  const needsQty = isDelivered;
  const qtyValid = !needsQty || (!Number.isNaN(qtyNum) && qtyNum >= 1 && !!order && qtyNum <= order.quantity * 2);
  const needsBottles = isDelivered && !!order?.product_requires_bottle;
  const retValid = !needsBottles || (!Number.isNaN(retNum) && retNum >= 0);
  const canSubmit = reasonValid && qtyValid && retValid && !submitting && !!order;

  const bypassedCutoff = !!order?.cutoff_locked_at && new Date(order.cutoff_locked_at).getTime() <= Date.now();

  // Preview side-effects
  let billable = 0;
  let ledgerDelta = 0;
  if (order) {
    if (isDelivered && !Number.isNaN(qtyNum)) {
      billable = qtyNum * order.unit_price_paise;
      if (order.product_requires_bottle && !Number.isNaN(retNum)) {
        ledgerDelta = qtyNum - retNum;
      }
    }
    // Reversing a prior delivery creates a compensating -N
    if (order.status === 'delivered' && status !== 'delivered') {
      // assume previous delivered contributed +quantity (matches qty-returned=0 in stub)
      ledgerDelta = -((order.delivered_quantity ?? 0) - (order.bottles_returned ?? 0));
    }
  }
  const newBottleBalance = (order?.customer_bottle_balance ?? 0) + ledgerDelta;

  function reset() {
    setStatus('delivered'); setQty(''); setRet('0'); setReason(''); setError(null); setSubmitting(false);
  }

  async function submit() {
    if (!order) return;
    setSubmitting(true);
    setError(null);
    try {
      const body: any = { status, reason: reason.trim() };
      if (isDelivered) {
        body.delivered_quantity = qtyNum;
        if (needsBottles) body.bottles_returned = retNum;
      }
      await apiFetch(`/admin/delivery-orders/${order.id}/override`, { method: 'POST', body });
      toast.success(`Order → ${status}`, {
        description: ledgerDelta !== 0 ? `Bottle balance: ${order.customer_bottle_balance} → ${newBottleBalance}` : undefined,
      });
      reset();
      onOpenChange(false);
      onDone();
    } catch (e: any) {
      setError(e.message || 'Override failed');
    } finally {
      setSubmitting(false);
    }
  }

  if (!order) return null;

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) reset(); onOpenChange(v); }}>
      <DialogContent data-testid="override-modal" className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Manual override</DialogTitle>
          <DialogDescription>
            Current status: <Badge variant="outline" className="ml-1 capitalize">{order.status}</Badge> · {order.product_name} × {order.quantity}
          </DialogDescription>
        </DialogHeader>

        {bypassedCutoff && (
          <div data-testid="override-cutoff-banner" className="flex items-start gap-2 p-3 rounded-lg bg-accent/10 border border-accent/30 text-sm">
            <Lock className="w-4 h-4 text-accent mt-0.5 flex-shrink-0" />
            <div>
              <div className="font-semibold text-accent">Past cutoff — will be bypassed.</div>
              <div className="text-xs text-muted-foreground mt-0.5">Locked at {new Date(order.cutoff_locked_at!).toLocaleString('en-IN')}. This will be flagged in the audit log.</div>
            </div>
          </div>
        )}

        <div className="space-y-3">
          <div>
            <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">New status</label>
            <Select value={status} onValueChange={setStatus}>
              <SelectTrigger data-testid="override-status-select" className="mt-1 h-10">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="delivered">Mark delivered</SelectItem>
                <SelectItem value="skipped">Mark skipped</SelectItem>
                <SelectItem value="failed">Mark failed</SelectItem>
                <SelectItem value="pending">Revert to pending</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {isDelivered && (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Delivered qty *</label>
                <Input
                  data-testid="override-qty"
                  type="number" inputMode="numeric"
                  value={qty} onChange={(e) => setQty(e.target.value)}
                  placeholder={`1 – ${order.quantity * 2}`}
                  className="mt-1"
                />
              </div>
              {needsBottles && (
                <div>
                  <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Bottles returned</label>
                  <Input
                    data-testid="override-returned"
                    type="number" inputMode="numeric"
                    value={ret} onChange={(e) => setRet(e.target.value)}
                    placeholder="0"
                    className="mt-1"
                  />
                </div>
              )}
            </div>
          )}

          <div>
            <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Reason * (min 10)</label>
            <Textarea
              data-testid="override-reason"
              value={reason} onChange={(e) => setReason(e.target.value)}
              rows={3} className="mt-1" maxLength={500}
            />
            <div className="text-[11px] text-muted-foreground mt-1 flex justify-between">
              <span className={reason.length > 0 && reason.length < 10 ? 'text-accent' : ''}>
                {reason.trim().length} / 10 min
              </span>
              <span>{reason.length} / 500</span>
            </div>
          </div>

          {/* Preview */}
          <div data-testid="override-preview" className="p-3 rounded-lg bg-muted/50 border border-border/50 text-sm space-y-1">
            <div className="text-[10px] uppercase tracking-widest font-semibold text-muted-foreground">Side effects</div>
            <div className="flex justify-between"><span>Billable</span><span className="font-semibold tabular-nums">{isDelivered ? paiseToRupees(billable) : '—'}</span></div>
            <div className="flex justify-between"><span>Bottle ledger Δ</span>
              <span className={`font-semibold tabular-nums ${ledgerDelta === 0 ? '' : ledgerDelta > 0 ? 'text-secondary' : 'text-accent'}`}>
                {ledgerDelta === 0 ? '—' : (ledgerDelta > 0 ? '+' : '') + ledgerDelta}
              </span>
            </div>
            <div className="flex justify-between"><span>New bottle balance</span><span className="font-semibold tabular-nums">{newBottleBalance}</span></div>
            {order.status === 'delivered' && status !== 'delivered' && (
              <div className="mt-2 text-[11px] text-muted-foreground flex items-start gap-1.5">
                <AlertTriangle className="w-3 h-3 mt-0.5 flex-shrink-0 text-accent" />
                A compensating ledger entry will be created — original row preserved for audit.
              </div>
            )}
          </div>

          {error && (
            <div data-testid="override-error" className="p-3 rounded-lg bg-accent/10 border border-accent/30 text-sm text-accent">{error}</div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>Cancel</Button>
          <Button data-testid="override-submit" onClick={submit} disabled={!canSubmit}>
            {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Apply override'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
