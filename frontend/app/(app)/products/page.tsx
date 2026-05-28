"use client";
import { useMemo, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Milk } from 'lucide-react';
import { apiFetch } from '@/lib/api';
import { paiseToRupees } from '@/lib/format';
import { todayIstYmd } from '@/lib/cutoff';
import { Button } from '@/components/ui/button';
import { Dialog, DialogHeader, DialogTitle, DialogFooter, DialogTrigger, DialogDescription } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

const IMG_BY_SKU: Record<string, string> = {
  'COW-MILK-500': 'https://images.unsplash.com/photo-1768850418252-37af725e46bb?crop=entropy&cs=srgb&fm=jpg&w=400&q=75',
  'COW-MILK-1L': 'https://images.unsplash.com/photo-1768850418252-37af725e46bb?crop=entropy&cs=srgb&fm=jpg&w=400&q=75',
  'GHEE-500': 'https://images.unsplash.com/photo-1573812461383-e5f8b759d12e?crop=entropy&cs=srgb&fm=jpg&w=400&q=75',
  'GHEE-1L': 'https://images.unsplash.com/photo-1573812461383-e5f8b759d12e?crop=entropy&cs=srgb&fm=jpg&w=400&q=75',
  'PANEER-250': 'https://images.pexels.com/photos/20395267/pexels-photo-20395267.jpeg?auto=compress&cs=tinysrgb&w=400',
  'BUTTER-500': 'https://images.unsplash.com/photo-1630748662359-40a2105640c7?crop=entropy&cs=srgb&fm=jpg&w=400&q=75',
};

export default function ProductsPage() {
  const qc = useQueryClient();
  const products = useQuery({ queryKey: ['products'], queryFn: () => apiFetch<any[]>('/products') });
  const [selected, setSelected] = useState<any | null>(null);
  const [qty, setQty] = useState(1);
  const [freq, setFreq] = useState<'daily' | 'alternate' | 'weekly' | 'custom'>('daily');
  const [customDays, setCustomDays] = useState<number[]>([]);

  const subscribe = useMutation({
    mutationFn: async () => {
      const body: any = {
        product_id: selected.id,
        quantity: qty,
        frequency: freq,
        start_date: todayIstYmd(),
      };
      if (freq === 'weekly' || freq === 'custom') {
        body.custom_days = (customDays.length ? customDays : [0, 2, 4]).join(',');
      }
      return apiFetch('/me/subscriptions', { method: 'POST', body });
    },
    onSuccess: () => {
      toast.success('Subscribed!');
      qc.invalidateQueries({ queryKey: ['subs'] });
      setSelected(null);
    },
    onError: (e: any) => toast.error(e.message || 'Failed to subscribe'),
  });

  return (
    <div className="p-5 pb-4 animate-fade-in">
      <header className="mb-5">
        <div className="text-xs text-muted-foreground uppercase tracking-widest">Catalog</div>
        <h1 className="text-3xl font-display font-bold tracking-tight mt-0.5">Fresh today</h1>
        <p className="text-sm text-muted-foreground mt-1">Farm-to-doorstep milk, ghee & more.</p>
      </header>

      {products.isLoading && (
        <div className="grid grid-cols-2 gap-3">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="aspect-[3/4] bg-muted/50 rounded-2xl animate-pulse" />
          ))}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        {(products.data || []).map((p) => (
          <button
            key={p.id}
            data-testid={`product-card-${p.sku}`}
            onClick={() => { setSelected(p); setQty(1); setFreq('daily'); }}
            className="text-left bg-card rounded-2xl border border-border/50 overflow-hidden group hover:shadow-md transition-all active:scale-[0.98]"
          >
            <div className="aspect-square bg-muted/60 relative overflow-hidden">
              {IMG_BY_SKU[p.sku] ? (
                <img src={IMG_BY_SKU[p.sku]} alt={p.name} className="w-full h-full object-cover" loading="lazy" />
              ) : (
                <div className="w-full h-full flex items-center justify-center text-muted-foreground">
                  <Milk className="w-10 h-10" />
                </div>
              )}
              {p.requires_bottle && (
                <span className="absolute top-2 left-2 text-[10px] bg-secondary/90 text-secondary-foreground px-2 py-1 rounded-full font-semibold">
                  Returnable
                </span>
              )}
            </div>
            <div className="p-3">
              <div className="font-display font-semibold text-sm leading-snug line-clamp-2 min-h-[2.5rem]">{p.name}</div>
              <div className="mt-2 flex items-baseline justify-between">
                <span className="font-display font-bold text-base text-primary">{paiseToRupees(p.price_paise)}</span>
                <span className="text-[10px] text-muted-foreground uppercase tracking-wider">{p.unit}</span>
              </div>
            </div>
          </button>
        ))}
      </div>

      <Dialog open={!!selected} onOpenChange={(o) => !o && setSelected(null)}>
        <div className="rounded-3xl border-none bg-white p-6">
          <DialogHeader>
            <DialogTitle className="font-display text-xl">{selected?.name}</DialogTitle>
            <DialogDescription>
              {paiseToRupees(selected?.price_paise ?? 0)} per {selected?.unit}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 pt-2">
            <div>
              <Label className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-2 block">
                Quantity
              </Label>
              <div className="flex items-center gap-3">
                <Button variant="outline" size="icon" onClick={() => setQty(Math.max(1, qty - 1))} className="rounded-full">−</Button>
                <Input value={qty} onChange={(e) => setQty(Math.max(1, Number(e.target.value) || 1))} className="text-center font-mono text-lg rounded-xl" data-testid="sub-qty-input" />
                <Button variant="outline" size="icon" onClick={() => setQty(qty + 1)} className="rounded-full">+</Button>
              </div>
            </div>

            <div>
              <Label className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-2 block">
                Frequency
              </Label>
              <Select value={freq} onValueChange={(v: any) => setFreq(v)}>
                <SelectTrigger data-testid="sub-frequency-select" className="rounded-xl h-12">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="daily">Daily</SelectItem>
                  <SelectItem value="alternate">Alternate days</SelectItem>
                  <SelectItem value="weekly">Weekly (pick days)</SelectItem>
                  <SelectItem value="custom">Custom days</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {(freq === 'weekly' || freq === 'custom') && (
              <div>
                <Label className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-2 block">
                  Days of week
                </Label>
                <div className="flex flex-wrap gap-2">
                  {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((d, i) => {
                    const active = customDays.includes(i);
                    return (
                      <button
                        key={d}
                        type="button"
                        onClick={() => setCustomDays(active ? customDays.filter((x) => x !== i) : [...customDays, i])}
                        className={`px-3 py-1.5 rounded-full text-xs font-semibold border transition ${
                          active ? 'bg-primary text-primary-foreground border-primary' : 'bg-muted text-muted-foreground border-border'
                        }`}
                      >
                        {d}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            <div className="flex items-center justify-between pt-2 border-t">
              <span className="text-sm text-muted-foreground">Per-delivery total</span>
              <span className="font-display font-bold text-lg text-primary">
                {paiseToRupees((selected?.price_paise ?? 0) * qty)}
              </span>
            </div>
          </div>

          <DialogFooter>
            <Button
              data-testid="confirm-subscribe-button"
              onClick={() => subscribe.mutate()}
              disabled={subscribe.isPending}
              className="w-full h-12 rounded-full"
            >
              {subscribe.isPending ? 'Subscribing…' : 'Confirm subscription'}
            </Button>
          </DialogFooter>
        </div>
      </Dialog>
    </div>
  );
}
