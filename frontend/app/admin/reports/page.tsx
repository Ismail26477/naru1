"use client";
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  BarChart3,
  TrendingUp,
  Users,
  Truck,
  Milk,
  Download,
  Loader2,
  Calendar,
  Filter,
  AlertCircle,
  PhoneCall,
  ArrowDown,
  ArrowUp,
} from 'lucide-react';
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Legend,
} from 'recharts';
import { toast } from 'sonner';
import { apiFetch } from '@/lib/api';
import { paiseToRupees, formatDate } from '@/lib/format';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from '@/components/ui/tabs';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

// ---------- types ----------

type RevenueSeriesPoint = {
  period: string;
  revenue_paise: number;
  collected_paise: number;
  invoice_count: number;
};
type RevenueByProduct = {
  product_id: string;
  product_name: string;
  product_sku: string;
  revenue_paise: number;
  quantity_total: number;
};
type RevenueOut = {
  from_date: string;
  to_date: string;
  group_by: string;
  total_revenue_paise: number;
  total_collected_paise: number;
  total_outstanding_paise: number;
  avg_invoice_paise: number;
  invoice_count: number;
  series: RevenueSeriesPoint[];
  by_product: RevenueByProduct[];
};
type ChurnedCustomer = {
  customer_id: string;
  name: string | null;
  phone: string;
  last_delivery_date: string | null;
  days_inactive: number;
  cancelled_at: string | null;
};
type ChurnOut = {
  year: number; month: number;
  active_start: number; active_end: number;
  new_customers: number; churned_customers: number;
  net_change: number;
  churned_list: ChurnedCustomer[];
};
type DailyDeliveryPoint = {
  date: string;
  scheduled: number; delivered: number; skipped: number; failed: number; pending: number;
};
type DeliveryByRoute = {
  route_id: string | null; route_name: string;
  delivered: number; skipped: number; failed: number; total: number;
};
type DeliveryByBoy = {
  delivery_boy_id: string | null; name: string; phone: string;
  delivered: number; skipped: number; failed: number; total: number;
};
type DailyDeliveryOut = {
  from_date: string; to_date: string;
  total_scheduled: number; total_delivered: number;
  total_skipped: number; total_failed: number;
  completion_rate_pct: number;
  series: DailyDeliveryPoint[];
  by_route: DeliveryByRoute[];
  by_delivery_boy: DeliveryByBoy[];
};
type BottleOutCustomer = {
  customer_id: string;
  name: string | null;
  phone: string;
  area: string | null;
  route_name: string | null;
  bottles_out: number;
  last_return_date: string | null;
  days_since_return: number;
  ever_returned: boolean;
};
type BottleOutOut = {
  total_bottles_out: number;
  customers_with_outstanding: number;
  customers_above_5: number;
  oldest_days: number;
  customers: BottleOutCustomer[];
};

// ---------- helpers ----------

function nowIst(): Date {
  return new Date(Date.now() + 5.5 * 60 * 60 * 1000);
}
function istIso(d: Date): string { return d.toISOString().slice(0, 10); }
function monthsAgo(n: number): string {
  const d = nowIst();
  d.setUTCMonth(d.getUTCMonth() - n);
  d.setUTCDate(1);
  return istIso(d);
}
function firstOfCurrentMonth(): string {
  const d = nowIst();
  d.setUTCDate(1);
  return istIso(d);
}
function nowIstYearMonth(): string {
  const d = nowIst();
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
}

function KpiCard({
  label, value, sublabel, testid, tone,
}: {
  label: string;
  value: string | number;
  sublabel?: string;
  testid: string;
  tone?: 'default' | 'primary' | 'accent' | 'destructive' | 'secondary';
}) {
  const toneCls =
    tone === 'primary'
      ? 'bg-primary/5 border-primary/20'
      : tone === 'accent'
        ? 'bg-accent/10 border-accent/30'
        : tone === 'destructive'
          ? 'bg-destructive/10 border-destructive/30'
          : tone === 'secondary'
            ? 'bg-secondary/10 border-secondary/30'
            : 'bg-card border-border/60';
  return (
    <div data-testid={testid} className={`rounded-xl border ${toneCls} p-3`}>
      <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">{label}</div>
      <div className="mt-1 font-display font-bold text-xl tabular-nums">{value}</div>
      {sublabel && <div className="text-[11px] text-muted-foreground mt-0.5">{sublabel}</div>}
    </div>
  );
}

