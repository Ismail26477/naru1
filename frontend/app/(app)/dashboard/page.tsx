"use client";
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { Milk, Wallet, Receipt, Package, ChevronRight, Leaf } from 'lucide-react';
import { apiFetch, auth } from '@/lib/api';
import { paiseToRupees, FREQUENCY_LABEL } from '@/lib/format';
import { todayIstYmd, addDaysYmd } from '@/lib/cutoff';
import { Badge } from '@/components/ui/badge';
import { CardSkeleton, RowSkeleton } from '@/components/skeletons';
import CutoffTimer from '@/components/cutoff-timer';

export default function DashboardPage() {
  const user = auth.getUser();
  const me = useQuery({ queryKey: ['me'], queryFn: () => apiFetch('/me') });
  const bottle = useQuery({ queryKey: ['bottle'], queryFn: () => apiFetch<{ balance: number }>('/me/bottle-balance') });
  const wallet = useQuery({ queryKey: ['wallet'], queryFn: () => apiFetch<{ balance_paise: number }>('/me/wallet') });
  const subs = useQuery({ queryKey: ['subs'], queryFn: () => apiFetch<any[]>('/me/subscriptions') });
  const today = todayIstYmd();
  const from = today;
  const to = addDaysYmd(today, 3);
  const upcoming = useQuery({
    queryKey: ['orders', from, to],
    queryFn: () => apiFetch<any[]>('/me/delivery-orders', { query: { from, to } }),
  });
  const products = useQuery({ queryKey: ['products'], queryFn: () => apiFetch<any[]>('/products') });
  const prodMap = new Map((products.data || []).map((p) => [p.id, p]));

  return (
    <div className="p-5 pb-4 space-y-6 animate-fade-in">
      <header className="flex items-center justify-between">
        <div>
          <div className="text-xs text-muted-foreground uppercase tracking-widest">Good morning</div>
          <h1 className="text-3xl font-display font-bold tracking-tight mt-0.5" data-testid="dashboard-greeting">
            {me.data?.name || user?.name || 'Welcome'}
          </h1>
        </div>
        <Link href="/profile" className="w-11 h-11 rounded-full bg-primary/10 text-primary flex items-center justify-center font-display font-bold">
          {(me.data?.name || user?.name || '?').slice(0, 1).toUpperCase()}
        </Link>
      </header>

      <CutoffTimer />

      {/* Bento grid */}
      <div className="grid grid-cols-2 gap-3">
        <div className="bg-card rounded-2xl p-4 border border-border/50 shadow-[0_4px_24px_-8px_rgba(0,0,0,0.04)]">
          <div className="flex items-center gap-2 mb-2">
            <div className="w-8 h-8 rounded-lg bg-secondary/15 flex items-center justify-center">
              <Leaf className="w-4 h-4 text-secondary" />
            </div>
            <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Bottles</div>
          </div>
          <div className="font-display text-3xl font-bold" data-testid="bottle-balance-value">
            {bottle.isLoading ? '—' : bottle.data?.balance ?? 0}
          </div>
          <div className="text-xs text-muted-foreground mt-1">returnable with you</div>
        </div>
        <div className="bg-card rounded-2xl p-4 border border-border/50 shadow-[0_4px_24px_-8px_rgba(0,0,0,0.04)]">
          <div className="flex items-center gap-2 mb-2">
            <div className="w-8 h-8 rounded-lg bg-primary/15 flex items-center justify-center">
              <Wallet className="w-4 h-4 text-primary" />
            </div>
            <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Wallet</div>
          </div>
          <div className="font-display text-3xl font-bold" data-testid="wallet-balance-value">
            {wallet.isLoading ? '—' : paiseToRupees(wallet.data?.balance_paise ?? 0)}
          </div>
          <div className="text-xs text-muted-foreground mt-1">prepaid balance</div>
        </div>
      </div>

      {/* Active subscriptions */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-display font-semibold">Your subscriptions</h2>
          <Link href="/subscriptions" className="text-xs text-primary font-semibold inline-flex items-center gap-1" data-testid="view-all-subs-link">
            See all <ChevronRight className="w-3 h-3" />
          </Link>
        </div>
        <div className="space-y-3">
          {subs.isLoading && <RowSkeleton />}
          {!subs.isLoading && (subs.data || []).slice(0, 3).map((s: any) => {
            const p = prodMap.get(s.product_id);
            return (
              <Link
                key={s.id}
                href={`/subscriptions/${s.id}`}
                data-testid={`sub-card-${s.id}`}
                className="block bg-card rounded-2xl p-4 border-l-4 border-l-primary border border-border/40 shadow-sm hover:shadow-md transition-shadow"
              >
                <div className="flex items-start justify-between">
                  <div>
                    <div className="font-display font-semibold">{p?.name || 'Product'}</div>
                    <div className="text-xs text-muted-foreground mt-0.5">
                      {s.quantity} × {FREQUENCY_LABEL[s.frequency] || s.frequency}
                    </div>
                  </div>
                  <Badge variant={s.status === 'active' ? 'default' : 'secondary'} className="rounded-full">
                    {s.status}
                  </Badge>
                </div>
              </Link>
            );
          })}
          {!subs.isLoading && (subs.data?.length ?? 0) === 0 && (
            <div className="bg-muted/40 rounded-2xl p-8 text-center border border-dashed border-border">
              <Milk className="w-8 h-8 mx-auto text-muted-foreground mb-2" />
              <div className="text-sm font-medium">No subscriptions yet</div>
              <Link href="/products" className="inline-block mt-3 text-sm text-primary font-semibold">
                Browse products →
              </Link>
            </div>
          )}
        </div>
      </section>

      {/* Upcoming orders */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-display font-semibold">Upcoming deliveries</h2>
        </div>
        <div className="space-y-2">
          {upcoming.isLoading && <RowSkeleton />}
          {!upcoming.isLoading && (upcoming.data || []).slice(0, 5).map((o: any) => {
            const p = prodMap.get(o.product_id);
            return (
              <div key={o.id} className="flex items-center gap-3 p-3 bg-card rounded-xl border border-border/40">
                <div className="w-12 h-12 rounded-xl bg-muted flex items-center justify-center text-muted-foreground font-display font-bold">
                  {String(new Date(o.delivery_date).getDate()).padStart(2, '0')}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-medium truncate">{p?.name || 'Product'}</div>
                  <div className="text-xs text-muted-foreground">Qty {o.quantity}</div>
                </div>
                <Badge variant="outline" className="rounded-full capitalize">{o.status}</Badge>
              </div>
            );
          })}
          {!upcoming.isLoading && (upcoming.data?.length ?? 0) === 0 && (
            <div className="text-sm text-muted-foreground text-center py-6">No deliveries scheduled yet.</div>
          )}
        </div>
      </section>

      <Link
        href="/products"
        className="block text-center bg-primary text-primary-foreground py-4 rounded-full font-semibold shadow-[0_8px_24px_-8px_hsl(var(--primary)/0.5)]"
        data-testid="browse-products-cta"
      >
        Browse products →
      </Link>
    </div>
  );
}
