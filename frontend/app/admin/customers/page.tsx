"use client";
import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useRouter, useSearchParams } from 'next/navigation';
import { Search, Download, CheckCircle2, Loader2, Filter, X, AlertCircle } from 'lucide-react';
import { toast } from 'sonner';
import { apiFetch } from '@/lib/api';
import { paiseToRupees, formatDate } from '@/lib/format';
import { downloadCsv } from '@/lib/csv';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Badge } from '@/components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

type Row = {
  id: string;
  phone: string;
  name: string | null;
  email: string | null;
  approved_at: string | null;
  is_active: boolean;
  created_at: string;
  wallet_balance_paise: number;
  bottle_balance: number;
  active_subs_count: number;
  area: string | null;
  last_delivery_date: string | null;
};

type Paginated = { items: Row[]; total: number; page: number; page_size: number };

function StatusBadge({ row }: { row: Row }) {
  if (!row.is_active) return <Badge variant="secondary" className="rounded-full text-[10px] uppercase tracking-wider">Inactive</Badge>;
  if (!row.approved_at)
    return <Badge className="rounded-full text-[10px] uppercase tracking-wider bg-accent/15 text-accent border-accent/30" variant="outline">Pending</Badge>;
  return <Badge className="rounded-full text-[10px] uppercase tracking-wider bg-secondary/15 text-secondary border-secondary/30" variant="outline">Active</Badge>;
}

