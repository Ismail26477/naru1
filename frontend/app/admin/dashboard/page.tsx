"use client";
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  CartesianGrid,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  Truck,
  Wallet,
  UserPlus,
  AlertCircle,
  RotateCw,
  FileWarning,
  Activity,
  Loader2,
  PlayCircle,
} from 'lucide-react';
import { toast } from 'sonner';
import { apiFetch } from '@/lib/api';
import { paiseToRupees } from '@/lib/format';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';

type TrendPoint = { date: string; value: number };
type Stats = {
  today_deliveries: number;
  mtd_revenue_paise: number;
  new_customers_mtd: number;
  pending_approvals: number;
  bottles_outstanding: number;
  overdue_invoices: number;
  active_subscriptions: number;
  deliveries_trend_14d: TrendPoint[];
  revenue_trend_30d: TrendPoint[];
  signups_trend_30d: TrendPoint[];
  generated_at: string;
};

const CHART_TAB_KEY = 'posuhtik.admin.dashboard.tab';

function KpiCard({
  testid,
  label,
  value,
  icon: Icon,
  tone,
  hint,
}: {
  testid: string;
  label: string;
  value: string;
  icon: React.ComponentType<{ className?: string }>;
  tone: 'primary' | 'secondary' | 'accent' | 'neutral';
  hint?: string;
}) {
  const toneClass = {
    primary: 'bg-primary/10 text-primary border-primary/20',
    secondary: 'bg-secondary/10 text-secondary border-secondary/20',
    accent: 'bg-accent/10 text-accent border-accent/20',
    neutral: 'bg-muted text-muted-foreground border-border',
  }[tone];
  return (
    <div
      data-testid={testid}
      className="bg-card rounded-xl p-4 border border-border/60 flex flex-col justify-between min-h-[96px]"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider leading-tight">
          {label}
        </div>
        <div className={`w-7 h-7 rounded-lg border flex items-center justify-center ${toneClass}`}>
          <Icon className="w-3.5 h-3.5" />
        </div>
      </div>
      <div className="mt-3">
        <div className="font-display text-2xl font-bold tabular-nums leading-none">{value}</div>
        {hint && <div className="text-[10px] text-muted-foreground mt-1">{hint}</div>}
      </div>
    </div>
  );
}

function TrendChart({
  data,
  label,
  formatter,
  color,
  testid,
}: {
  data: TrendPoint[];
  label: string;
  formatter: (n: number) => string;
  color: string;
  testid: string;
}) {
  const formatted = data.map((p) => ({
    date: new Date(p.date).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' }),
    value: p.value,
  }));
  return (
    <div data-testid={testid} className="h-[280px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={formatted} margin={{ top: 10, right: 12, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id={`grad-${testid}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.35} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }}
            axisLine={false}
            tickLine={false}
            interval="preserveStartEnd"
            minTickGap={24}
          />
          <YAxis
            tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }}
            axisLine={false}
            tickLine={false}
            width={52}
            tickFormatter={(v: number) => formatter(v)}
          />
          <Tooltip
            contentStyle={{
              background: 'hsl(var(--card))',
              border: '1px solid hsl(var(--border))',
              borderRadius: 8,
              fontSize: 12,
            }}
            formatter={(v: number) => [formatter(v), label]}
          />
          <Area
            type="monotone"
            dataKey="value"
            stroke={color}
            strokeWidth={2}
            fill={`url(#grad-${testid})`}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function ManualJobButton({
  job,
  label,
  onDone,
}: {
  job: 'nightly_cutoff' | 'monthly_billing' | 'morning_reminder';
  label: string;
  onDone: () => void;
}) {
  const [busy, setBusy] = useState(false);
  async function run() {
    setBusy(true);
    try {
      const r = await apiFetch<{ job: string; affected: number }>(
        `/admin/jobs/${job}/trigger`,
        { method: 'POST' },
      );
      toast.success(`${label} complete`, { description: `${r.affected} records affected.` });
      onDone();
    } catch (e: any) {
      toast.error(e.message || 'Job failed');
    } finally {
      setBusy(false);
    }
  }
  return (
    <Button
      data-testid={`admin-job-${job}`}
      variant="outline"
      size="sm"
      onClick={run}
      disabled={busy}
      className="justify-start gap-2 h-9 text-xs font-medium"
    >
      {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <PlayCircle className="w-3.5 h-3.5" />}
      {label}
    </Button>
  );
}

