"use client";
import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Receipt,
  Play,
  AlertTriangle,
  Download,
  Search,
  Filter,
  Loader2,
  X,
  CheckCircle2,
  Clock,
  AlertCircle,
  TrendingUp,
  PhoneCall,
  Zap,
} from 'lucide-react';
import { toast } from 'sonner';
import { apiFetch, ApiError } from '@/lib/api';
import { paiseToRupees, formatDate, formatDateTime } from '@/lib/format';
import { downloadCsv } from '@/lib/csv';
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

// ------------------ types ------------------

type BillingStatus = {
  year: number;
  month: number;
  invoice_count: number;
  by_status: Record<string, number>;
  subtotal_paise: number;
  total_billed_paise: number;
  total_collected_paise: number;
  outstanding_paise: number;
  last_generated_at: string | null;
  last_generated_by: string | null;
  regenerations: number;
  failed_customers_last_run: number;
};

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

type Paginated = { items: InvoiceRow[]; total: number; page: number; page_size: number };

type Overdue = {
  customer_id: string;
  customer_name: string | null;
  customer_phone: string;
  oldest_overdue_invoice_id: string;
  oldest_due_date: string;
  days_overdue: number;
  overdue_count: number;
  overdue_total_paise: number;
};

// ------------------ helpers ------------------

const MONTH_NAMES = [
  'Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec',
];

function nowIstYearMonth(): { year: number; month: number } {
  const istMs = Date.now() + 5.5 * 60 * 60 * 1000;
  const d = new Date(istMs);
  return { year: d.getUTCFullYear(), month: d.getUTCMonth() + 1 };
}

function formatMonthYear(y: number, m: number): string {
  return `${MONTH_NAMES[m - 1]} ${y}`;
}

function InvoiceStatusBadge({ status, overdueDays }: { status: string; overdueDays: number }) {
  const map: Record<string, string> = {
    draft:         'bg-muted text-muted-foreground border-muted-foreground/20',
    issued:        'bg-secondary/15 text-secondary border-secondary/30',
    partially_paid:'bg-accent/15 text-accent border-accent/30',
    paid:          'bg-primary/15 text-primary border-primary/30',
    overdue:       'bg-destructive/15 text-destructive border-destructive/30',
  };
  const cls = map[status] || 'bg-muted text-muted-foreground';
  const label =
    status === 'partially_paid'
      ? 'Part. paid'
      : status === 'overdue'
        ? `Overdue ${overdueDays}d`
        : status.charAt(0).toUpperCase() + status.slice(1);
  return (
    <Badge variant="outline" className={`rounded-full text-[10px] uppercase tracking-wider ${cls}`}>
      {label}
    </Badge>
  );
}

// ------------------ Generate dialog ------------------

