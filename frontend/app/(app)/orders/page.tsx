"use client";
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api';
import { formatDate } from '@/lib/format';
import { todayIstYmd, addDaysYmd } from '@/lib/cutoff';
import { Badge } from '@/components/ui/badge';
import { RowSkeleton } from '@/components/skeletons';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';

const STATUS_COLOR: Record<string, string> = {
  delivered: 'bg-secondary/15 text-secondary-foreground border-secondary/30',
  pending: 'bg-primary/10 text-primary border-primary/30',
  skipped: 'bg-muted text-muted-foreground border-border',
  failed: 'bg-accent/10 text-accent border-accent/30',
};

export default function OrdersPage() {
  const [tab, setTab] = useState<'upcoming' | 'history'>('upcoming');
  const today = todayIstYmd();
  const upcomingQ = useQuery({
    queryKey: ['orders', 'up', today],
    queryFn: () => apiFetch<any[]>('/me/delivery-orders', { query: { from: today, to: addDaysYmd(today, 30) } }),
  });
  const historyQ = useQuery({
    queryKey: ['orders', 'hist', today],
    queryFn: () => apiFetch<any[]>('/me/delivery-orders', { query: { from: addDaysYmd(today, -60), to: addDaysYmd(today, -1) } }),
  });
  const products = useQuery({ queryKey: ['products'], queryFn: () => apiFetch<any[]>('/products') });
  const prodMap = new Map((products.data || []).map((p) => [p.id, p]));

  const list = tab === 'upcoming'
    ? (upcomingQ.data || [])
    : (historyQ.data || []);

  return (
    <div className="p-5 pb-4 animate-fade-in">
      <header className="mb-4">
        <div className="text-xs text-muted-foreground uppercase tracking-widest">Deliveries</div>
        <h1 className="text-3xl font-display font-bold tracking-tight mt-0.5">My orders</h1>
      </header>

      <Tabs value={tab} onValueChange={(v: any) => setTab(v)} className="mb-4">
        <div className="w-full rounded-full bg-muted p-1 flex">
          <TabsTrigger value="upcoming" className="flex-1 rounded-full" data-testid="orders-upcoming-tab">Upcoming</TabsTrigger>
          <TabsTrigger value="history" className="flex-1 rounded-full" data-testid="orders-history-tab">History</TabsTrigger>
        </div>
      </Tabs>

      {(tab === 'upcoming' ? upcomingQ.isLoading : historyQ.isLoading) && (
        <div className="space-y-2"><RowSkeleton /><RowSkeleton /><RowSkeleton /></div>
      )}

      <div className="space-y-2">
        {list.map((o: any) => {
          const p = prodMap.get(o.product_id);
          return (
            <div
              key={o.id}
              data-testid={`order-row-${o.id}`}
              className="flex items-center gap-3 p-3 bg-card rounded-2xl border border-border/40"
            >
              <div className="w-14 h-14 rounded-xl bg-muted flex flex-col items-center justify-center text-xs text-muted-foreground font-display">
                <span className="text-[10px] uppercase">{formatDate(o.delivery_date, 'MMM')}</span>
                <span className="font-bold text-lg text-foreground -mt-0.5">{formatDate(o.delivery_date, 'd')}</span>
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-semibold truncate">{p?.name || 'Product'}</div>
                <div className="text-xs text-muted-foreground">
                  Qty {o.delivered_quantity ?? o.quantity}
                  {o.skip_reason && <span className="italic"> · {o.skip_reason}</span>}
                </div>
              </div>
              <Badge className={`rounded-full border capitalize ${STATUS_COLOR[o.status] || ''}`}>
                {o.status}
              </Badge>
            </div>
          );
        })}
        {!list.length && !(tab === 'upcoming' ? upcomingQ.isLoading : historyQ.isLoading) && (
          <div className="text-center py-10 text-muted-foreground text-sm">No orders in this period.</div>
        )}
      </div>
    </div>
  );
}
