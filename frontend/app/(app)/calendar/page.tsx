"use client";
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Lock, Check, Clock, X } from 'lucide-react';
import { apiFetch } from '@/lib/api';
import { todayIstYmd, addDaysYmd, isModifiable } from '@/lib/cutoff';
import { formatDate } from '@/lib/format';
import { cn } from '@/lib/utils';
import CutoffTimer from '@/components/cutoff-timer';

export default function CalendarPage() {
  const today = todayIstYmd();
  const to = addDaysYmd(today, 30);
  const orders = useQuery({
    queryKey: ['orders', today, to],
    queryFn: () => apiFetch<any[]>('/me/delivery-orders', { query: { from: today, to } }),
  });

  const ordersByDate = useMemo(() => {
    const m = new Map<string, any[]>();
    for (const o of orders.data || []) {
      const d = o.delivery_date;
      if (!m.has(d)) m.set(d, []);
      m.get(d)!.push(o);
    }
    return m;
  }, [orders.data]);

  const days: { ymd: string; label: string; weekday: string }[] = [];
  for (let i = 0; i < 30; i++) {
    const ymd = addDaysYmd(today, i);
    const d = new Date(ymd + 'T00:00:00');
    days.push({
      ymd,
      label: formatDate(ymd, 'd'),
      weekday: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][d.getUTCDay()],
    });
  }

  return (
    <div className="p-5 pb-4 animate-fade-in">
      <header className="mb-4">
        <div className="text-xs text-muted-foreground uppercase tracking-widest">Schedule</div>
        <h1 className="text-3xl font-display font-bold tracking-tight mt-0.5">Next 30 days</h1>
        <p className="text-sm text-muted-foreground mt-1">Locked days are past the 8 PM cutoff.</p>
      </header>

      <CutoffTimer className="mb-5" />

      <div className="bg-card rounded-3xl p-4 border border-border/50 shadow-sm">
        {/* Legend */}
        <div className="flex flex-wrap items-center gap-3 text-xs mb-4 text-muted-foreground">
          <span className="inline-flex items-center gap-1"><span className="w-3 h-3 rounded-md bg-primary/20 border border-primary/30" /> Delivery</span>
          <span className="inline-flex items-center gap-1"><span className="w-3 h-3 rounded-md bg-secondary/20 border border-secondary/30" /> Delivered</span>
          <span className="inline-flex items-center gap-1"><Lock className="w-3 h-3" /> Locked</span>
        </div>

        <div className="grid grid-cols-7 gap-1.5 mb-2 text-[10px] font-bold uppercase text-muted-foreground text-center">
          {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((d) => <div key={d}>{d}</div>)}
        </div>

        <div className="grid grid-cols-7 gap-1.5">
          {/* blank offset for first week alignment */}
          {(() => {
            const firstDow = new Date(today + 'T00:00:00').getUTCDay();
            return Array.from({ length: firstDow }).map((_, i) => <div key={`pad-${i}`} />);
          })()}
          {days.map((d) => {
            const list = ordersByDate.get(d.ymd) || [];
            const hasDelivery = list.length > 0;
            const delivered = list.some((o) => o.status === 'delivered');
            const skipped = list.some((o) => o.status === 'skipped');
            const locked = !isModifiable(d.ymd);
            const isToday = d.ymd === today;

            return (
              <div
                key={d.ymd}
                data-testid={`calendar-day-${d.ymd}`}
                className={cn(
                  'aspect-square rounded-xl flex flex-col items-center justify-center text-xs border relative overflow-hidden',
                  isToday && 'ring-2 ring-primary ring-offset-1',
                  locked && !hasDelivery && 'bg-stone-50 text-muted-foreground/50 border-border locked-hatch',
                  locked && hasDelivery && !delivered && 'bg-stone-100 border-border locked-hatch',
                  !locked && hasDelivery && 'bg-primary/10 border-primary/30 text-primary font-bold',
                  !locked && !hasDelivery && 'bg-card border-border/60',
                  delivered && 'bg-secondary/15 border-secondary/40 text-secondary-foreground',
                  skipped && 'bg-muted border-border',
                )}
              >
                <span className={cn('font-display font-bold text-sm', isToday && 'text-primary')}>{d.label}</span>
                {hasDelivery && !delivered && !skipped && (
                  <span className="w-1 h-1 mt-0.5 rounded-full bg-primary" />
                )}
                {delivered && <Check className="w-2.5 h-2.5 text-secondary" />}
                {skipped && <X className="w-2.5 h-2.5 text-muted-foreground" />}
                {locked && !delivered && !skipped && <Lock className="absolute top-0.5 right-0.5 w-2 h-2 text-muted-foreground/40" />}
              </div>
            );
          })}
        </div>
      </div>

      {/* Today / Tomorrow details */}
      <div className="mt-5 space-y-3">
        {[today, addDaysYmd(today, 1)].map((ymd) => {
          const list = ordersByDate.get(ymd) || [];
          if (!list.length) return null;
          return (
            <div key={ymd} className="bg-card rounded-2xl p-4 border border-border/50">
              <div className="flex items-center justify-between mb-2">
                <div className="font-display font-semibold">{ymd === today ? 'Today' : 'Tomorrow'} · {formatDate(ymd, 'EEE, d MMM')}</div>
                {!isModifiable(ymd) && <Lock className="w-3.5 h-3.5 text-muted-foreground" />}
              </div>
              <ul className="space-y-1.5">
                {list.map((o: any) => (
                  <li key={o.id} className="flex items-center justify-between text-sm">
                    <span className="truncate">Qty {o.quantity}</span>
                    <span className="text-xs capitalize text-muted-foreground">{o.status}</span>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>
    </div>
  );
}