function downloadFromEndpoint(path: string, filename: string) {
  const token = typeof window !== 'undefined' ? localStorage.getItem('posuhtik.access_token') : null;
  if (!token) return;
  const API_BASE =
    (process.env.NEXT_PUBLIC_BACKEND_URL || '').replace(/\/$/, '') + '/api';
  fetch(`${API_BASE}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  }).then(async (r) => {
    if (!r.ok) {
      toast.error(`CSV export failed (${r.status})`);
      return;
    }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast.success('CSV downloaded');
  }).catch((e) => toast.error(e.message || 'CSV export failed'));
}

// ---------- Revenue tab ----------

function RevenueTab() {
  const [fromDate, setFromDate] = useState<string>(monthsAgo(1));
  const [toDate, setToDate] = useState<string>(istIso(nowIst()));
  const [groupBy, setGroupBy] = useState<'day' | 'week' | 'month'>('day');
  const [viewMode, setViewMode] = useState<'issued_date' | 'bill_period'>('issued_date');

  // bill_period mode forces monthly aggregation server-side; reflect that in the UI
  // by disabling the group-by selector in this mode.
  const effectiveGroupBy = viewMode === 'bill_period' ? 'month' : groupBy;

  const q = useQuery<RevenueOut>({
    queryKey: ['admin', 'report', 'revenue', fromDate, toDate, effectiveGroupBy, viewMode],
    queryFn: () =>
      apiFetch<RevenueOut>(`/admin/reports/revenue`, {
        query: { from: fromDate, to: toDate, group_by: effectiveGroupBy, view_mode: viewMode },
      }),
  });

  const data = q.data;
  const chartData = useMemo(
    () =>
      (data?.series ?? []).map((s) => ({
        period: s.period,
        revenue: s.revenue_paise / 100,
        collected: s.collected_paise / 100,
      })),
    [data],
  );

  function exportCsv() {
    downloadFromEndpoint(
      `/admin/reports/revenue/export?from=${fromDate}&to=${toDate}&group_by=${effectiveGroupBy}&view_mode=${viewMode}`,
      `posuhtik_revenue_${viewMode}_${fromDate}_${toDate}.csv`,
    );
  }

  return (
    <div className="space-y-5" data-testid="revenue-tab">
      <div className="flex flex-wrap gap-2 items-end bg-card border border-border/60 rounded-xl p-3">
        <div className="space-y-1">
          <label className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">From</label>
          <Input data-testid="revenue-from" type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} className="h-9 text-sm" />
        </div>
        <div className="space-y-1">
          <label className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">To</label>
          <Input data-testid="revenue-to" type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} min={fromDate} className="h-9 text-sm" />
        </div>
        <div className="space-y-1">
          <label className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Group by</label>
          <Select
            value={effectiveGroupBy}
            onValueChange={(v: any) => setGroupBy(v)}
            disabled={viewMode === 'bill_period'}
          >
            <SelectTrigger className="h-9 w-[110px] text-sm" data-testid="revenue-groupby"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="day">Day</SelectItem>
              <SelectItem value="week">Week</SelectItem>
              <SelectItem value="month">Month</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="flex-1" />
        <Button data-testid="revenue-export" onClick={exportCsv} variant="outline" size="sm" className="h-9 text-xs gap-2" disabled={!data}>
          <Download className="w-3.5 h-3.5" /> Export CSV
        </Button>
      </div>

      {/* View mode toggle — lines below explain the two counting frames. */}
      <div
        className="flex items-start justify-between gap-3 bg-card border border-border/60 rounded-xl p-3 flex-wrap"
        data-testid="revenue-view-mode-toggle-group"
      >
        <div className="flex items-center gap-1 rounded-lg bg-muted/40 p-1 border border-border/60">
          <button
            type="button"
            data-testid="revenue-view-mode-issued"
            onClick={() => setViewMode('issued_date')}
            className={`h-7 px-3 rounded-md text-[11px] font-semibold uppercase tracking-wider transition ${
              viewMode === 'issued_date'
                ? 'bg-background shadow-sm text-foreground'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            Issued date
          </button>
          <button
            type="button"
            data-testid="revenue-view-mode-billperiod"
            onClick={() => setViewMode('bill_period')}
            className={`h-7 px-3 rounded-md text-[11px] font-semibold uppercase tracking-wider transition ${
              viewMode === 'bill_period'
                ? 'bg-background shadow-sm text-foreground'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            Bill period
          </button>
        </div>
        <p className="text-[11px] text-muted-foreground max-w-xl leading-relaxed">
          {viewMode === 'issued_date'
            ? 'Counts invoices by the day they were issued. Use for cash-flow and collection trend analysis.'
            : 'Counts invoices by the month they bill for (year/month). Use for service-period revenue recognition. Aggregation is monthly in this mode.'}
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <KpiCard label="Total revenue" value={paiseToRupees(data?.total_revenue_paise ?? 0)} testid="kpi-rev-total" tone="primary" />
        <KpiCard label="Collected" value={paiseToRupees(data?.total_collected_paise ?? 0)} testid="kpi-rev-collected" tone="secondary" />
        <KpiCard label="Outstanding" value={paiseToRupees(data?.total_outstanding_paise ?? 0)} testid="kpi-rev-outstanding" tone={(data?.total_outstanding_paise ?? 0) > 0 ? 'destructive' : 'default'} />
        <KpiCard label="Avg invoice" value={paiseToRupees(data?.avg_invoice_paise ?? 0)} testid="kpi-rev-avg" />
        <KpiCard label="Invoices" value={data?.invoice_count ?? 0} testid="kpi-rev-count" />
      </div>

      <div className="rounded-2xl border border-border/60 bg-card p-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-display text-lg font-semibold flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-muted-foreground" /> Revenue over time
          </h3>
          <Badge variant="outline" className="text-[10px] uppercase tracking-wider">
            {chartData.length} {effectiveGroupBy}{chartData.length === 1 ? '' : 's'} · {viewMode === 'issued_date' ? 'issued' : 'bill period'}
          </Badge>
        </div>
        {q.isLoading && <div className="h-[260px] flex items-center justify-center"><Loader2 className="w-5 h-5 animate-spin text-muted-foreground" /></div>}
        {!q.isLoading && (
          <ResponsiveContainer width="100%" height={260} data-testid="revenue-chart">
            <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.3} />
              <XAxis dataKey="period" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `₹${v.toLocaleString()}`} width={70} />
              <Tooltip
                formatter={(v: any, name: string) => [`₹${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, name === 'revenue' ? 'Revenue' : 'Collected']}
                contentStyle={{ fontSize: 12, borderRadius: 8 }}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line type="monotone" dataKey="revenue" stroke="hsl(var(--primary))" strokeWidth={2} dot={{ r: 3 }} />
              <Line type="monotone" dataKey="collected" stroke="hsl(var(--secondary))" strokeWidth={2} dot={{ r: 3 }} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="rounded-2xl border border-border/60 bg-card">
        <div className="p-5 border-b border-border/60">
          <h3 className="font-display text-lg font-semibold">By product</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="revenue-by-product-table">
            <thead className="bg-muted/40 text-[10px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="text-left px-4 py-2 font-semibold">Product</th>
                <th className="text-left px-4 py-2 font-semibold">SKU</th>
                <th className="text-right px-4 py-2 font-semibold">Qty delivered</th>
                <th className="text-right px-4 py-2 font-semibold">Revenue</th>
                <th className="text-right px-4 py-2 font-semibold">Share</th>
              </tr>
            </thead>
            <tbody>
              {(data?.by_product ?? []).length === 0 && (
                <tr><td colSpan={5} className="px-4 py-10 text-center text-muted-foreground text-sm">No product revenue in this period.</td></tr>
              )}
              {(data?.by_product ?? []).map((p) => {
                const pct = data && data.total_revenue_paise ? (p.revenue_paise / data.total_revenue_paise) * 100 : 0;
                return (
                  <tr key={p.product_id} data-testid={`rev-prod-row-${p.product_id}`} className="border-t border-border/50 h-[40px]">
                    <td className="px-4 py-1.5 font-medium">{p.product_name}</td>
                    <td className="px-4 py-1.5"><span className="font-mono text-[10px] bg-muted/50 px-1.5 py-0.5 rounded">{p.product_sku}</span></td>
                    <td className="px-4 py-1.5 text-right tabular-nums">{p.quantity_total}</td>
                    <td className="px-4 py-1.5 text-right tabular-nums font-semibold">{paiseToRupees(p.revenue_paise)}</td>
                    <td className="px-4 py-1.5 text-right tabular-nums text-muted-foreground">{pct.toFixed(1)}%</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ---------- Churn tab ----------

function ChurnTab() {
  const [month, setMonth] = useState<string>(nowIstYearMonth());
  const q = useQuery<ChurnOut>({
    queryKey: ['admin', 'report', 'churn', month],
    queryFn: () => apiFetch<ChurnOut>(`/admin/reports/churn`, { query: { month } }),
  });
  const data = q.data;
  const net = data?.net_change ?? 0;

  function exportCsv() {
    downloadFromEndpoint(`/admin/reports/churn/export?month=${month}`, `posuhtik_churn_${month}.csv`);
  }

  return (
    <div className="space-y-5" data-testid="churn-tab">
      <div className="flex flex-wrap gap-2 items-end bg-card border border-border/60 rounded-xl p-3">
        <div className="space-y-1">
          <label className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Month</label>
          <Input data-testid="churn-month" type="month" value={month} onChange={(e) => setMonth(e.target.value)} className="h-9 text-sm w-[160px]" />
        </div>
        <div className="flex-1" />
        <Button data-testid="churn-export" onClick={exportCsv} variant="outline" size="sm" className="h-9 text-xs gap-2" disabled={!data}>
          <Download className="w-3.5 h-3.5" /> Export CSV
        </Button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="Active at start" value={data?.active_start ?? 0} testid="kpi-churn-start" />
        <KpiCard label="New" value={`+${data?.new_customers ?? 0}`} testid="kpi-churn-new" tone="secondary" />
        <KpiCard label="Churned" value={`-${data?.churned_customers ?? 0}`} testid="kpi-churn-churned" tone="destructive" />
        <KpiCard
          label="Net change"
          value={
            <span className="flex items-center gap-1.5">
              {net >= 0 ? <ArrowUp className="w-4 h-4 text-secondary" /> : <ArrowDown className="w-4 h-4 text-destructive" />}
              {net >= 0 ? '+' : ''}{net}
            </span> as any
          }
          testid="kpi-churn-net"
          tone={net >= 0 ? 'primary' : 'accent'}
        />
      </div>

      <div className="rounded-2xl border border-border/60 bg-card">
        <div className="p-5 border-b border-border/60">
          <h3 className="font-display text-lg font-semibold flex items-center gap-2">
            <Users className="w-4 h-4 text-muted-foreground" /> Churned customers
          </h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="churned-table">
            <thead className="bg-muted/40 text-[10px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="text-left px-4 py-2 font-semibold">Customer</th>
                <th className="text-left px-4 py-2 font-semibold">Last delivery</th>
                <th className="text-right px-4 py-2 font-semibold">Days inactive</th>
                <th className="text-left px-4 py-2 font-semibold">Cancelled at</th>
              </tr>
            </thead>
            <tbody>
              {(data?.churned_list ?? []).length === 0 && (
                <tr><td colSpan={4} className="px-4 py-10 text-center text-muted-foreground text-sm" data-testid="churn-empty">No churn this month. 🎉</td></tr>
              )}
              {(data?.churned_list ?? []).map((c) => (
                <tr key={c.customer_id} data-testid={`churn-row-${c.customer_id}`} className="border-t border-border/50 h-[40px]">
                  <td className="px-4 py-1.5">
                    <div className="font-medium">{c.name || '—'}</div>
                    <div className="text-[11px] text-muted-foreground tabular-nums">{c.phone}</div>
                  </td>
                  <td className="px-4 py-1.5 text-muted-foreground text-xs">{c.last_delivery_date ? formatDate(c.last_delivery_date) : '—'}</td>
                  <td className="px-4 py-1.5 text-right tabular-nums">{c.days_inactive >= 0 ? c.days_inactive : '—'}</td>
                  <td className="px-4 py-1.5 text-muted-foreground text-xs">{c.cancelled_at ? formatDate(c.cancelled_at) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ---------- Daily delivery tab ----------

function DailyDeliveryTab() {
  const [fromDate, setFromDate] = useState<string>(istIso(new Date(Date.now() + 5.5 * 60 * 60 * 1000 - 13 * 86_400_000)));
  const [toDate, setToDate] = useState<string>(istIso(nowIst()));
  const q = useQuery<DailyDeliveryOut>({
    queryKey: ['admin', 'report', 'delivery', fromDate, toDate],
    queryFn: () =>
      apiFetch<DailyDeliveryOut>(`/admin/reports/daily-delivery`, { query: { from: fromDate, to: toDate } }),
  });
  const data = q.data;
  const chartData = useMemo(
    () =>
      (data?.series ?? []).map((s) => ({
        date: s.date,
        Delivered: s.delivered,
        Skipped: s.skipped,
        Failed: s.failed,
        Pending: s.pending,
      })),
    [data],
  );

  function exportCsv() {
    downloadFromEndpoint(
      `/admin/reports/daily-delivery/export?from=${fromDate}&to=${toDate}`,
      `posuhtik_delivery_${fromDate}_${toDate}.csv`,
    );
  }

  return (
    <div className="space-y-5" data-testid="delivery-tab">
      <div className="flex flex-wrap gap-2 items-end bg-card border border-border/60 rounded-xl p-3">
        <div className="space-y-1">
          <label className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">From</label>
          <Input data-testid="delivery-from" type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} className="h-9 text-sm" />
        </div>
        <div className="space-y-1">
          <label className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">To</label>
          <Input data-testid="delivery-to" type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} min={fromDate} className="h-9 text-sm" />
        </div>
        <div className="flex-1" />
        <Button data-testid="delivery-export" onClick={exportCsv} variant="outline" size="sm" className="h-9 text-xs gap-2" disabled={!data}>
          <Download className="w-3.5 h-3.5" /> Export CSV
        </Button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <KpiCard label="Scheduled" value={data?.total_scheduled ?? 0} testid="kpi-del-scheduled" />
        <KpiCard label="Delivered" value={data?.total_delivered ?? 0} testid="kpi-del-delivered" tone="secondary" />
        <KpiCard label="Skipped" value={data?.total_skipped ?? 0} testid="kpi-del-skipped" tone="accent" />
        <KpiCard label="Failed" value={data?.total_failed ?? 0} testid="kpi-del-failed" tone={(data?.total_failed ?? 0) > 0 ? 'destructive' : 'default'} />
        <KpiCard label="Completion" value={`${(data?.completion_rate_pct ?? 0).toFixed(1)}%`} testid="kpi-del-completion" tone="primary" />
      </div>

      <div className="rounded-2xl border border-border/60 bg-card p-5">
        <h3 className="font-display text-lg font-semibold flex items-center gap-2 mb-3">
          <Truck className="w-4 h-4 text-muted-foreground" /> Daily breakdown
        </h3>
        {q.isLoading && <div className="h-[260px] flex items-center justify-center"><Loader2 className="w-5 h-5 animate-spin" /></div>}
        {!q.isLoading && (
          <ResponsiveContainer width="100%" height={260} data-testid="delivery-chart">
            <BarChart data={chartData} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.3} />
              <XAxis dataKey="date" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey="Delivered" stackId="a" fill="hsl(var(--secondary))" />
              <Bar dataKey="Skipped" stackId="a" fill="hsl(var(--accent))" />
              <Bar dataKey="Failed" stackId="a" fill="hsl(var(--destructive))" />
              <Bar dataKey="Pending" stackId="a" fill="hsl(var(--muted-foreground))" />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="rounded-2xl border border-border/60 bg-card">
          <div className="p-4 border-b border-border/60"><h4 className="font-display text-sm font-semibold">By route</h4></div>
          <table className="w-full text-sm" data-testid="delivery-by-route-table">
            <thead className="bg-muted/40 text-[10px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="text-left px-3 py-2 font-semibold">Route</th>
                <th className="text-right px-3 py-2 font-semibold">Del</th>
                <th className="text-right px-3 py-2 font-semibold">Skip</th>
                <th className="text-right px-3 py-2 font-semibold">Fail</th>
                <th className="text-right px-3 py-2 font-semibold">Total</th>
              </tr>
            </thead>
            <tbody>
              {(data?.by_route ?? []).length === 0 && (
                <tr><td colSpan={5} className="px-3 py-6 text-center text-muted-foreground text-xs">—</td></tr>
              )}
              {(data?.by_route ?? []).map((r, i) => (
                <tr key={r.route_id || `u-${i}`} className="border-t border-border/50 h-[36px]">
                  <td className="px-3 py-1.5 font-medium truncate max-w-[180px]">{r.route_name}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{r.delivered}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{r.skipped}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{r.failed}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums font-semibold">{r.total}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="rounded-2xl border border-border/60 bg-card">
          <div className="p-4 border-b border-border/60"><h4 className="font-display text-sm font-semibold">By delivery boy</h4></div>
          <table className="w-full text-sm" data-testid="delivery-by-boy-table">
            <thead className="bg-muted/40 text-[10px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="text-left px-3 py-2 font-semibold">Name</th>
                <th className="text-right px-3 py-2 font-semibold">Del</th>
                <th className="text-right px-3 py-2 font-semibold">Skip</th>
                <th className="text-right px-3 py-2 font-semibold">Fail</th>
                <th className="text-right px-3 py-2 font-semibold">Total</th>
              </tr>
            </thead>
            <tbody>
              {(data?.by_delivery_boy ?? []).length === 0 && (
                <tr><td colSpan={5} className="px-3 py-6 text-center text-muted-foreground text-xs">—</td></tr>
              )}
              {(data?.by_delivery_boy ?? []).map((b, i) => (
                <tr key={b.delivery_boy_id || `u-${i}`} className="border-t border-border/50 h-[36px]">
                  <td className="px-3 py-1.5 font-medium truncate max-w-[180px]">{b.name}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{b.delivered}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{b.skipped}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{b.failed}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums font-semibold">{b.total}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ---------- Bottle outstanding tab ----------

function BottleOutstandingTab() {
  const q = useQuery<BottleOutOut>({
    queryKey: ['admin', 'report', 'bottles'],
    queryFn: () => apiFetch<BottleOutOut>(`/admin/reports/bottle-outstanding`),
  });
  const data = q.data;

  function exportCsv() {
    downloadFromEndpoint(`/admin/reports/bottle-outstanding/export`, `posuhtik_bottles_outstanding.csv`);
  }

  return (
    <div className="space-y-5" data-testid="bottles-tab">
      <div className="flex justify-end">
        <Button data-testid="bottles-export" onClick={exportCsv} variant="outline" size="sm" className="h-9 text-xs gap-2" disabled={!data}>
          <Download className="w-3.5 h-3.5" /> Export CSV
        </Button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="Bottles out" value={data?.total_bottles_out ?? 0} testid="kpi-bot-total" tone="accent" />
        <KpiCard label="Customers" value={data?.customers_with_outstanding ?? 0} testid="kpi-bot-customers" />
        <KpiCard label="Holding > 5" value={data?.customers_above_5 ?? 0} testid="kpi-bot-above5" tone={(data?.customers_above_5 ?? 0) > 0 ? 'destructive' : 'default'} />
        <KpiCard label="Oldest" value={`${data?.oldest_days ?? 0}d`} testid="kpi-bot-oldest" />
      </div>

      <div className="rounded-2xl border border-border/60 bg-card">
        <div className="p-5 border-b border-border/60">
          <h3 className="font-display text-lg font-semibold flex items-center gap-2">
            <Milk className="w-4 h-4 text-muted-foreground" /> Outstanding bottles by customer
          </h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            Sorted by bottles-out DESC, then days-since-return DESC.
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="bottles-table">
            <thead className="bg-muted/40 text-[10px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="text-left px-4 py-2 font-semibold">Customer</th>
                <th className="text-left px-4 py-2 font-semibold">Area</th>
                <th className="text-left px-4 py-2 font-semibold">Route</th>
                <th className="text-right px-4 py-2 font-semibold">Bottles</th>
                <th className="text-left px-4 py-2 font-semibold">Last return</th>
                <th className="text-right px-4 py-2 font-semibold">Days since</th>
              </tr>
            </thead>
            <tbody>
              {q.isLoading && (
                <tr><td colSpan={6} className="px-4 py-10 text-center text-muted-foreground"><Loader2 className="inline w-4 h-4 animate-spin" /> Loading…</td></tr>
              )}
              {!q.isLoading && (data?.customers ?? []).length === 0 && (
                <tr><td colSpan={6} className="px-4 py-10 text-center text-muted-foreground text-sm" data-testid="bottles-empty">All bottles returned. 🫙</td></tr>
              )}
              {(data?.customers ?? []).map((c) => (
                <tr key={c.customer_id} data-testid={`bottles-row-${c.customer_id}`} className="border-t border-border/50 h-[40px]">
                  <td className="px-4 py-1.5">
                    <div className="font-medium">{c.name || '—'}</div>
                    <div className="text-[11px] text-muted-foreground tabular-nums flex items-center gap-1">
                      <PhoneCall className="w-2.5 h-2.5" /> {c.phone}
                    </div>
                  </td>
                  <td className="px-4 py-1.5 text-muted-foreground text-xs">{c.area || '—'}</td>
                  <td className="px-4 py-1.5 text-muted-foreground text-xs">{c.route_name || '(no route)'}</td>
                  <td className="px-4 py-1.5 text-right tabular-nums font-bold">{c.bottles_out}</td>
                  <td className="px-4 py-1.5 text-muted-foreground text-xs">
                    {c.ever_returned ? (c.last_return_date ? formatDate(c.last_return_date) : '—') : <span className="italic">Never</span>}
                  </td>
                  <td className="px-4 py-1.5 text-right tabular-nums">
                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${c.days_since_return > 30 ? 'bg-destructive/10 text-destructive' : c.days_since_return > 14 ? 'bg-accent/10 text-accent' : 'bg-muted/50 text-muted-foreground'}`}>
                      {c.days_since_return}d
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ---------- Page ----------

export default function AdminReportsPage() {
  return (
    <div className="space-y-6" data-testid="admin-reports-page">
      <header>
        <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
          Analytics
        </div>
        <h1 className="font-display text-3xl font-bold tracking-tight mt-1">Reports</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Revenue, churn, delivery ops and bottle-return health. CSV exports stream from the backend with UTF-8 BOM for Excel compatibility.
        </p>
      </header>
      <Tabs defaultValue="revenue" className="space-y-4">
        <TabsList data-testid="reports-tabs">
          <TabsTrigger value="revenue" data-testid="reports-tab-revenue" className="gap-1.5"><TrendingUp className="w-3.5 h-3.5" /> Revenue</TabsTrigger>
          <TabsTrigger value="churn" data-testid="reports-tab-churn" className="gap-1.5"><Users className="w-3.5 h-3.5" /> Churn</TabsTrigger>
          <TabsTrigger value="delivery" data-testid="reports-tab-delivery" className="gap-1.5"><Truck className="w-3.5 h-3.5" /> Deliveries</TabsTrigger>
          <TabsTrigger value="bottles" data-testid="reports-tab-bottles" className="gap-1.5"><Milk className="w-3.5 h-3.5" /> Bottles</TabsTrigger>
        </TabsList>
        <TabsContent value="revenue"><RevenueTab /></TabsContent>
        <TabsContent value="churn"><ChurnTab /></TabsContent>
        <TabsContent value="delivery"><DailyDeliveryTab /></TabsContent>
        <TabsContent value="bottles"><BottleOutstandingTab /></TabsContent>
      </Tabs>
    </div>
  );
}
