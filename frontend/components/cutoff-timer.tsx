"use client";
import { useEffect, useState } from 'react';
import { AlarmClock } from 'lucide-react';
import { cutoffForDelivery, formatCountdown, tomorrowIstYmd } from '@/lib/cutoff';
import { cn } from '@/lib/utils';

export default function CutoffTimer({
  deliveryYmd,
  label = 'Tomorrow locks in',
  className,
}: {
  deliveryYmd?: string;
  label?: string;
  className?: string;
}) {
  const ymd = deliveryYmd || tomorrowIstYmd();
  const [ms, setMs] = useState<number>(() => cutoffForDelivery(ymd).getTime() - Date.now());

  useEffect(() => {
    const id = setInterval(() => {
      setMs(cutoffForDelivery(ymd).getTime() - Date.now());
    }, 1000);
    return () => clearInterval(id);
  }, [ymd]);

  const passed = ms <= 0;
  return (
    <div
      data-testid="cutoff-timer"
      className={cn(
        'rounded-2xl p-4 border flex items-center justify-between gap-4 animate-fade-in',
        passed
          ? 'bg-muted border-border'
          : 'bg-accent/10 border-accent/30',
        className,
      )}
    >
      <div className="flex items-center gap-3">
        <div className={cn('w-10 h-10 rounded-xl flex items-center justify-center', passed ? 'bg-muted-foreground/20' : 'bg-accent/20')}>
          <AlarmClock className={cn('w-5 h-5', passed ? 'text-muted-foreground' : 'text-accent animate-pulse')} />
        </div>
        <div>
          <div className={cn('text-[10px] font-bold uppercase tracking-widest', passed ? 'text-muted-foreground' : 'text-accent/80')}>
            {passed ? 'Cutoff passed' : label}
          </div>
          <div className="text-xs text-muted-foreground">
            {passed ? 'Tomorrow is locked' : 'until 8:00 PM IST'}
          </div>
        </div>
      </div>
      <div className={cn('font-mono font-bold text-2xl tracking-tight tabular-nums', passed ? 'text-muted-foreground' : 'text-accent')}>
        {formatCountdown(ms)}
      </div>
    </div>
  );
}
