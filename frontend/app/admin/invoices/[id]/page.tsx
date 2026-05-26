"use client";
import { useMemo, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  Loader2,
  CheckCircle2,
  RotateCcw,
  Wallet,
  Download,
  AlertTriangle,
  Zap,
  Calendar,
  User,
  MessageSquare,
  FileText,
  Receipt,
  CreditCard,
  Clock,
} from 'lucide-react';
import { toast } from 'sonner';
import { apiFetch, ApiError } from '@/lib/api';
import { paiseToRupees, formatDate, formatDateTime } from '@/lib/format';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

// ---------- types ----------

type InvoiceRow = {
  id: string;
  customer_id: string;
  customer_name: string | null;
  customer_phone: string;
  year: number;
  month: number;
  subtotal_paise: number;
  adjustments_paise: number;
  total_paise: number;
  amount_paid_paise: number;
  balance_due_paise: number;
  status: string;
  issued_at: string | null;
  due_date: string | null;
  paid_at: string | null;
  days_overdue: number;
  has_post_billing_adjustments: boolean;
  regenerated_count: number;
};
type LineItem = {
  id: string;
  date: string;
  product_id: string;
  product_name: string;
  product_sku: string;
  quantity: number;
  price_paise: number;
  total_paise: number;
  delivery_order_id: string | null;
};
type Adjustment = {
  id: string;
  kind: 'wallet_credit' | 'manual_credit' | 'manual_debit' | 'override_adjustment' | string;
  amount_paise: number;
  reason: string;
  actor_user_id: string | null;
  actor_name: string | null;
  reference_id: string | null;
  created_at: string;
};
type PaymentR = {
  id: string;
  amount_paise: number;
  method: string;
  reference: string | null;
  status: string;
  created_at: string;
};
type AuditR = {
  id: string;
  action: string;
  actor_name: string | null;
  before_state: any;
  after_state: any;
  reason: string | null;
  created_at: string;
};
type Detail = {
  invoice: InvoiceRow;
  line_items: LineItem[];
  adjustments: Adjustment[];
  payments: PaymentR[];
  audit_log: AuditR[];
};

const MONTH_NAMES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
function formatMonthYear(y: number, m: number) { return `${MONTH_NAMES[m - 1]} ${y}`; }

// ---------- Mark-paid modal ----------

