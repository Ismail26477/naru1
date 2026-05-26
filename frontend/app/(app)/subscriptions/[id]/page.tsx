"use client";
import { useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { ArrowLeft, Pause, Play, XCircle, CalendarOff, Loader2 } from 'lucide-react';
import { apiFetch } from '@/lib/api';
import { FREQUENCY_LABEL, paiseToRupees, formatDate } from '@/lib/format';
import { tomorrowIstYmd, addDaysYmd, isModifiable } from '@/lib/cutoff';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '@/components/ui/dialog';
import CutoffTimer from '@/components/cutoff-timer';

export default function SubscriptionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();

  const sub = useQuery({ queryKey: ['sub', id], queryFn: () => apiFetch<any>(`/me/subscriptions`).then((list) => list.find((s: any) => s.id === id)) });
  const products = useQuery({ queryKey: ['products'], queryFn: () => apiFetch<any[]>('/products') });
  const product = (products.data || []).find((p) => p.id === sub.data?.product_id);

  const [editQty, setEditQty] = useState<number | ''>('');
  const [freq, setFreq] = useState<string>('');
  const [overrideDate, setOverrideDate] = useState<string>(tomorrowIstYmd());
  const [skipDlg, setSkipDlg] = useState(false);

  const update = useMutation({
    mutationFn: async (body: any) => apiFetch(`/me/subscriptions/${id}`, { method: 'PATCH', body }),
    onSuccess: () => {
      toast.success('Subscription updated');
      qc.invalidateQueries({ queryKey: ['sub', id] });
      qc.invalidateQueries({ queryKey: ['subs'] });
      setEditQty('');
      setFreq('');
    },
    onError: (e: any) => toast.error(e.message),
  });

  const skipDate = useMutation({
    mutationFn: async () => apiFetch(`/me/subscriptions/${id}/schedule-override`, {
      method: 'POST',
      body: { date: overrideDate, skip: true, reason: 'customer skip' },
    }),
    onSuccess: () => {
      toast.success(`Skipped ${formatDate(overrideDate)}`);
      qc.invalidateQueries({ queryKey: ['orders'] });
      setSkipDlg(false);
    },
    onError: (e: any) => toast.error(e.message || 'Could not skip'),
  });

  if (sub.isLoading) {
    return <div className="p-6"><Loader2 className="w-5 h-5 animate-spin" /></div>;
  }
  if (!sub.data) {
    return <div className="p-6 text-center text-muted-foreground">Subscription not found. <Link className="text-primary underline" href="/subscriptions">Back</Link></div>;
  }
  const s = sub.data;
  const canModifyTomorrow = isModifiable(overrideDate);

  return (
    <div className="pb-32 animate-fade-in">
      {/* Header */}
      <div className="sticky top-0 z-40 bg-background/95 backdrop-blur border-b border-border/50 px-4 py-3 flex items-center gap-3">
        <button onClick={() => router.back()} className="w-9 h-9 rounded-full bg-muted flex items-center justify-center" data-testid="back-button">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div className="flex-1 min-w-0">
          <div className="font-display font-semibold truncate">{product?.name || 'Subscription'}</div>
          <div className="text-xs text-muted-foreground">Subscription detail</div>
        </div>
        <Badge variant={s.status === 'active' ? 'default' : 'secondary'} className="rounded-full capitalize">{s.status}</Badge>
      </div>

      <div className="p-5 space-y-5">
        {/* Summary */}
        <div className="bg-card rounded-2xl p-5 border border-border/50">
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <div className="text-xs text-muted-foreground uppercase tracking-widest">Quantity</div>
              <div className="font-display text-2xl font-bold">{s.quantity}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground uppercase tracking-widest">Frequency</div>
              <div className="font-display text-lg font-semibold">{FREQUENCY_LABEL[s.frequency] || s.frequency}</div>
            </div>
          </div>
          {product && (
            <div className="pt-4 border-t border-border/50 flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Per delivery</span>
              <span className="font-display font-bold text-lg text-primary">
                {paiseToRupees(product.price_paise * s.quantity)}
              </span>
            </div>
          )}
        </div>

        {/* Modify */}
        <div className="bg-card rounded-2xl p-5 border border-border/50 space-y-4">
          <h2 className="font-display font-semibold">Modify plan</h2>
          <div>
            <Label className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-2 block">Quantity</Label>
            <Input
              data-testid="modify-qty-input"
              type="number"
              min={1}
              max={50}
              placeholder={String(s.quantity)}
              value={editQty}
              onChange={(e) => setEditQty(e.target.value === '' ? '' : Math.max(1, Number(e.target.value)))}
              className="rounded-xl h-12"
            />
          </div>
          <div>
            <Label className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-2 block">Frequency</Label>
            <Select value={freq || s.frequency} onValueChange={setFreq}>
              <SelectTrigger data-testid="modify-frequency-select" className="rounded-xl h-12"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="daily">Daily</SelectItem>
                <SelectItem value="alternate">Alternate days</SelectItem>
                <SelectItem value="weekly">Weekly</SelectItem>
                <SelectItem value="custom">Custom</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Button
            data-testid="save-modifications-button"
            disabled={update.isPending || (!editQty && !freq)}
            onClick={() => {
              const body: any = {};
              if (editQty) body.quantity = Number(editQty);
              if (freq) body.frequency = freq;
              update.mutate(body);
            }}
            className="w-full h-12 rounded-full"
          >
            {update.isPending ? 'Saving…' : 'Save changes'}
          </Button>
        </div>

        {/* Pause / Resume / Cancel */}
        <div className="bg-card rounded-2xl p-5 border border-border/50 space-y-3">
          <h2 className="font-display font-semibold">Schedule controls</h2>
          <div className="grid grid-cols-3 gap-2">
            {s.status === 'active' ? (
              <Button
                data-testid="pause-subscription-button"
                variant="outline"
                onClick={() => update.mutate({ status: 'paused' })}
                className="rounded-xl h-14 flex-col gap-1 text-xs"
              >
                <Pause className="w-4 h-4" /> Pause
              </Button>
            ) : (
              <Button
                data-testid="resume-subscription-button"
                variant="outline"
                onClick={() => update.mutate({ status: 'active' })}
                className="rounded-xl h-14 flex-col gap-1 text-xs"
              >
                <Play className="w-4 h-4" /> Resume
              </Button>
            )}
            <Button
              data-testid="skip-date-button"
              variant="outline"
              onClick={() => setSkipDlg(true)}
              className="rounded-xl h-14 flex-col gap-1 text-xs"
            >
              <CalendarOff className="w-4 h-4" /> Skip a day
            </Button>
            <Button
              data-testid="cancel-subscription-button"
              variant="outline"
              onClick={() => {
                if (confirm('Cancel this subscription?')) update.mutate({ status: 'cancelled' });
              }}
              className="rounded-xl h-14 flex-col gap-1 text-xs text-accent"
            >
              <XCircle className="w-4 h-4" /> Cancel
            </Button>
          </div>
        </div>
      </div>

      {/* Sticky cutoff bar */}
      <div className="fixed bottom-20 left-1/2 -translate-x-1/2 w-full max-w-md px-4 z-40">
        <CutoffTimer className="shadow-lg" />
      </div>

      {/* Skip dialog */}
      <Dialog open={skipDlg} onOpenChange={setSkipDlg}>
        <DialogContent className="rounded-3xl border-none">
          <DialogHeader>
            <DialogTitle className="font-display">Skip a delivery</DialogTitle>
            <DialogDescription>
              Pick a date to skip. Dates past 8 PM IST on the preceding day are locked.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <Label className="text-xs uppercase tracking-widest text-muted-foreground">Delivery date</Label>
            <Input
              data-testid="skip-date-input"
              type="date"
              min={tomorrowIstYmd()}
              max={addDaysYmd(tomorrowIstYmd(), 45)}
              value={overrideDate}
              onChange={(e) => setOverrideDate(e.target.value)}
              className="rounded-xl h-12"
            />
            {!canModifyTomorrow && (
              <div className="p-3 bg-accent/10 border border-accent/30 rounded-xl text-sm text-accent">
                This date is past its 8 PM cutoff. Pick a later date.
              </div>
            )}
          </div>
          <DialogFooter>
            <Button
              data-testid="confirm-skip-button"
              onClick={() => skipDate.mutate()}
              disabled={skipDate.isPending || !canModifyTomorrow}
              className="w-full h-12 rounded-full"
            >
              {skipDate.isPending ? 'Skipping…' : `Skip ${formatDate(overrideDate)}`}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
