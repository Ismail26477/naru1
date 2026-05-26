"use client";
import { useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft, Loader2, Wrench, Lock, Calendar, Package, MapPin, Truck, Activity,
} from 'lucide-react';
import { apiFetch } from '@/lib/api';
import { paiseToRupees, formatDate, formatDateTime } from '@/lib/format';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { OverrideModal } from '@/components/admin/override-modal';

const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-muted text-muted-foreground border-border',
  delivered: 'bg-secondary/15 text-secondary border-secondary/30',
  skipped: 'bg-accent/15 text-accent border-accent/30',
  failed: 'bg-red-100 text-red-800 border-red-200',
};

export default function DeliveryOrderDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = String(params.id);
  const qc = useQueryClient();
  const [overrideOpen, setOverrideOpen] = useState(false);

  const q = useQuery<any>({
    queryKey: ['admin', 'delivery-order', id],
    queryFn: () => apiFetch(`/admin/delivery-orders/${id}/admin-detail`),
  });

  const d = q.data;
  if (q.isLoading) {
    return <div className="flex items-center justify-center py-20" data-testid="delivery-detail-loading"><Loader2 className="w-5 h-5 animate-spin text-muted-foreground" /></div>;
  }
  if (q.isError || !d) {
    return (
      <div className="py-20 text-center space-y-3" data-testid="delivery-detail-error">
        <div className="text-sm text-muted-foreground">Delivery order not found.</div>
        <Button asChild variant="outline" size="sm">
          <Link href="/admin/delivery-orders">Back to deliveries</Link>
        </Button>
      </div>
    );
  }

  const locked = d.cutoff_locked_at && new Date(d.cutoff_locked_at).getTime() <= Date.now();

  return (
    <div className="space-y-5" data-testid="admin-delivery-detail-page">
      <Link href="/admin/delivery-orders" className="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1" data-testid="back-to-deliveries">
        <ArrowLeft className="w-3 h-3" /> Back to deliveries
      </Link>

      <header className="bg-card border border-border/60 rounded-xl p-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="text-[10px] uppercase tracking-widest font-semibold text-muted-foreground">Delivery order</div>
          <h1 className="font-display text-2xl font-bold tracking-tight mt-1 flex items-center gap-3">
            {d.product_name} × {d.quantity}
            <Badge variant="outline" className={`rounded-full text-[10px] uppercase tracking-wider capitalize ${STATUS_COLORS[d.status]}`}>{d.status}</Badge>
          </h1>
          <div className="text-sm text-muted-foreground mt-1 flex items-center gap-3 flex-wrap">
            <Calendar className="w-3.5 h-3.5" /> {formatDate(d.delivery_date)}
            <span>·</span>
            <Link href={`/admin/customers/${d.customer_id}`} className="text-primary hover:underline" data-testid="link-customer">
              {d.customer_name || d.customer_phone}
            </Link>
            {d.route_id && (
              <>
                <span>·</span>
                <Link href={`/admin/routes/${d.route_id}`} className="text-primary hover:underline" data-testid="link-route">
                  {d.route_name} (seq {d.route_sequence})
                </Link>
              </>
            )}
          </div>
        </div>
        <div className="flex gap-2">
          <Button data-testid="override-open-button" onClick={() => setOverrideOpen(true)} size="sm" className="gap-1.5 h-9 text-xs">
            <Wrench className="w-3.5 h-3.5" /> Manual override
          </Button>
        </div>
      </header>

      {/* Info grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-card border border-border/60 rounded-xl p-4 space-y-3" data-testid="order-info-card">
          <div className="text-[10px] uppercase tracking-widest font-semibold text-muted-foreground">Order</div>
          <div className="flex justify-between text-sm"><span className="text-muted-foreground">Quantity (subscribed)</span><span className="font-semibold tabular-nums">{d.quantity}</span></div>
          <div className="flex justify-between text-sm"><span className="text-muted-foreground">Delivered qty</span><span className="font-semibold tabular-nums">{d.delivered_quantity ?? '—'}</span></div>
          <div className="flex justify-between text-sm"><span className="text-muted-foreground">Unit price</span><span className="font-semibold tabular-nums">{paiseToRupees(d.unit_price_paise)}</span></div>
          <div className="flex justify-between text-sm"><span className="text-muted-foreground">Billable</span>
            <span className="font-semibold tabular-nums">{d.status === 'delivered' ? paiseToRupees((d.delivered_quantity ?? d.quantity) * d.unit_price_paise) : '—'}</span>
          </div>
          <div className="flex justify-between text-sm"><span className="text-muted-foreground">Delivered at</span><span className="font-semibold tabular-nums">{d.delivered_at ? formatDateTime(d.delivered_at) : '—'}</span></div>
          <div className="flex justify-between text-sm items-center"><span className="text-muted-foreground">Cutoff</span>
            <span className="flex items-center gap-1 text-xs">
              {locked ? <><Lock className="w-3 h-3 text-accent" /> Locked at {formatDateTime(d.cutoff_locked_at!)}</> : <span className="text-secondary">Still editable</span>}
            </span>
          </div>
          {d.skip_reason && (
            <div className="p-2 rounded bg-muted/40 text-xs">
              <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold mb-1">Skip reason</div>
              {d.skip_reason}
            </div>
          )}
        </div>

        <div className="bg-card border border-border/60 rounded-xl p-4 space-y-3" data-testid="bottle-card">
          <div className="text-[10px] uppercase tracking-widest font-semibold text-muted-foreground">Bottles</div>
          <div className="flex justify-between text-sm"><span className="text-muted-foreground">Requires bottle</span><span className="font-semibold">{d.product_requires_bottle ? 'Yes' : 'No'}</span></div>
          <div className="flex justify-between text-sm"><span className="text-muted-foreground">Bottles returned this order</span><span className="font-semibold tabular-nums">{d.bottles_returned ?? '—'}</span></div>
          <div className="flex justify-between text-sm"><span className="text-muted-foreground">Customer bottle balance</span><span className="font-semibold tabular-nums" data-testid="customer-bottle-balance">{d.customer_bottle_balance}</span></div>
          {d.bottle_entries.length > 0 && (
            <div className="border-t border-border/50 pt-2">
              <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold mb-2">Ledger rows for this order</div>
              <div className="space-y-1">
                {d.bottle_entries.map((e: any) => (
                  <div key={e.id} className="flex justify-between items-center text-xs">
                    <span className="text-muted-foreground">{formatDateTime(e.created_at)} · {e.reason}</span>
                    <span className={`font-semibold tabular-nums ${e.change >= 0 ? 'text-secondary' : 'text-accent'}`}>{e.change > 0 ? '+' : ''}{e.change}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Audit timeline */}
      <div className="bg-card border border-border/60 rounded-xl overflow-hidden" data-testid="audit-timeline">
        <div className="px-4 py-3 border-b border-border/50 flex items-center gap-2">
          <Activity className="w-3.5 h-3.5 text-muted-foreground" />
          <div className="text-sm font-semibold">Audit timeline</div>
          <div className="text-[11px] text-muted-foreground">({d.audit.length})</div>
        </div>
        <table className="w-full text-sm">
          <tbody>
            {d.audit.length === 0 && (
              <tr><td className="px-4 py-8 text-center text-muted-foreground text-sm">No audit entries for this order yet.</td></tr>
            )}
            {d.audit.map((a: any) => {
              const bypassed = a.after_state?.bypassed_cutoff === true;
              return (
                <tr key={a.id} className="border-t border-border/50 h-[40px]">
                  <td className="px-4 py-1.5 text-xs text-muted-foreground tabular-nums w-[180px]">{formatDateTime(a.created_at)}</td>
                  <td className="px-4 py-1.5 font-mono text-[11px]">{a.action}</td>
                  <td className="px-4 py-1.5 text-xs capitalize">{a.actor_role || 'system'}</td>
                  <td className="px-4 py-1.5">
                    {bypassed && <Badge className="rounded-full text-[10px] uppercase tracking-wider bg-accent/15 text-accent border-accent/30" variant="outline">Bypassed cutoff</Badge>}
                  </td>
                  <td className="px-4 py-1.5 text-xs text-muted-foreground truncate max-w-[320px]">{a.reason || '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <OverrideModal
        open={overrideOpen}
        onOpenChange={setOverrideOpen}
        order={{
          id: d.id,
          status: d.status,
          quantity: d.quantity,
          delivered_quantity: d.delivered_quantity,
          bottles_returned: d.bottles_returned,
          unit_price_paise: d.unit_price_paise,
          product_name: d.product_name,
          product_requires_bottle: d.product_requires_bottle,
          cutoff_locked_at: d.cutoff_locked_at,
          customer_name: d.customer_name,
          customer_phone: d.customer_phone,
          customer_bottle_balance: d.customer_bottle_balance,
        }}
        onDone={() => qc.invalidateQueries({ queryKey: ['admin', 'delivery-order', id] })}
      />
    </div>
  );
}
