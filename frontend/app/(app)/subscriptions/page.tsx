"use client";
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { Package, ChevronRight, Plus } from 'lucide-react';
import { apiFetch } from '@/lib/api';
import { FREQUENCY_LABEL, paiseToRupees } from '@/lib/format';
import { Badge } from '@/components/ui/badge';
import { RowSkeleton } from '@/components/skeletons';

export default function SubscriptionsPage() {
  const subs = useQuery({ queryKey: ['subs'], queryFn: () => apiFetch<any[]>('/me/subscriptions') });
  const products = useQuery({ queryKey: ['products'], queryFn: () => apiFetch<any[]>('/products') });
  const prodMap = new Map((products.data || []).map((p) => [p.id, p]));

  const active = (subs.data || []).filter((s) => s.status === 'active');
  const paused = (subs.data || []).filter((s) => s.status === 'paused');
  const ended = (subs.data || []).filter((s) => s.status === 'cancelled');

  return (
    <div className="p-5 pb-4 animate-fade-in">
      <header className="mb-5 flex items-end justify-between">
        <div>
          <div className="text-xs text-muted-foreground uppercase tracking-widest">Your plan</div>
          <h1 className="text-3xl font-display font-bold tracking-tight mt-0.5">Subscriptions</h1>
        </div>
        <Link
          href="/products"
          data-testid="add-subscription-button"
          className="inline-flex items-center gap-1 bg-primary text-primary-foreground px-4 py-2 rounded-full text-sm font-semibold shadow-[0_4px_14px_-4px_hsl(var(--primary)/0.5)]"
        >
          <Plus className="w-4 h-4" /> Add
        </Link>
      </header>

      {subs.isLoading && <div className="space-y-3"><RowSkeleton /><RowSkeleton /></div>}

      {!subs.isLoading && (subs.data?.length ?? 0) === 0 && (
        <div className="bg-muted/40 rounded-2xl p-10 text-center border border-dashed">
          <Package className="w-10 h-10 mx-auto text-muted-foreground mb-3" />
          <div className="font-medium">No subscriptions yet</div>
          <p className="text-sm text-muted-foreground mt-1 mb-4">Start with a daily milk plan — you can modify anytime.</p>
          <Link href="/products" className="inline-block bg-primary text-primary-foreground px-6 py-3 rounded-full text-sm font-semibold">
            Browse products
          </Link>
        </div>
      )}

      {active.length > 0 && (
        <section className="mb-6">
          <h2 className="text-xs font-bold uppercase tracking-widest text-muted-foreground mb-3">Active</h2>
          <div className="space-y-3">
            {active.map((s) => <Card key={s.id} sub={s} product={prodMap.get(s.product_id)} />)}
          </div>
        </section>
      )}

      {paused.length > 0 && (
        <section className="mb-6">
          <h2 className="text-xs font-bold uppercase tracking-widest text-muted-foreground mb-3">Paused</h2>
          <div className="space-y-3">
            {paused.map((s) => <Card key={s.id} sub={s} product={prodMap.get(s.product_id)} />)}
          </div>
        </section>
      )}

      {ended.length > 0 && (
        <section className="mb-6">
          <h2 className="text-xs font-bold uppercase tracking-widest text-muted-foreground mb-3">Cancelled</h2>
          <div className="space-y-3">
            {ended.map((s) => <Card key={s.id} sub={s} product={prodMap.get(s.product_id)} />)}
          </div>
        </section>
      )}
    </div>
  );
}

function Card({ sub, product }: { sub: any; product: any }) {
  return (
    <Link
      href={`/subscriptions/${sub.id}`}
      data-testid={`sub-card-${sub.id}`}
      className="block bg-card rounded-2xl p-4 border-l-4 border-l-primary border border-border/40 shadow-sm hover:shadow-md transition-shadow"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="font-display font-semibold truncate">{product?.name || 'Product'}</div>
          <div className="text-xs text-muted-foreground mt-0.5">
            {sub.quantity} × {FREQUENCY_LABEL[sub.frequency] || sub.frequency}
          </div>
          {product && (
            <div className="text-xs mt-2 font-mono">
              {paiseToRupees(product.price_paise * sub.quantity)} / delivery
            </div>
          )}
        </div>
        <div className="flex flex-col items-end gap-2">
          <Badge variant={sub.status === 'active' ? 'default' : 'secondary'} className="rounded-full capitalize">
            {sub.status}
          </Badge>
          <ChevronRight className="w-4 h-4 text-muted-foreground" />
        </div>
      </div>
    </Link>
  );
}