export default function AdminDashboardPage() {
  const [tab, setTab] = useState<'deliveries' | 'revenue' | 'signups'>('deliveries');

  useEffect(() => {
    const saved = typeof window !== 'undefined' ? localStorage.getItem(CHART_TAB_KEY) : null;
    if (saved === 'deliveries' || saved === 'revenue' || saved === 'signups') setTab(saved);
  }, []);

  useEffect(() => {
    if (typeof window !== 'undefined') localStorage.setItem(CHART_TAB_KEY, tab);
  }, [tab]);

  const q = useQuery<Stats>({
    queryKey: ['admin', 'dashboard', 'stats'],
    queryFn: () => apiFetch<Stats>('/admin/dashboard/stats'),
    staleTime: 30_000,
  });

  const s = q.data;

  return (
    <div className="space-y-6" data-testid="admin-dashboard-page">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
            Operations
          </div>
          <h1 className="font-display text-3xl font-bold tracking-tight mt-1">Dashboard</h1>
        </div>
        <div className="flex items-center gap-2">
          <Button
            data-testid="admin-dashboard-refresh"
            variant="outline"
            size="sm"
            onClick={() => q.refetch()}
            disabled={q.isFetching}
            className="gap-2 h-9 text-xs"
          >
            {q.isFetching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RotateCw className="w-3.5 h-3.5" />}
            Refresh
          </Button>
        </div>
      </header>

      {/* KPI cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <KpiCard
          testid="kpi-today-deliveries"
          label="Today deliveries"
          value={String(s?.today_deliveries ?? '—')}
          icon={Truck}
          tone="primary"
          hint="scheduled for today"
        />
        <KpiCard
          testid="kpi-mtd-revenue"
          label="MTD revenue"
          value={s ? paiseToRupees(s.mtd_revenue_paise) : '—'}
          icon={Wallet}
          tone="secondary"
          hint="delivered × price"
        />
        <KpiCard
          testid="kpi-new-customers"
          label="New customers"
          value={String(s?.new_customers_mtd ?? '—')}
          icon={UserPlus}
          tone="primary"
          hint="month to date"
        />
        <KpiCard
          testid="kpi-pending-approvals"
          label="Pending approvals"
          value={String(s?.pending_approvals ?? '—')}
          icon={AlertCircle}
          tone={s && s.pending_approvals > 0 ? 'accent' : 'neutral'}
          hint="awaiting review"
        />
        <KpiCard
          testid="kpi-bottles-outstanding"
          label="Bottles out"
          value={String(s?.bottles_outstanding ?? '—')}
          icon={Activity}
          tone="neutral"
          hint="with customers"
        />
        <KpiCard
          testid="kpi-overdue-invoices"
          label="Overdue invoices"
          value={String(s?.overdue_invoices ?? '—')}
          icon={FileWarning}
          tone={s && s.overdue_invoices > 0 ? 'accent' : 'neutral'}
          hint="past due date"
        />
      </div>

      {/* Chart card */}
      <section className="bg-card rounded-xl border border-border/60 p-4 md:p-6">
        <Tabs value={tab} onValueChange={(v) => setTab(v as any)} data-testid="admin-dashboard-chart-tabs">
          <div className="flex items-center justify-between gap-4 flex-wrap mb-4">
            <TabsList className="bg-muted h-9">
              <TabsTrigger value="deliveries" data-testid="tab-deliveries" className="text-xs">
                Deliveries · 14d
              </TabsTrigger>
              <TabsTrigger value="revenue" data-testid="tab-revenue" className="text-xs">
                Revenue · 30d
              </TabsTrigger>
              <TabsTrigger value="signups" data-testid="tab-signups" className="text-xs">
                New customers · 30d
              </TabsTrigger>
            </TabsList>
            <div className="text-[11px] text-muted-foreground">
              Active subs: <span className="font-semibold text-foreground tabular-nums">{s?.active_subscriptions ?? '—'}</span>
            </div>
          </div>

          <TabsContent value="deliveries" className="mt-0">
            {q.isLoading ? (
              <div className="h-[280px] flex items-center justify-center text-muted-foreground text-sm">
                <Loader2 className="w-4 h-4 animate-spin mr-2" /> Loading…
              </div>
            ) : (
              <TrendChart
                testid="chart-deliveries"
                data={s?.deliveries_trend_14d ?? []}
                label="Orders"
                formatter={(n) => String(n)}
                color="hsl(var(--primary))"
              />
            )}
          </TabsContent>
          <TabsContent value="revenue" className="mt-0">
            {q.isLoading ? (
              <div className="h-[280px] flex items-center justify-center text-muted-foreground text-sm">
                <Loader2 className="w-4 h-4 animate-spin mr-2" /> Loading…
              </div>
            ) : (
              <TrendChart
                testid="chart-revenue"
                data={s?.revenue_trend_30d ?? []}
                label="Revenue"
                formatter={(n) => paiseToRupees(n)}
                color="hsl(var(--secondary))"
              />
            )}
          </TabsContent>
          <TabsContent value="signups" className="mt-0">
            {q.isLoading ? (
              <div className="h-[280px] flex items-center justify-center text-muted-foreground text-sm">
                <Loader2 className="w-4 h-4 animate-spin mr-2" /> Loading…
              </div>
            ) : (
              <TrendChart
                testid="chart-signups"
                data={s?.signups_trend_30d ?? []}
                label="Signups"
                formatter={(n) => String(n)}
                color="hsl(var(--accent))"
              />
            )}
          </TabsContent>
        </Tabs>
      </section>

      {/* Manual jobs */}
      <section className="bg-card rounded-xl border border-border/60 p-4 md:p-6">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="font-display text-base font-semibold">Manual triggers</h2>
            <p className="text-xs text-muted-foreground mt-0.5">Cron jobs also run automatically via APScheduler.</p>
          </div>
          <Link
            href="/admin/audit-log"
            className="text-xs text-primary font-semibold hover:underline"
            data-testid="link-audit-log"
          >
            View audit log →
          </Link>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          <ManualJobButton job="nightly_cutoff" label="Nightly cutoff (8 PM)" onDone={() => q.refetch()} />
          <ManualJobButton job="monthly_billing" label="Monthly billing" onDone={() => q.refetch()} />
          <ManualJobButton job="morning_reminder" label="Morning reminders" onDone={() => q.refetch()} />
        </div>
      </section>
    </div>
  );
}