export default function AdminCustomersPage() {
  const router = useRouter();
  const params = useSearchParams();
  const qc = useQueryClient();

  const [search, setSearch] = useState(params.get('q') || '');
  const [debounced, setDebounced] = useState(search);
  const [status, setStatus] = useState<string>(params.get('status') || 'all');
  const page = Math.max(1, parseInt(params.get('page') || '1', 10));
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);

  // Debounce 300ms
  useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  // Persist page/search/status into URL
  useEffect(() => {
    const qp = new URLSearchParams();
    if (debounced) qp.set('q', debounced);
    if (status !== 'all') qp.set('status', status);
    if (page !== 1) qp.set('page', String(page));
    const qs = qp.toString();
    router.replace(`/admin/customers${qs ? `?${qs}` : ''}`, { scroll: false });
  }, [debounced, status, page, router]);

  const query = useQuery<Paginated>({
    queryKey: ['admin', 'customers', debounced, status, page],
    queryFn: () =>
      apiFetch<Paginated>('/admin/customers', {
        query: {
          search: debounced || undefined,
          status: status === 'all' ? undefined : status,
          page,
          page_size: 50,
        },
      }),
    placeholderData: (prev) => prev,
  });

  const rows = query.data?.items ?? [];
  const total = query.data?.total ?? 0;
  const pageSize = query.data?.page_size ?? 50;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  function toggleOne(id: string, checked: boolean) {
    setSelected((s) => {
      const n = new Set(s);
      if (checked) n.add(id);
      else n.delete(id);
      return n;
    });
  }

  function toggleAll(checked: boolean) {
    if (checked) setSelected(new Set(rows.map((r) => r.id)));
    else setSelected(new Set());
  }

  const pendingSelected = rows.filter((r) => selected.has(r.id) && !r.approved_at);

  async function bulkApprove() {
    if (!pendingSelected.length) return;
    setBulkBusy(true);
    try {
      const r = await apiFetch<{ approved: string[]; count: number }>(
        '/admin/customers/bulk-approve',
        { method: 'POST', body: pendingSelected.map((p) => p.id) },
      );
      toast.success(`Approved ${r.count} customer${r.count === 1 ? '' : 's'}`);
      setSelected(new Set());
      qc.invalidateQueries({ queryKey: ['admin', 'customers'] });
    } catch (e: any) {
      toast.error(e.message || 'Bulk approve failed');
    } finally {
      setBulkBusy(false);
    }
  }

  function exportCsv() {
    if (!rows.length) return;
    downloadCsv(
      `posuhtik-customers-${new Date().toISOString().slice(0, 10)}.csv`,
      rows.map((r) => ({
        id: r.id,
        name: r.name,
        phone: r.phone,
        area: r.area,
        status: !r.is_active ? 'inactive' : r.approved_at ? 'approved' : 'pending',
        active_subs: r.active_subs_count,
        bottle_balance: r.bottle_balance,
        wallet_rupees: (r.wallet_balance_paise / 100).toFixed(2),
        last_delivery: r.last_delivery_date,
        created_at: r.created_at,
      })),
    );
    toast.success('CSV downloaded');
  }

  function setPage(p: number) {
    const qp = new URLSearchParams(params.toString());
    if (p <= 1) qp.delete('page');
    else qp.set('page', String(p));
    router.replace(`/admin/customers?${qp.toString()}`, { scroll: false });
  }

  function clearFilters() {
    setSearch('');
    setStatus('all');
  }

  return (
    <div className="space-y-5" data-testid="admin-customers-page">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Operations</div>
          <h1 className="font-display text-3xl font-bold tracking-tight mt-1">Customers</h1>
        </div>
        <div className="flex gap-2">
          <Button
            data-testid="customers-export-csv"
            variant="outline"
            size="sm"
            onClick={exportCsv}
            disabled={!rows.length}
            className="gap-2 h-9 text-xs"
          >
            <Download className="w-3.5 h-3.5" /> Export CSV
          </Button>
        </div>
      </header>

      {/* Filters */}
      <div className="flex flex-wrap gap-2 items-center bg-card border border-border/60 rounded-xl p-3">
        <div className="relative flex-1 min-w-[220px]">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input
            data-testid="customers-search"
            placeholder="Search name, phone, email, or address"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 h-9 text-sm"
          />
        </div>
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="h-9 w-[160px] text-sm" data-testid="customers-status-filter">
            <Filter className="w-3.5 h-3.5 mr-1.5" />
            <SelectValue placeholder="All statuses" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="approved">Approved</SelectItem>
            <SelectItem value="pending">Pending</SelectItem>
            <SelectItem value="inactive">Inactive</SelectItem>
          </SelectContent>
        </Select>
        {(search || status !== 'all') && (
          <Button variant="ghost" size="sm" onClick={clearFilters} className="h-9 text-xs gap-1" data-testid="customers-clear-filters">
            <X className="w-3.5 h-3.5" /> Clear
          </Button>
        )}
      </div>

      {/* Bulk action bar */}
      {selected.size > 0 && (
        <div
          data-testid="bulk-action-bar"
          className="flex items-center justify-between gap-3 bg-foreground text-background rounded-xl px-4 py-2.5 text-sm"
        >
          <div>
            <span className="font-semibold">{selected.size}</span> selected ·{' '}
            <span className="text-background/70">{pendingSelected.length} pending</span>
          </div>
          <div className="flex gap-2">
            <Button
              data-testid="bulk-approve-button"
              size="sm"
              variant="default"
              onClick={bulkApprove}
              disabled={!pendingSelected.length || bulkBusy}
              className="h-8 text-xs gap-1.5"
            >
              {bulkBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
              Approve {pendingSelected.length} pending
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())} className="h-8 text-xs text-background hover:bg-white/10">
              Clear
            </Button>
          </div>
        </div>
      )}

      {/* Table */}
      <div className="bg-card border border-border/60 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="customers-table">
            <thead className="bg-muted/40 text-[10px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-3 py-2 w-[36px]">
                  <Checkbox
                    checked={rows.length > 0 && rows.every((r) => selected.has(r.id))}
                    onCheckedChange={(v) => toggleAll(!!v)}
                    data-testid="customers-select-all"
                  />
                </th>
                <th className="text-left px-3 py-2 font-semibold">Name · Phone</th>
                <th className="text-left px-3 py-2 font-semibold">Area</th>
                <th className="text-right px-3 py-2 font-semibold">Active subs</th>
                <th className="text-right px-3 py-2 font-semibold">Bottles</th>
                <th className="text-right px-3 py-2 font-semibold">Wallet</th>
                <th className="text-left px-3 py-2 font-semibold">Last delivery</th>
                <th className="text-left px-3 py-2 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody>
              {query.isLoading && (
                <tr><td colSpan={8} className="px-3 py-16 text-center text-muted-foreground"><Loader2 className="inline w-4 h-4 animate-spin" /> Loading…</td></tr>
              )}
              {!query.isLoading && rows.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-3 py-16 text-center">
                    <div className="text-muted-foreground text-sm flex flex-col items-center gap-2" data-testid="customers-empty-state">
                      <AlertCircle className="w-6 h-6 opacity-40" />
                      <div>No customers match your filters.</div>
                      <Button variant="link" size="sm" onClick={clearFilters}>Clear filters</Button>
                    </div>
                  </td>
                </tr>
              )}
              {rows.map((r) => (
                <tr
                  key={r.id}
                  data-testid={`customer-row-${r.id}`}
                  className="border-t border-border/50 hover:bg-muted/30 cursor-pointer h-[40px]"
                  onClick={() => router.push(`/admin/customers/${r.id}`)}
                >
                  <td className="px-3 py-1.5" onClick={(e) => e.stopPropagation()}>
                    <Checkbox
                      checked={selected.has(r.id)}
                      onCheckedChange={(v) => toggleOne(r.id, !!v)}
                      data-testid={`customer-select-${r.id}`}
                    />
                  </td>
                  <td className="px-3 py-1.5">
                    <div className="font-medium truncate max-w-[220px]">{r.name || '—'}</div>
                    <div className="text-[11px] text-muted-foreground tabular-nums">{r.phone}</div>
                  </td>
                  <td className="px-3 py-1.5 text-muted-foreground">{r.area || '—'}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{r.active_subs_count}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{r.bottle_balance}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{paiseToRupees(r.wallet_balance_paise)}</td>
                  <td className="px-3 py-1.5 text-muted-foreground text-xs">
                    {r.last_delivery_date ? formatDate(r.last_delivery_date) : '—'}
                  </td>
                  <td className="px-3 py-1.5">
                    <StatusBadge row={r} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between">
        <div className="text-xs text-muted-foreground">
          {total > 0 && (
            <>
              Showing <span className="font-semibold text-foreground">{(page - 1) * pageSize + 1}</span>–
              <span className="font-semibold text-foreground">{Math.min(page * pageSize, total)}</span>{' '}
              of <span className="font-semibold text-foreground tabular-nums">{total}</span>
            </>
          )}
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline" size="sm" className="h-8 text-xs"
            onClick={() => setPage(page - 1)}
            disabled={page <= 1}
            data-testid="customers-prev-page"
          >
            Previous
          </Button>
          <div className="flex items-center px-3 text-xs text-muted-foreground tabular-nums" data-testid="customers-page-indicator">
            Page {page} / {totalPages}
          </div>
          <Button
            variant="outline" size="sm" className="h-8 text-xs"
            onClick={() => setPage(page + 1)}
            disabled={page >= totalPages}
            data-testid="customers-next-page"
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}