function MarkPaidModal({
  invoice,
  open,
  onOpenChange,
  onDone,
}: {
  invoice: InvoiceRow;
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onDone: () => void;
}) {
  const remaining = invoice.balance_due_paise;
  const [priceRupees, setPriceRupees] = useState<string>((remaining / 100).toFixed(2));
  const [method, setMethod] = useState<string>('cash');
  const [reference, setReference] = useState<string>('');
  const [reason, setReason] = useState<string>('');
  const [force, setForce] = useState(false);
  const [busy, setBusy] = useState(false);

  const amountPaise = useMemo(() => {
    const n = parseFloat(priceRupees);
    if (!isFinite(n) || n <= 0) return 0;
    return Math.round(n * 100);
  }, [priceRupees]);

  const reasonOk = reason.trim().length >= 10 && reason.trim().length <= 500;
  const amountOk = amountPaise > 0;
  const exceeds = amountPaise > remaining;
  const valid = reasonOk && amountOk && (!exceeds || force);

  async function submit() {
    setBusy(true);
    try {
      await apiFetch(`/admin/invoices/${invoice.id}/mark-paid`, {
        method: 'POST',
        body: {
          amount_paise: amountPaise,
          method,
          reference: reference.trim() || null,
          reason: reason.trim(),
          force,
        },
      });
      toast.success(
        amountPaise >= remaining ? 'Invoice marked paid' : 'Partial payment recorded',
      );
      onOpenChange(false);
      onDone();
    } catch (e: any) {
      const err = e as ApiError;
      const code = err.body?.detail?.code;
      if (code === 'would_go_negative') {
        toast.error('Insufficient wallet balance for this amount');
      } else if (code === 'overpayment') {
        toast.error('Amount exceeds balance due');
      } else {
        toast.error(err.message || 'Mark-paid failed');
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => !busy && onOpenChange(v)}>
      <DialogContent className="sm:max-w-[520px]" data-testid="mark-paid-modal">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-primary" /> Record payment
          </DialogTitle>
          <DialogDescription>
            Invoice <span className="font-mono">#{invoice.id.slice(0, 8)}</span> · {invoice.customer_name || '—'}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 pt-1 text-sm">
          <div className="rounded-lg bg-muted/40 px-3 py-2">
            <div className="flex items-baseline justify-between">
              <span className="text-[10px] uppercase tracking-widest text-muted-foreground">Balance due</span>
              <span className="font-bold text-lg tabular-nums">{paiseToRupees(remaining)}</span>
            </div>
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Amount (₹)
            </label>
            <Input
              data-testid="mark-paid-amount"
              type="number"
              inputMode="decimal"
              step="0.01"
              min="0.01"
              value={priceRupees}
              onChange={(e) => setPriceRupees(e.target.value)}
              className="font-semibold tabular-nums"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Method</label>
              <Select value={method} onValueChange={setMethod}>
                <SelectTrigger data-testid="mark-paid-method"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="cash">Cash</SelectItem>
                  <SelectItem value="upi">UPI</SelectItem>
                  <SelectItem value="bank_transfer">Bank transfer</SelectItem>
                  <SelectItem value="wallet">Wallet</SelectItem>
                  <SelectItem value="other">Other</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                Reference <span className="normal-case font-normal">· optional</span>
              </label>
              <Input
                data-testid="mark-paid-reference"
                value={reference}
                onChange={(e) => setReference(e.target.value)}
                placeholder="UTR / receipt # / cheque #"
              />
            </div>
          </div>
          {method === 'wallet' && (
            <div className="rounded-lg bg-secondary/10 border border-secondary/30 px-3 py-2 text-xs">
              Wallet will be debited by <span className="font-bold">{paiseToRupees(amountPaise)}</span>.
              Requires sufficient wallet balance.
            </div>
          )}
          {exceeds && (
            <label className="flex items-center gap-2 text-xs cursor-pointer text-destructive">
              <Checkbox
                checked={force}
                onCheckedChange={(v) => setForce(!!v)}
                data-testid="mark-paid-force"
              />
              Allow overpayment (amount exceeds balance due by {paiseToRupees(amountPaise - remaining)})
            </label>
          )}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center justify-between">
              Reason
              <span className={`font-mono tabular-nums text-[10px] ${reasonOk ? 'text-muted-foreground' : 'text-destructive'}`}>
                {reason.trim().length}/10+
              </span>
            </label>
            <Textarea
              data-testid="mark-paid-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={2}
              placeholder="e.g. Customer paid cash at delivery on 22 Apr 2026."
            />
          </div>
        </div>
        <DialogFooter className="gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>Cancel</Button>
          <Button
            onClick={submit}
            disabled={!valid || busy}
            data-testid="mark-paid-submit"
            className="gap-2"
          >
            {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Record payment
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------- Wallet credit modal ----------

function WalletCreditModal({
  invoice,
  open,
  onOpenChange,
  onDone,
}: {
  invoice: InvoiceRow;
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onDone: () => void;
}) {
  const remaining = invoice.balance_due_paise;
  const [priceRupees, setPriceRupees] = useState<string>('');
  const [reason, setReason] = useState<string>('');
  const [busy, setBusy] = useState(false);

  const amountPaise = useMemo(() => {
    const n = parseFloat(priceRupees);
    if (!isFinite(n) || n <= 0) return 0;
    return Math.round(n * 100);
  }, [priceRupees]);

  const reasonOk = reason.trim().length >= 10;
  const valid = amountPaise > 0 && amountPaise <= remaining && reasonOk;

  async function submit() {
    setBusy(true);
    try {
      await apiFetch(`/admin/invoices/${invoice.id}/apply-wallet-credit`, {
        method: 'POST',
        body: { amount_paise: amountPaise, reason: reason.trim() },
      });
      toast.success(`Applied ${paiseToRupees(amountPaise)} wallet credit`);
      onOpenChange(false);
      onDone();
    } catch (e: any) {
      const err = e as ApiError;
      if (err.body?.detail?.code === 'would_go_negative') {
        toast.error('Customer wallet has insufficient balance');
      } else {
        toast.error(err.message || 'Wallet credit failed');
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => !busy && onOpenChange(v)}>
      <DialogContent className="sm:max-w-[480px]" data-testid="wallet-credit-modal">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Wallet className="w-4 h-4 text-secondary" /> Apply wallet credit
          </DialogTitle>
          <DialogDescription>
            Debits customer wallet, reduces this invoice&apos;s total by the same amount.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 pt-1 text-sm">
          <div className="rounded-lg bg-muted/40 px-3 py-2">
            <div className="flex items-baseline justify-between">
              <span className="text-[10px] uppercase tracking-widest text-muted-foreground">Balance due</span>
              <span className="font-bold text-lg tabular-nums">{paiseToRupees(remaining)}</span>
            </div>
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Credit amount (₹)</label>
            <Input
              data-testid="wallet-credit-amount"
              type="number"
              inputMode="decimal"
              step="0.01"
              min="0.01"
              max={(remaining / 100).toFixed(2)}
              value={priceRupees}
              onChange={(e) => setPriceRupees(e.target.value)}
              className="font-semibold tabular-nums"
            />
            {amountPaise > remaining && (
              <div className="text-[11px] text-destructive">Cannot exceed balance due.</div>
            )}
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center justify-between">
              Reason
              <span className={`font-mono tabular-nums text-[10px] ${reasonOk ? 'text-muted-foreground' : 'text-destructive'}`}>
                {reason.trim().length}/10+
              </span>
            </label>
            <Textarea
              data-testid="wallet-credit-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={2}
              placeholder="e.g. Apply ₹100 refund credit from earlier over-delivery."
            />
          </div>
        </div>
        <DialogFooter className="gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>Cancel</Button>
          <Button
            onClick={submit}
            disabled={!valid || busy}
            data-testid="wallet-credit-submit"
            className="gap-2"
          >
            {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Apply credit
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------- Regenerate confirm ----------

function RegenerateDialog({
  invoice,
  open,
  onOpenChange,
  onDone,
}: {
  invoice: InvoiceRow;
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onDone: () => void;
}) {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const ok = reason.trim().length >= 10;

  async function submit() {
    setBusy(true);
    try {
      await apiFetch(`/admin/invoices/${invoice.id}/regenerate`, {
        method: 'POST',
        body: { reason: reason.trim() },
      });
      toast.success('Invoice regenerated');
      onOpenChange(false);
      onDone();
    } catch (e: any) {
      toast.error(e.message || 'Regeneration failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => !busy && onOpenChange(v)}>
      <DialogContent className="sm:max-w-[500px]" data-testid="regenerate-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <RotateCcw className="w-4 h-4 text-destructive" /> Regenerate invoice
          </DialogTitle>
          <DialogDescription>
            Recomputes line items from delivered orders. Payments and manual/wallet
            adjustments are preserved; override-adjustment rows are rederived.
            Existing snapshot will be recorded in audit log.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2 pt-1 text-sm">
          <div className="rounded-lg bg-destructive/10 border border-destructive/30 px-3 py-2 text-xs">
            <div className="font-semibold flex items-center gap-1.5">
              <AlertTriangle className="w-3.5 h-3.5 text-destructive" />
              Destructive action
            </div>
            <div className="mt-1 text-muted-foreground">
              The invoice ID stays the same. Regeneration count will bump to{' '}
              <span className="font-semibold text-foreground">{(invoice.regenerated_count || 0) + 1}</span>.
            </div>
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center justify-between">
              Reason
              <span className={`font-mono tabular-nums text-[10px] ${ok ? 'text-muted-foreground' : 'text-destructive'}`}>
                {reason.trim().length}/10+
              </span>
            </label>
            <Textarea
              data-testid="regenerate-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              placeholder="e.g. Override on 18 Apr invalidated line items; regenerating to sync totals."
            />
          </div>
        </div>
        <DialogFooter className="gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>Cancel</Button>
          <Button
            onClick={submit}
            disabled={!ok || busy}
            data-testid="regenerate-submit"
            variant="destructive"
            className="gap-2"
          >
            {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Regenerate
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------- Page ----------

export default function InvoiceDetailPage() {
  const params = useParams();
  const router = useRouter();
  const qc = useQueryClient();
  const id = params?.id as string;

  const [payOpen, setPayOpen] = useState(false);
  const [walletOpen, setWalletOpen] = useState(false);
  const [regenOpen, setRegenOpen] = useState(false);

  const query = useQuery<Detail>({
    queryKey: ['admin', 'invoice', id],
    queryFn: () => apiFetch<Detail>(`/admin/invoices/${id}`),
    enabled: !!id,
  });

  if (query.isLoading || !query.data) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (query.isError) {
    return (
      <div className="py-20 text-center space-y-3">
        <div className="text-sm text-muted-foreground">Invoice not found.</div>
        <Button asChild variant="outline" size="sm">
          <Link href="/admin/billing">Back to billing</Link>
        </Button>
      </div>
    );
  }

  const d = query.data;
  const inv = d.invoice;

  function refresh() {
    qc.invalidateQueries({ queryKey: ['admin', 'invoice', id] });
    qc.invalidateQueries({ queryKey: ['admin', 'billing'] });
  }

  // Group adjustments by kind for breakdown
  const adjByKind: Record<string, Adjustment[]> = {};
  for (const a of d.adjustments) {
    (adjByKind[a.kind] ||= []).push(a);
  }

  return (
    <div className="space-y-6" data-testid="admin-invoice-detail-page">
      {/* Breadcrumb */}
      <div>
        <Link
          href="/admin/billing"
          data-testid="invoice-back-link"
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> All invoices
        </Link>
        <div className="mt-2 flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="font-display text-3xl font-bold tracking-tight flex items-center gap-3 flex-wrap">
              Invoice{' '}
              <span className="font-mono text-2xl text-muted-foreground">#{inv.id.slice(0, 8)}</span>
              {inv.status === 'paid' && (
                <Badge variant="outline" className="rounded-full text-[10px] uppercase tracking-wider bg-primary/15 text-primary border-primary/30">Paid</Badge>
              )}
              {inv.status === 'partially_paid' && (
                <Badge variant="outline" className="rounded-full text-[10px] uppercase tracking-wider bg-accent/15 text-accent border-accent/30">Partially paid</Badge>
              )}
              {inv.status === 'overdue' && (
                <Badge variant="outline" className="rounded-full text-[10px] uppercase tracking-wider bg-destructive/15 text-destructive border-destructive/30">Overdue {inv.days_overdue}d</Badge>
              )}
              {inv.status === 'issued' && (
                <Badge variant="outline" className="rounded-full text-[10px] uppercase tracking-wider bg-secondary/15 text-secondary border-secondary/30">Issued</Badge>
              )}
            </h1>
            <div className="mt-1 text-xs text-muted-foreground flex items-center gap-3 flex-wrap">
              <span className="flex items-center gap-1"><User className="w-3 h-3" /> {inv.customer_name || '—'}</span>
              <span className="tabular-nums">{inv.customer_phone}</span>
              <span>· {formatMonthYear(inv.year, inv.month)}</span>
              {inv.issued_at && <span>· Issued {formatDate(inv.issued_at)}</span>}
              {inv.due_date && <span>· Due {formatDate(inv.due_date)}</span>}
              {inv.regenerated_count > 0 && (
                <span className="text-accent font-semibold">· Regenerated {inv.regenerated_count}×</span>
              )}
            </div>
          </div>
          <div className="flex gap-2 flex-wrap">
            {inv.balance_due_paise > 0 && (
              <Button
                data-testid="invoice-mark-paid-button"
                onClick={() => setPayOpen(true)}
                size="sm"
                className="gap-2 h-9 text-xs"
              >
                <CheckCircle2 className="w-3.5 h-3.5" /> Record payment
              </Button>
            )}
            {inv.balance_due_paise > 0 && (
              <Button
                data-testid="invoice-wallet-credit-button"
                onClick={() => setWalletOpen(true)}
                size="sm"
                variant="outline"
                className="gap-2 h-9 text-xs"
              >
                <Wallet className="w-3.5 h-3.5" /> Apply wallet credit
              </Button>
            )}
            <Button
              data-testid="invoice-regenerate-button"
              onClick={() => setRegenOpen(true)}
              size="sm"
              variant="outline"
              className="gap-2 h-9 text-xs border-destructive/40 text-destructive hover:bg-destructive/5"
            >
              <RotateCcw className="w-3.5 h-3.5" /> Regenerate
            </Button>
            <Button
              data-testid="invoice-pdf-button"
              size="sm"
              variant="outline"
              onClick={() => {
                const token = typeof window !== 'undefined' ? localStorage.getItem('posuhtik.access_token') : null;
                const API_BASE = (process.env.NEXT_PUBLIC_BACKEND_URL || '').replace(/\/$/, '') + '/api';
                const filename = `posuhtik_invoice_${inv.year}_${String(inv.month).padStart(2, '0')}_${inv.id.slice(0, 8)}.pdf`;
                fetch(`${API_BASE}/admin/invoices/${inv.id}/pdf?download=true`, {
                  headers: token ? { Authorization: `Bearer ${token}` } : {},
                }).then(async (r) => {
                  if (!r.ok) { toast.error(`PDF download failed (${r.status})`); return; }
                  const blob = await r.blob();
                  const href = URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = href; a.download = filename;
                  document.body.appendChild(a); a.click(); document.body.removeChild(a);
                  URL.revokeObjectURL(href);
                  toast.success('PDF downloaded');
                }).catch((e) => toast.error(e?.message || 'PDF download failed'));
              }}
              className="gap-2 h-9 text-xs"
            >
              <Download className="w-3.5 h-3.5" /> PDF
            </Button>
          </div>
        </div>
      </div>

      {/* Warning banners */}
      {inv.has_post_billing_adjustments && (() => {
        const overrides = (adjByKind['override_adjustment'] || [])
          .slice()
          .sort((a, b) => a.created_at < b.created_at ? 1 : -1);
        const totalDelta = overrides.reduce((s, a) => s + a.amount_paise, 0);
        return (
          <div
            data-testid="post-billing-callout"
            className="rounded-2xl bg-accent/10 border-2 border-accent/40 p-5 space-y-4"
          >
            <div className="flex items-start gap-3">
              <div className="shrink-0 w-10 h-10 rounded-full bg-accent/20 flex items-center justify-center">
                <Zap className="w-5 h-5 text-accent" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline justify-between gap-3 flex-wrap">
                  <h2 className="font-display font-semibold text-base">
                    {overrides.length} post-billing change{overrides.length === 1 ? '' : 's'}
                    {overrides.length > 0 && (
                      <>
                        {' '}totalling{' '}
                        <span
                          className={`tabular-nums font-bold ${totalDelta < 0 ? 'text-secondary' : 'text-accent'}`}
                          data-testid="post-billing-total-delta"
                        >
                          {totalDelta < 0 ? '' : '+'}{paiseToRupees(totalDelta)}
                        </span>
                      </>
                    )}
                  </h2>
                  <Button
                    asChild
                    size="sm"
                    variant="outline"
                    className="h-8 text-[11px] gap-1.5 border-accent/40 text-accent hover:bg-accent/10"
                    data-testid="post-billing-regenerate-shortcut"
                  >
                    <button type="button" onClick={() => setRegenOpen(true)}>
                      <RotateCcw className="w-3 h-3" /> Regenerate to sync
                    </button>
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  Delivery override{overrides.length === 1 ? ' was' : 's were'} applied after this invoice was issued.
                  The override-adjustment rows below keep the books correct; regenerating will rederive line items
                  while preserving payments and manual credits.
                </p>
              </div>
            </div>

            {overrides.length > 0 && (
              <ul
                className="divide-y divide-accent/20 rounded-xl bg-background/50 border border-accent/20"
                data-testid="post-billing-list"
              >
                {overrides.map((a) => (
                  <li
                    key={a.id}
                    data-testid={`post-billing-row-${a.id}`}
                    className="p-3 flex items-start gap-3"
                  >
                    <div className="shrink-0">
                      <div
                        className={`tabular-nums font-bold text-sm ${a.amount_paise < 0 ? 'text-secondary' : 'text-accent'}`}
                      >
                        {a.amount_paise < 0 ? '' : '+'}{paiseToRupees(a.amount_paise)}
                      </div>
                      <div className="text-[10px] text-muted-foreground mt-0.5">
                        {formatDateTime(a.created_at)}
                      </div>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-[12px] text-foreground/90 italic truncate">
                        &ldquo;{a.reason}&rdquo;
                      </div>
                      <div className="text-[10px] text-muted-foreground mt-0.5">
                        by <span className="font-semibold text-foreground/80">{a.actor_name || 'System'}</span>
                      </div>
                    </div>
                    {a.reference_id && (
                      <Button
                        asChild
                        size="sm"
                        variant="ghost"
                        className="h-7 text-[10px] gap-1 shrink-0"
                        data-testid={`post-billing-drilldown-${a.id}`}
                      >
                        <Link href={`/admin/delivery-orders/${a.reference_id}`}>
                          View order <ArrowLeft className="w-3 h-3 rotate-180" />
                        </Link>
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })()}
      {inv.status === 'overdue' && (
        <div
          data-testid="overdue-banner"
          className="rounded-xl bg-destructive/10 border border-destructive/40 px-4 py-3 flex items-start gap-3"
        >
          <AlertTriangle className="w-5 h-5 text-destructive mt-0.5 shrink-0" />
          <div className="text-sm">
            <div className="font-semibold">Overdue by {inv.days_overdue} day{inv.days_overdue === 1 ? '' : 's'}</div>
            <div className="text-xs text-muted-foreground mt-0.5">
              Due date passed on {inv.due_date ? formatDate(inv.due_date) : '—'}. Follow up with customer.
            </div>
          </div>
        </div>
      )}

      {/* Financial summary */}
      <div
        className="rounded-2xl border-2 border-primary/20 bg-primary/5 p-5 relative overflow-hidden"
        data-testid="financial-summary"
      >
        <div className="absolute -right-4 -top-4 opacity-10">
          <Receipt className="w-32 h-32 text-primary" />
        </div>
        <div className="relative z-10 grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Subtotal</div>
            <div className="font-display font-bold text-2xl tabular-nums mt-1" data-testid="summary-subtotal">
              {paiseToRupees(inv.subtotal_paise)}
            </div>
            <div className="text-[11px] text-muted-foreground mt-0.5">
              {d.line_items.length} delivered line{d.line_items.length === 1 ? '' : 's'}
            </div>
          </div>
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Adjustments</div>
            <div
              className={`font-display font-bold text-2xl tabular-nums mt-1 ${inv.adjustments_paise !== 0 ? 'text-accent' : 'text-muted-foreground/60'}`}
              data-testid="summary-adjustments"
            >
              {inv.adjustments_paise === 0 ? '—' : paiseToRupees(inv.adjustments_paise)}
            </div>
            <div className="text-[11px] text-muted-foreground mt-0.5">
              {d.adjustments.length} entr{d.adjustments.length === 1 ? 'y' : 'ies'}
            </div>
          </div>
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-widest text-primary">Total due</div>
            <div className="font-display font-bold text-3xl tabular-nums mt-1" data-testid="summary-total">
              {paiseToRupees(inv.total_paise)}
            </div>
            <div className="text-[11px] text-muted-foreground mt-0.5">
              Paid <span className="text-foreground font-semibold">{paiseToRupees(inv.amount_paid_paise)}</span>{' '}
              · Balance{' '}
              <span className="text-foreground font-semibold" data-testid="summary-balance-due">
                {paiseToRupees(inv.balance_due_paise)}
              </span>
            </div>
          </div>
        </div>

        {/* Adjustments breakdown */}
        {d.adjustments.length > 0 && (
          <div className="mt-5 pt-4 border-t border-primary/20 relative z-10 space-y-1.5">
            <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground mb-2">
              Adjustments breakdown
            </div>
            {Object.entries(adjByKind).map(([kind, arr]) => {
              const total = arr.reduce((s, a) => s + a.amount_paise, 0);
              return (
                <div key={kind} className="flex items-center justify-between text-sm" data-testid={`adj-kind-${kind}`}>
                  <span className="text-muted-foreground capitalize">
                    {kind.replace(/_/g, ' ')} ({arr.length})
                  </span>
                  <span className={`tabular-nums font-semibold ${total < 0 ? 'text-secondary' : 'text-accent'}`}>
                    {total < 0 ? '' : '+'}
                    {paiseToRupees(total)}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Line items */}
      <div className="rounded-2xl border border-border/60 bg-card">
        <div className="p-5 border-b border-border/60">
          <h2 className="font-display text-lg font-semibold flex items-center gap-2">
            <FileText className="w-4 h-4 text-muted-foreground" /> Line items
          </h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Prices are SNAPSHOTS taken at delivery — not affected by later price changes.
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="line-items-table">
            <thead className="bg-muted/40 text-[10px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="text-left px-4 py-2 font-semibold">Date</th>
                <th className="text-left px-4 py-2 font-semibold">Product</th>
                <th className="text-right px-4 py-2 font-semibold">Qty</th>
                <th className="text-right px-4 py-2 font-semibold">Unit price</th>
                <th className="text-right px-4 py-2 font-semibold">Amount</th>
              </tr>
            </thead>
            <tbody>
              {d.line_items.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-10 text-center text-muted-foreground text-sm">
                    No delivered line items for this period.
                  </td>
                </tr>
              )}
              {d.line_items.map((li) => (
                <tr
                  key={li.id}
                  data-testid={`line-item-${li.id}`}
                  className="border-t border-border/50 h-[40px]"
                >
                  <td className="px-4 py-1.5 text-muted-foreground text-xs tabular-nums">{formatDate(li.date)}</td>
                  <td className="px-4 py-1.5">
                    <span className="font-medium">{li.product_name}</span>
                    <span className="ml-1.5 font-mono text-[10px] bg-muted/50 px-1 py-0.5 rounded text-muted-foreground">
                      {li.product_sku}
                    </span>
                  </td>
                  <td className="px-4 py-1.5 text-right tabular-nums">{li.quantity}</td>
                  <td className="px-4 py-1.5 text-right tabular-nums">{paiseToRupees(li.price_paise)}</td>
                  <td className="px-4 py-1.5 text-right tabular-nums font-semibold">{paiseToRupees(li.total_paise)}</td>
                </tr>
              ))}
            </tbody>
            {d.line_items.length > 0 && (
              <tfoot className="border-t border-border/60 bg-muted/20">
                <tr>
                  <td colSpan={4} className="px-4 py-2 text-right text-xs uppercase tracking-widest text-muted-foreground font-semibold">
                    Subtotal
                  </td>
                  <td className="px-4 py-2 text-right font-bold tabular-nums">{paiseToRupees(inv.subtotal_paise)}</td>
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      </div>

      {/* Payments */}
      {d.payments.length > 0 && (
        <div className="rounded-2xl border border-border/60 bg-card">
          <div className="p-5 border-b border-border/60">
            <h2 className="font-display text-lg font-semibold flex items-center gap-2">
              <CreditCard className="w-4 h-4 text-muted-foreground" /> Payment history
            </h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="payments-table">
              <thead className="bg-muted/40 text-[10px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="text-left px-4 py-2 font-semibold">Date</th>
                  <th className="text-left px-4 py-2 font-semibold">Method</th>
                  <th className="text-left px-4 py-2 font-semibold">Reference</th>
                  <th className="text-left px-4 py-2 font-semibold">Status</th>
                  <th className="text-right px-4 py-2 font-semibold">Amount</th>
                </tr>
              </thead>
              <tbody>
                {d.payments.map((p) => (
                  <tr key={p.id} data-testid={`payment-row-${p.id}`} className="border-t border-border/50 h-[40px]">
                    <td className="px-4 py-1.5 text-muted-foreground text-xs">{formatDateTime(p.created_at)}</td>
                    <td className="px-4 py-1.5 capitalize">{p.method.replace(/_/g, ' ')}</td>
                    <td className="px-4 py-1.5 text-xs font-mono text-muted-foreground">{p.reference || '—'}</td>
                    <td className="px-4 py-1.5">
                      <Badge
                        variant="outline"
                        className="rounded-full text-[10px] uppercase tracking-wider bg-primary/15 text-primary border-primary/30"
                      >
                        {p.status}
                      </Badge>
                    </td>
                    <td className="px-4 py-1.5 text-right tabular-nums font-semibold">{paiseToRupees(p.amount_paise)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Adjustments detail */}
      {d.adjustments.length > 0 && (
        <div className="rounded-2xl border border-border/60 bg-card">
          <div className="p-5 border-b border-border/60">
            <h2 className="font-display text-lg font-semibold flex items-center gap-2">
              <Wallet className="w-4 h-4 text-muted-foreground" /> Adjustments
            </h2>
          </div>
          <ul className="divide-y divide-border/50" data-testid="adjustments-list">
            {d.adjustments.map((a) => (
              <li key={a.id} className="p-4 flex items-start gap-4" data-testid={`adj-${a.id}`}>
                <div className="shrink-0 w-40">
                  <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">
                    {a.kind.replace(/_/g, ' ')}
                  </div>
                  <div className="text-[11px] text-muted-foreground mt-0.5">{formatDateTime(a.created_at)}</div>
                </div>
                <div className="flex-1 min-w-0">
                  <div className={`font-bold tabular-nums ${a.amount_paise < 0 ? 'text-secondary' : 'text-accent'}`}>
                    {a.amount_paise < 0 ? '' : '+'}{paiseToRupees(a.amount_paise)}
                  </div>
                  <div className="text-[12px] text-foreground/80 mt-0.5 italic">&ldquo;{a.reason}&rdquo;</div>
                  <div className="text-[10px] text-muted-foreground mt-1">
                    by {a.actor_name || 'System'}
                    {a.reference_id && <> · ref <span className="font-mono">{a.reference_id.slice(0, 12)}</span></>}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Audit log */}
      {d.audit_log.length > 0 && (
        <div className="rounded-2xl border border-border/60 bg-card">
          <div className="p-5 border-b border-border/60">
            <h2 className="font-display text-lg font-semibold flex items-center gap-2">
              <Clock className="w-4 h-4 text-muted-foreground" /> Audit log
            </h2>
          </div>
          <ul className="divide-y divide-border/50" data-testid="audit-list">
            {d.audit_log.map((a) => (
              <li key={a.id} className="p-4 flex items-start gap-4" data-testid={`audit-${a.id}`}>
                <div className="shrink-0 w-48">
                  <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">
                    {a.action}
                  </div>
                  <div className="text-[11px] text-muted-foreground mt-0.5">{formatDateTime(a.created_at)}</div>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-[11px] text-muted-foreground">
                    by <span className="text-foreground font-semibold">{a.actor_name || 'System'}</span>
                  </div>
                  {a.reason && (
                    <div className="text-[12px] text-foreground/80 mt-1 italic border-l-2 border-border pl-2">
                      &ldquo;{a.reason}&rdquo;
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      <MarkPaidModal invoice={inv} open={payOpen} onOpenChange={setPayOpen} onDone={refresh} />
      <WalletCreditModal invoice={inv} open={walletOpen} onOpenChange={setWalletOpen} onDone={refresh} />
      <RegenerateDialog invoice={inv} open={regenOpen} onOpenChange={setRegenOpen} onDone={refresh} />
    </div>
  );
}