function GenerateDialog({
  open,
  onOpenChange,
  year,
  month,
  existingCount,
  onDone,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  year: number;
  month: number;
  existingCount: number;
  onDone: () => void;
}) {
  const [regenerate, setRegenerate] = useState(false);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  useEffect(() => {
    if (open) {
      setRegenerate(existingCount > 0);
      setReason('');
    }
  }, [open, existingCount]);

  const needsRegenerate = existingCount > 0;
  const reasonValid = !needsRegenerate || (regenerate && reason.trim().length >= 10);
  const valid = reasonValid && (!needsRegenerate || regenerate);

  async function submit() {
    setBusy(true);
    try {
      const r = await apiFetch<any>('/admin/billing/generate', {
        method: 'POST',
        body: {
          year,
          month,
          regenerate,
          reason: regenerate ? reason.trim() : null,
        },
      });
      toast.success(
        regenerate
          ? `Regenerated ${r.regenerated_count} invoice${r.regenerated_count === 1 ? '' : 's'}`
          : `Created ${r.created_count} invoice${r.created_count === 1 ? '' : 's'}`,
      );
      if (r.failed?.length) {
        toast.warning(`${r.failed.length} customer${r.failed.length === 1 ? '' : 's'} failed — check audit log`);
      }
      setConfirmOpen(false);
      onOpenChange(false);
      onDone();
    } catch (e: any) {
      const err = e as ApiError;
      if (err.body?.detail?.code === 'invoices_already_exist') {
        toast.error(`Invoices already exist — tick "Regenerate" to replace them`);
      } else if (err.body?.detail?.code === 'billing_generation_locked') {
        toast.error('Generation already in progress for this month');
      } else {
        toast.error(err.message || 'Generation failed');
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Dialog open={open} onOpenChange={(v) => !busy && onOpenChange(v)}>
        <DialogContent className="sm:max-w-[520px]" data-testid="generate-billing-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Play className="w-4 h-4 text-primary" /> Generate invoices — {formatMonthYear(year, month)}
            </DialogTitle>
            <DialogDescription>
              Creates one invoice per customer who had DELIVERED orders in this month.
              Each line item is locked to the price snapshot on the delivery order.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 pt-1 text-sm">
            {needsRegenerate && (
              <div className="rounded-lg bg-accent/10 border border-accent/30 px-3 py-2.5 text-xs">
                <div className="font-semibold flex items-center gap-1.5">
                  <AlertTriangle className="w-3.5 h-3.5 text-accent" />
                  {existingCount} invoices already exist for this period
                </div>
                <div className="mt-1 text-muted-foreground">
                  To replace them, tick <span className="font-semibold">Regenerate</span> and provide a reason.
                  Existing payments will be preserved; old invoice snapshot will be written to audit log.
                </div>
              </div>
            )}
            <label className="flex items-start gap-2 text-sm cursor-pointer">
              <Checkbox
                checked={regenerate}
                onCheckedChange={(v) => setRegenerate(!!v)}
                disabled={!needsRegenerate}
                data-testid="generate-regenerate-checkbox"
                className="mt-0.5"
              />
              <span>
                <span className="font-semibold">Regenerate</span> — replace existing invoices for this month
              </span>
            </label>
            {regenerate && (
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center justify-between">
                  Reason
                  <span className={`font-mono tabular-nums text-[10px] ${reasonValid ? 'text-muted-foreground' : 'text-destructive'}`}>
                    {reason.trim().length}/10+
                  </span>
                </label>
                <Textarea
                  data-testid="generate-reason"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  rows={2}
                  placeholder="e.g. Fixing post-override adjustments for Apr; corrective regen per ops review."
                />
              </div>
            )}
          </div>
          <DialogFooter className="gap-2">
            <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
              Cancel
            </Button>
            <Button
              onClick={() => setConfirmOpen(true)}
              disabled={!valid || busy}
              data-testid="generate-review"
            >
              Review &amp; run
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={confirmOpen} onOpenChange={(v) => !busy && setConfirmOpen(v)}>
        <AlertDialogContent data-testid="generate-confirm-dialog">
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-accent" />
              Confirm invoice generation
            </AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-2 text-sm">
                <div>
                  {regenerate
                    ? `Regenerate all ${existingCount} invoices for ${formatMonthYear(year, month)}?`
                    : `Generate invoices for ${formatMonthYear(year, month)}?`}
                </div>
                <div className="text-muted-foreground">
                  Totals are computed from <span className="font-semibold text-foreground">DELIVERED</span> orders only.
                  Prices locked at delivery-order snapshot.
                </div>
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              data-testid="generate-submit"
              onClick={(e) => { e.preventDefault(); submit(); }}
              disabled={busy}
            >
              {busy ? <><Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" /> Running…</> : 'Run now'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

// ------------------ Billing period card ------------------

function PeriodStatusCard({
  status,
  year,
  month,
  onGenerate,
  onMonthChange,
}: {
  status: BillingStatus | undefined;
  year: number;
  month: number;
  onGenerate: () => void;
  onMonthChange: (y: number, m: number) => void;
}) {
  const n = nowIstYearMonth();
  const isCurrent = year === n.year && month === n.month;

  function monthOptions(): Array<{ y: number; m: number; label: string }> {
    const opts: Array<{ y: number; m: number; label: string }> = [];
    let y = n.year;
    let m = n.month;
    for (let i = 0; i < 12; i++) {
      opts.push({ y, m, label: formatMonthYear(y, m) });
      m -= 1;
      if (m < 1) { m = 12; y -= 1; }
    }
    return opts;
  }

  const opts = monthOptions();
  const totalStatusCount = status ? Object.values(status.by_status).reduce((s, v) => s + v, 0) : 0;

  return (
    <div
      data-testid="billing-period-card"
      className="rounded-2xl border-2 border-primary/20 bg-primary/5 p-5 md:p-6 relative overflow-hidden"
    >
      <div className="absolute -right-4 -top-4 opacity-10">
        <Receipt className="w-32 h-32 text-primary" />
      </div>
      <div className="flex items-start justify-between gap-4 flex-wrap relative z-10">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-widest text-primary">
            Billing period
          </div>
          <div className="flex items-center gap-3 mt-1 flex-wrap">
            <h2 className="font-display text-3xl font-bold tabular-nums" data-testid="billing-period-label">
              {formatMonthYear(year, month)}
            </h2>
            <Select
              value={`${year}-${String(month).padStart(2, '0')}`}
              onValueChange={(v) => {
                const [y, m] = v.split('-').map(Number);
                onMonthChange(y, m);
              }}
            >
              <SelectTrigger className="h-8 w-[150px] text-xs" data-testid="billing-month-select">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {opts.map((o) => (
                  <SelectItem key={`${o.y}-${o.m}`} value={`${o.y}-${String(o.m).padStart(2, '0')}`}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {isCurrent && (
              <Badge variant="outline" className="rounded-full text-[10px] uppercase tracking-wider bg-secondary/15 text-secondary border-secondary/30">
                Current
              </Badge>
            )}
          </div>
          <div className="mt-2 text-xs text-muted-foreground">
            {status?.last_generated_at ? (
              <>
                Last run{' '}
                <span className="text-foreground font-semibold">
                  {formatDateTime(status.last_generated_at)}
                </span>{' '}
                by {status.last_generated_by || 'System'}
                {status.regenerations > 0 && (
                  <>
                    {' · '}
                    <span className="text-accent font-semibold">
                      Regenerated {status.regenerations}×
                    </span>
                  </>
                )}
              </>
            ) : (
              <span className="italic">Not yet generated</span>
            )}
          </div>
        </div>
        <Button
          onClick={onGenerate}
          size="lg"
          data-testid="billing-generate-button"
          className="gap-2 relative z-10"
        >
          <Play className="w-4 h-4" />
          {totalStatusCount > 0 ? 'Regenerate invoices' : 'Generate invoices'}
        </Button>
      </div>

      {/* KPIs */}
      <div className="mt-5 grid grid-cols-2 md:grid-cols-4 gap-3 relative z-10">
        <KpiCell label="Invoices" value={status?.invoice_count ?? 0} testid="kpi-invoice-count" />
        <KpiCell label="Total billed" value={paiseToRupees(status?.total_billed_paise ?? 0)} testid="kpi-billed" />
        <KpiCell label="Collected" value={paiseToRupees(status?.total_collected_paise ?? 0)} testid="kpi-collected" />
        <KpiCell
          label="Outstanding"
          value={paiseToRupees(status?.outstanding_paise ?? 0)}
          testid="kpi-outstanding"
          accent={status?.outstanding_paise ? 'bg-destructive/10 border-destructive/30 text-destructive' : undefined}
        />
      </div>

      {/* Status breakdown */}
      {status && totalStatusCount > 0 && (
        <div className="mt-4 flex gap-2 flex-wrap relative z-10">
          {Object.entries(status.by_status).map(([k, v]) => (
            <Badge
              key={k}
              variant="outline"
              className="rounded-full text-[10px] uppercase tracking-wider bg-card"
              data-testid={`status-pill-${k}`}
            >
              {k}: <span className="ml-1 font-bold tabular-nums">{v}</span>
            </Badge>
          ))}
          {status.failed_customers_last_run > 0 && (
            <Badge
              variant="outline"
              className="rounded-full text-[10px] uppercase tracking-wider bg-destructive/10 text-destructive border-destructive/30"
              data-testid="failed-last-run"
            >
              {status.failed_customers_last_run} failed last run
            </Badge>
          )}
        </div>
      )}
    </div>
  );
}

function KpiCell({
  label,
  value,
  testid,
  accent,
}: {
  label: string;
  value: string | number;
  testid: string;
  accent?: string;
}) {
  return (
    <div
      data-testid={testid}
      className={`rounded-xl border ${accent || 'border-border/60 bg-card'} p-3`}
    >
      <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 font-display font-bold text-xl tabular-nums">{value}</div>
    </div>
  );
}

// ------------------ Main page ------------------

export default function AdminBillingPage() {
  const router = useRouter();
  const params = useSearchParams();
  const qc = useQueryClient();

  const n = nowIstYearMonth();
  const urlY = parseInt(params.get('year') || String(n.year), 10);
  const urlM = parseInt(params.get('month') || String(n.month), 10);
  const [year, setYear] = useState(urlY);
  const [month, setMonth] = useState(urlM);
  const [openGen, setOpenGen] = useState(false);

  // List filters
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [hasAdj, setHasAdj] = useState(false);
  const [page, setPage] = useState(1);

  // Persist month in URL
  useEffect(() => {
    const qp = new URLSearchParams();
    qp.set('year', String(year));
    qp.set('month', String(month));
    router.replace(`/admin/billing?${qp.toString()}`, { scroll: false });
  }, [year, month, router]);

  // Reset page when month changes
  useEffect(() => { setPage(1); }, [year, month, statusFilter, hasAdj]);

  const statusQuery = useQuery<BillingStatus>({
    queryKey: ['admin', 'billing', 'status', year, month],
    queryFn: () =>
      apiFetch<BillingStatus>('/admin/billing/status', { query: { year, month } }),
  });

  const listQuery = useQuery<Paginated>({
    queryKey: ['admin', 'billing', 'list', year, month, statusFilter, hasAdj, page],
    queryFn: () =>
      apiFetch<Paginated>('/admin/invoices', {
        query: {
          year, month,
          status: statusFilter === 'all' ? undefined : statusFilter,
          has_adjustments: hasAdj ? 'true' : undefined,
          page, page_size: 50,
        },
      }),
    placeholderData: (prev) => prev,
  });

  const overdueQuery = useQuery<Overdue[]>({
    queryKey: ['admin', 'billing', 'overdue'],
    queryFn: () => apiFetch<Overdue[]>('/admin/billing/overdue'),
  });

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const items = listQuery.data?.items ?? [];
    if (!q) return items;
    return items.filter(
      (r) =>
        (r.customer_name || '').toLowerCase().includes(q) ||
        r.customer_phone.includes(q),
    );
  }, [listQuery.data, search]);

  function refreshAll() {
    qc.invalidateQueries({ queryKey: ['admin', 'billing'] });
  }

  function exportRegisterCsv() {
    // Export the currently-loaded page (server-side register CSV is a Phase 2B.7 scope item).
    const rows = filtered;
    if (!rows.length) return;
    downloadCsv(
      `posuhtik-billing-${year}-${String(month).padStart(2, '0')}.csv`,
      rows.map((r) => ({
        invoice_id: r.id,
        customer_name: r.customer_name,
        customer_phone: r.customer_phone,
        period: `${year}-${String(month).padStart(2, '0')}`,
        subtotal_rupees: (r.subtotal_paise / 100).toFixed(2),
        adjustments_rupees: (r.adjustments_paise / 100).toFixed(2),
        total_rupees: (r.total_paise / 100).toFixed(2),
        paid_rupees: (r.amount_paid_paise / 100).toFixed(2),
        balance_due_rupees: (r.balance_due_paise / 100).toFixed(2),
        status: r.status,
        due_date: r.due_date,
        paid_at: r.paid_at,
        days_overdue: r.days_overdue,
        post_billing_adjustments: r.has_post_billing_adjustments,
        regenerated_count: r.regenerated_count,
      })),
    );
    toast.success('CSV downloaded');
  }

  const total = listQuery.data?.total ?? 0;
  const pageSize = listQuery.data?.page_size ?? 50;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="space-y-6" data-testid="admin-billing-page">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
            Finance
          </div>
          <h1 className="font-display text-3xl font-bold tracking-tight mt-1">Billing</h1>
        </div>
        <Button
          data-testid="billing-export-csv"
          variant="outline"
          size="sm"
          onClick={exportRegisterCsv}
          disabled={!filtered.length}
          className="gap-2 h-9 text-xs"
        >
          <Download className="w-3.5 h-3.5" /> Export register CSV
        </Button>
      </header>

      <PeriodStatusCard
        status={statusQuery.data}
        year={year}
        month={month}
        onGenerate={() => setOpenGen(true)}
        onMonthChange={(y, m) => { setYear(y); setMonth(m); }}
      />

      {/* Invoices list */}
      <div>
        <div className="flex items-center justify-between gap-2 mb-3">
          <h2 className="font-display text-lg font-semibold flex items-center gap-2">
            <Receipt className="w-4 h-4 text-muted-foreground" /> Invoices
          </h2>
        </div>
        <div className="flex flex-wrap gap-2 items-center bg-card border border-border/60 rounded-xl p-3">
          <div className="relative flex-1 min-w-[220px]">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input
              data-testid="invoices-search"
              placeholder="Search customer name or phone"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 h-9 text-sm"
            />
          </div>
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="h-9 w-[170px] text-sm" data-testid="invoices-status-filter">
              <Filter className="w-3.5 h-3.5 mr-1.5" />
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              <SelectItem value="issued">Issued</SelectItem>
              <SelectItem value="partially_paid">Partially paid</SelectItem>
              <SelectItem value="paid">Paid</SelectItem>
              <SelectItem value="overdue">Overdue</SelectItem>
            </SelectContent>
          </Select>
          <label className="flex items-center gap-2 text-xs cursor-pointer ml-1">
            <Checkbox
              checked={hasAdj}
              onCheckedChange={(v) => setHasAdj(!!v)}
              data-testid="invoices-has-adj"
            />
            Post-billing adjustments only
          </label>
        </div>

        <div className="bg-card border border-border/60 rounded-xl overflow-hidden mt-3">
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="invoices-table">
              <thead className="bg-muted/40 text-[10px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="text-left px-3 py-2 font-semibold">Customer</th>
                  <th className="text-right px-3 py-2 font-semibold">Subtotal</th>
                  <th className="text-right px-3 py-2 font-semibold">Adj.</th>
                  <th className="text-right px-3 py-2 font-semibold">Total</th>
                  <th className="text-right px-3 py-2 font-semibold">Paid</th>
                  <th className="text-right px-3 py-2 font-semibold">Due</th>
                  <th className="text-left px-3 py-2 font-semibold">Due date</th>
                  <th className="text-left px-3 py-2 font-semibold">Status</th>
                </tr>
              </thead>
              <tbody>
                {listQuery.isLoading && (
                  <tr>
                    <td colSpan={8} className="px-3 py-16 text-center text-muted-foreground">
                      <Loader2 className="inline w-4 h-4 animate-spin" /> Loading…
                    </td>
                  </tr>
                )}
                {!listQuery.isLoading && filtered.length === 0 && (
                  <tr>
                    <td colSpan={8} className="px-3 py-16 text-center">
                      <div
                        className="text-muted-foreground text-sm flex flex-col items-center gap-2"
                        data-testid="invoices-empty-state"
                      >
                        <AlertCircle className="w-6 h-6 opacity-40" />
                        <div>No invoices for this period yet.</div>
                      </div>
                    </td>
                  </tr>
                )}
                {filtered.map((r) => (
                  <tr
                    key={r.id}
                    data-testid={`invoice-row-${r.id}`}
                    className="border-t border-border/50 hover:bg-muted/30 cursor-pointer h-[40px]"
                    onClick={() => router.push(`/admin/invoices/${r.id}`)}
                  >
                    <td className="px-3 py-1.5">
                      <div className="font-medium truncate max-w-[200px]">{r.customer_name || '—'}</div>
                      <div className="text-[11px] text-muted-foreground tabular-nums">{r.customer_phone}</div>
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{paiseToRupees(r.subtotal_paise)}</td>
                    <td
                      className={`px-3 py-1.5 text-right tabular-nums ${r.adjustments_paise !== 0 ? 'text-accent' : 'text-muted-foreground/60'}`}
                    >
                      {r.adjustments_paise === 0 ? '—' : paiseToRupees(r.adjustments_paise)}
                      {r.has_post_billing_adjustments && (
                        <Zap className="inline w-3 h-3 ml-1 text-accent" aria-label="Post-billing adjustments" />
                      )}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums font-semibold">
                      {paiseToRupees(r.total_paise)}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                      {r.amount_paid_paise > 0 ? paiseToRupees(r.amount_paid_paise) : '—'}
                    </td>
                    <td
                      className={`px-3 py-1.5 text-right tabular-nums ${r.balance_due_paise > 0 ? 'font-semibold' : 'text-muted-foreground/60'}`}
                    >
                      {r.balance_due_paise > 0 ? paiseToRupees(r.balance_due_paise) : '—'}
                    </td>
                    <td className="px-3 py-1.5 text-muted-foreground text-xs">
                      {r.due_date ? formatDate(r.due_date) : '—'}
                    </td>
                    <td className="px-3 py-1.5">
                      <InvoiceStatusBadge status={r.status} overdueDays={r.days_overdue} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {total > pageSize && (
          <div className="flex items-center justify-between mt-3">
            <div className="text-xs text-muted-foreground">
              Showing{' '}
              <span className="font-semibold text-foreground">{(page - 1) * pageSize + 1}</span>
              –<span className="font-semibold text-foreground">{Math.min(page * pageSize, total)}</span>{' '}
              of <span className="font-semibold text-foreground tabular-nums">{total}</span>
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline" size="sm" className="h-8 text-xs"
                onClick={() => setPage(page - 1)}
                disabled={page <= 1}
              >
                Previous
              </Button>
              <div className="flex items-center px-3 text-xs text-muted-foreground tabular-nums">
                Page {page} / {totalPages}
              </div>
              <Button
                variant="outline" size="sm" className="h-8 text-xs"
                onClick={() => setPage(page + 1)}
                disabled={page >= totalPages}
              >
                Next
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* Overdue customers */}
      <div>
        <h2 className="font-display text-lg font-semibold flex items-center gap-2 mb-3">
          <AlertTriangle className="w-4 h-4 text-destructive" /> Overdue customers
        </h2>
        <div className="bg-card border border-border/60 rounded-xl overflow-hidden">
          <table className="w-full text-sm" data-testid="overdue-table">
            <thead className="bg-muted/40 text-[10px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="text-left px-3 py-2 font-semibold">Customer</th>
                <th className="text-right px-3 py-2 font-semibold">Overdue invoices</th>
                <th className="text-right px-3 py-2 font-semibold">Total overdue</th>
                <th className="text-left px-3 py-2 font-semibold">Oldest due</th>
                <th className="text-right px-3 py-2 font-semibold">Days overdue</th>
                <th className="text-right px-3 py-2 font-semibold">Action</th>
              </tr>
            </thead>
            <tbody>
              {overdueQuery.isLoading && (
                <tr>
                  <td colSpan={6} className="px-3 py-10 text-center text-muted-foreground">
                    <Loader2 className="inline w-4 h-4 animate-spin" /> Loading…
                  </td>
                </tr>
              )}
              {!overdueQuery.isLoading && (overdueQuery.data?.length ?? 0) === 0 && (
                <tr>
                  <td colSpan={6} className="px-3 py-10 text-center">
                    <div className="text-muted-foreground text-sm flex flex-col items-center gap-2" data-testid="overdue-empty-state">
                      <CheckCircle2 className="w-6 h-6 opacity-60 text-secondary" />
                      <div>No overdue invoices. All caught up.</div>
                    </div>
                  </td>
                </tr>
              )}
              {(overdueQuery.data ?? []).map((r) => (
                <tr
                  key={r.customer_id}
                  data-testid={`overdue-row-${r.customer_id}`}
                  className="border-t border-border/50 hover:bg-muted/30 h-[40px]"
                >
                  <td className="px-3 py-1.5">
                    <div className="font-medium truncate max-w-[200px]">{r.customer_name || '—'}</div>
                    <div className="text-[11px] text-muted-foreground tabular-nums">{r.customer_phone}</div>
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{r.overdue_count}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums font-semibold text-destructive">
                    {paiseToRupees(r.overdue_total_paise)}
                  </td>
                  <td className="px-3 py-1.5 text-muted-foreground text-xs">{formatDate(r.oldest_due_date)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    <span className="px-2 py-0.5 bg-destructive/10 text-destructive rounded-full text-[10px] font-semibold">
                      {r.days_overdue}d
                    </span>
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    <Button
                      asChild
                      variant="outline"
                      size="sm"
                      className="h-7 text-xs"
                      data-testid={`overdue-view-${r.customer_id}`}
                    >
                      <Link href={`/admin/invoices/${r.oldest_overdue_invoice_id}`}>
                        View oldest
                      </Link>
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <GenerateDialog
        open={openGen}
        onOpenChange={setOpenGen}
        year={year}
        month={month}
        existingCount={statusQuery.data?.invoice_count ?? 0}
        onDone={refreshAll}
      />
    </div>
  );
}
