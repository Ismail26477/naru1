"use client";
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, Filter, RotateCw, AlertCircle, Calendar } from 'lucide-react';
import { apiFetch } from '@/lib/api';
import { paiseToRupees, formatDate, formatDateTime } from '@/lib/format';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { toast } from 'sonner';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';

type KPIs = { scheduled: number; delivered: number; pending: number; skipped: number; failed: number };
type Row = {
  id: string;
  customer_name: string | null;
  customer_phone: string;
  product_name: string;
  quantity: number;
  delivered_quantity: number | null;
  delivery_date: string;
  status: string;
  delivery_boy_name: string | null;
  route_name: string | null;
  route_sequence: number | null;
  cutoff_locked_at: string | null;
  delivered_at: string | null;
  unit_price_paise: number;
};
type Paginated = { kpis: KPIs; items: Row[]; total: number; page: number; page_size: number };

const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-muted text-muted-foreground border-border',
  delivered: 'bg-secondary/15 text-secondary border-secondary/30',
  skipped: 'bg-accent/15 text-accent border-accent/30',
  failed: 'bg-red-100 text-red-800 border-red-200',
};

export default function AdminDeliveriesPage() {
  const router = useRouter();
  const params = useSearchParams();
  const qc = useQueryClient();

  const today = new Date().toISOString().slice(0, 10);
  const [date, setDate] = useState(params.get('date') || today);
  const [routeId, setRouteId] = useState(params.get('route_id') || 'all');
  const [status, setStatus] = useState(params.get('status') || 'all');
  const [boyId, setBoyId] = useState(params.get('delivery_boy_id') || 'all');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkSkipOpen, setBulkSkipOpen] = useState(false);
  const [bulkReason, setBulkReason] = useState('');
  const [bulkBusy, setBulkBusy] = useState(false);

  const routes = useQuery<{ items: any[] }>({
    queryKey: ['admin', 'routes', 'picker'],
    queryFn: () => apiFetch('/admin/routes?page_size=100'),
    staleTime: 60_000,
  });
  const boys = useQuery<any[]>({
    queryKey: ['delivery-boys'],
    queryFn: () => apiFetch('/admin/users?role=delivery'),
    staleTime: 60_000,
  });

  const q = useQuery<Paginated>({
    queryKey: ['admin', 'deliveries', date, routeId, status, boyId],
    queryFn: () =>
      apiFetch('/admin/delivery-orders/board', {
        query: {
          date,
          route_id: routeId === 'all' ? undefined : routeId,
          status: status === 'all' ? undefined : status,
          delivery_boy_id: boyId === 'all' ? undefined : boyId,
          page_size: 200,
        },
      }),
    placeholderData: (p) => p,
  });

  const rows = q.data?.items ?? [];

  useEffect(() => {
    const qp = new URLSearchParams();
    if (date !== today) qp.set('date', date);
    if (routeId !== 'all') qp.set('route_id', routeId);
    if (status !== 'all') qp.set('status', status);
    if (boyId !== 'all') qp.set('delivery_boy_id', boyId);
    const qs = qp.toString();
    router.replace(`/admin/delivery-orders${qs ? `?${qs}` : ''}`, { scroll: false });
  }, [date, routeId, status, boyId, router, today]);

  function toggleOne(id: string, v: boolean) {
    setSelected((s) => { const n = new Set(s); v ? n.add(id) : n.delete(id); return n; });
  }
  function toggleAll(v: boolean) {
    setSelected(v ? new Set(rows.map((r) => r.id)) : new Set());
  }

  async function bulkSkip() {
    if (bulkReason.trim().length < 10 || selected.size === 0) return;
    setBulkBusy(true);
    try {
      const r = await apiFetch<{ applied: string[]; bulk_operation_id: string }>(
        '/admin/delivery-orders/bulk-skip',
        { method: 'POST', body: { order_ids: Array.from(selected), reason: bulkReason.trim() } },
      );
      toast.success(`Skipped ${r.applied.length} orders`, { description: `Bulk op: ${r.bulk_operation_id.slice(0, 8)}…` });
      setSelected(new Set()); setBulkSkipOpen(false); setBulkReason('');
      qc.invalidateQueries({ queryKey: ['admin', 'deliveries'] });
    } catch (e: any) {
      toast.error(e.message || 'Bulk skip failed');
    } finally {
      setBulkBusy(false);
    }
  }

  return (
    <div className="space-y-5" data-testid="admin-deliveries-page">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Operations</div>
          <h1 className="font-display text-3xl font-bold tracking-tight mt-1">Deliveries</h1>
        </div>
        <Button size="sm" variant="outline" onClick={() => q.refetch()} disabled={q.isFetching} className="h-9 text-xs gap-2" data-testid="deliveries-refresh">
          {q.isFetching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RotateCw className="w-3.5 h-3.5" />} Refresh
        </Button>
      </header>

      {/* Filters */}
      <div className="flex flex-wrap gap-2 items-center bg-card border border-border/60 rounded-xl p-3">
        <div className="relative">
          <Calendar className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input
            data-testid="deliveries-date-picker"
            type="date" value={date} onChange={(e) => setDate(e.target.value)}
            className="pl-9 h-9 w-[170px] text-sm"
          />
        </div>
        <Select value={routeId} onValueChange={setRouteId}>
          <SelectTrigger className="h-9 w-[180px] text-sm" data-testid="deliveries-route-filter">
            <Filter className="w-3.5 h-3.5 mr-1.5" />
            <SelectValue placeholder="All routes" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All routes</SelectItem>
            {(routes.data?.items ?? []).map((r: any) => (
              <SelectItem key={r.id} value={r.id}>{r.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="h-9 w-[150px] text-sm" data-testid="deliveries-status-filter">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="pending">Pending</SelectItem>
            <SelectItem value="delivered">Delivered</SelectItem>
            <SelectItem value="skipped">Skipped</SelectItem>
            <SelectItem value="failed">Failed</SelectItem>
          </SelectContent>
        </Select>
        <Select value={boyId} onValueChange={setBoyId}>
          <SelectTrigger className="h-9 w-[180px] text-sm" data-testid="deliveries-boy-filter">
            <SelectValue placeholder="All delivery boys" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All delivery boys</SelectItem>
            {(boys.data ?? []).map((b: any) => (<SelectItem key={b.id} value={b.id}>{b.name || b.phone}</SelectItem>))}
          </SelectContent>
        </Select>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {[
          { label: 'Scheduled', key: 'scheduled', tone: 'bg-muted text-muted-foreground' },
          { label: 'Pending', key: 'pending', tone: 'bg-primary/10 text-primary border-primary/20' },
          { label: 'Delivered', key: 'delivered', tone: 'bg-secondary/10 text-secondary border-secondary/30' },
          { label: 'Skipped', key: 'skipped', tone: 'bg-accent/10 text-accent border-accent/30' },
          { label: 'Failed', key: 'failed', tone: 'bg-red-50 text-red-800 border-red-200' },
        ].map((k) => (
          <div key={k.key} data-testid={`kpi-${k.key}`} className={`rounded-xl p-3 border ${k.tone}`}>
            <div className="text-[10px] font-semibold uppercase tracking-wider">{k.label}</div>
            <div className="font-display text-xl font-bold tabular-nums mt-1">
              {q.isLoading ? '—' : (q.data?.kpis?.[k.key as keyof KPIs] ?? 0)}
            </div>
          </div>
        ))}
      </div>

      {/* Bulk bar */}
      {selected.size > 0 && (
        <div data-testid="bulk-bar" className="flex items-center justify-between gap-3 bg-foreground text-background rounded-xl px-4 py-2.5 text-sm">
          <div><span className="font-semibold">{selected.size}</span> selected</div>
          <div className="flex gap-2">
            <Button data-testid="bulk-skip-open" size="sm" variant="default" onClick={() => setBulkSkipOpen(true)} className="h-8 text-xs">
              Bulk skip with reason
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())} className="h-8 text-xs text-background hover:bg-white/10">Clear</Button>
          </div>
        </div>
      )}

      {/* Table */}
      <div className="bg-card border border-border/60 rounded-xl overflow-hidden">
        <table className="w-full text-sm" data-testid="deliveries-table">
          <thead className="bg-muted/40 text-[10px] uppercase tracking-wider text-muted-foreground">
            <tr>
              <th className="px-3 py-2 w-[36px]">
                <Checkbox checked={rows.length > 0 && rows.every((r) => selected.has(r.id))} onCheckedChange={(v) => toggleAll(!!v)} />
              </th>
              <th className="text-right px-3 py-2 font-semibold w-[60px]">Seq</th>
              <th className="text-left px-3 py-2 font-semibold">Customer</th>
              <th className="text-left px-3 py-2 font-semibold">Product</th>
              <th className="text-right px-3 py-2 font-semibold">Qty</th>
              <th className="text-left px-3 py-2 font-semibold">Status</th>
              <th className="text-left px-3 py-2 font-semibold">Route</th>
              <th className="text-left px-3 py-2 font-semibold">Boy</th>
              <th className="text-left px-3 py-2 font-semibold">Delivered at</th>
              <th className="text-right px-3 py-2 font-semibold">Value</th>
            </tr>
          </thead>
          <tbody>
            {q.isLoading && <tr><td colSpan={10} className="px-3 py-12 text-center text-muted-foreground"><Loader2 className="inline w-4 h-4 animate-spin" /> Loading…</td></tr>}
            {!q.isLoading && rows.length === 0 && (
              <tr><td colSpan={10} className="px-3 py-16 text-center" data-testid="deliveries-empty-state">
                <AlertCircle className="inline w-5 h-5 opacity-40 mb-2" /><br />
                <span className="text-sm text-muted-foreground">No delivery orders for {formatDate(date)}.</span>
              </td></tr>
            )}
            {rows.map((r) => (
              <tr
                key={r.id}
                data-testid={`delivery-row-${r.id}`}
                className="border-t border-border/50 hover:bg-muted/30 cursor-pointer h-[40px]"
                onClick={() => router.push(`/admin/delivery-orders/${r.id}`)}
              >
                <td className="px-3 py-1.5" onClick={(e) => e.stopPropagation()}>
                  <Checkbox
                    checked={selected.has(r.id)}
                    onCheckedChange={(v) => toggleOne(r.id, !!v)}
                    data-testid={`delivery-select-${r.id}`}
                  />
                </td>
                <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{r.route_sequence ?? '—'}</td>
                <td className="px-3 py-1.5">
                  <div className="font-medium truncate max-w-[180px]">{r.customer_name || '—'}</div>
                  <div className="text-[11px] text-muted-foreground tabular-nums">{r.customer_phone}</div>
                </td>
                <td className="px-3 py-1.5 text-xs">{r.product_name}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{r.delivered_quantity ?? r.quantity}</td>
                <td className="px-3 py-1.5">
                  <Badge variant="outline" className={`rounded-full text-[10px] uppercase tracking-wider capitalize ${STATUS_COLORS[r.status] || ''}`}>
                    {r.status}
                  </Badge>
                </td>
                <td className="px-3 py-1.5 text-xs text-muted-foreground truncate max-w-[140px]">{r.route_name || '—'}</td>
                <td className="px-3 py-1.5 text-xs text-muted-foreground truncate max-w-[140px]">{r.delivery_boy_name || '—'}</td>
                <td className="px-3 py-1.5 text-xs text-muted-foreground tabular-nums">{r.delivered_at ? formatDateTime(r.delivered_at) : '—'}</td>
                <td className="px-3 py-1.5 text-right tabular-nums text-xs">{paiseToRupees(r.quantity * r.unit_price_paise)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Bulk skip dialog */}
      <Dialog open={bulkSkipOpen} onOpenChange={setBulkSkipOpen}>
        <DialogContent data-testid="bulk-skip-dialog">
          <DialogHeader>
            <DialogTitle>Bulk skip {selected.size} orders</DialogTitle>
            <DialogDescription>Reason will be written to every order's audit log with a shared bulk_operation_id.</DialogDescription>
          </DialogHeader>
          <div>
            <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Reason * (min 10 chars)</label>
            <Textarea data-testid="bulk-skip-reason" value={bulkReason} onChange={(e) => setBulkReason(e.target.value)} rows={3} className="mt-1" maxLength={500} />
            <div className="text-[11px] text-muted-foreground mt-1">{bulkReason.trim().length} / 10 min</div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setBulkSkipOpen(false)}>Cancel</Button>
            <Button data-testid="bulk-skip-confirm" onClick={bulkSkip} disabled={bulkReason.trim().length < 10 || bulkBusy} className="bg-accent hover:bg-accent/90">
              {bulkBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Skip selected'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
