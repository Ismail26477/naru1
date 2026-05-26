"use client";
import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  Edit3,
  Loader2,
  TrendingUp,
  Calendar,
  User,
  MessageSquare,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Milk,
  Users,
  Save,
} from 'lucide-react';
import { toast } from 'sonner';
import { apiFetch, ApiError } from '@/lib/api';
import { paiseToRupees, formatDate, formatDateTime } from '@/lib/format';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';

type PriceHistoryRow = {
  id: string;
  price_paise: number;
  effective_from: string; // YYYY-MM-DD
  changed_by: string | null;
  changed_by_name: string | null;
  reason: string | null;
  created_at: string;
};

type ProductDetail = {
  id: string;
  name: string;
  sku: string;
  unit: string;
  price_paise: number;
  requires_bottle: boolean;
  description: string | null;
  image_url: string | null;
  active: boolean;
  created_at: string;
  last_price_change_date: string | null;
  active_subscribers_count: number;
  price_history: PriceHistoryRow[];
};

// -------- helpers --------

/** YYYY-MM-DD representation of today's date in IST. */
function todayIstIso(): string {
  // India Standard Time is UTC+5:30 with no DST.
  const nowMs = Date.now();
  const istMs = nowMs + 5.5 * 60 * 60 * 1000;
  return new Date(istMs).toISOString().slice(0, 10);
}

function tomorrowIstIso(): string {
  const nowMs = Date.now();
  const istMs = nowMs + 5.5 * 60 * 60 * 1000 + 24 * 60 * 60 * 1000;
  return new Date(istMs).toISOString().slice(0, 10);
}

// -------- Price change modal --------

function PriceChangeModal({
  product,
  open,
  onOpenChange,
  onDone,
}: {
  product: ProductDetail;
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onDone: () => void;
}) {
  const today = todayIstIso();
  const tomorrow = tomorrowIstIso();
  const [priceRupees, setPriceRupees] = useState<string>('');
  const [effectiveFrom, setEffectiveFrom] = useState<string>(tomorrow);
  const [reason, setReason] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  // Reset form when modal opens
  useEffect(() => {
    if (open) {
      setPriceRupees((product.price_paise / 100).toFixed(2));
      setEffectiveFrom(tomorrow);
      setReason('');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, product.id]);

  const newPricePaise = useMemo(() => {
    const n = parseFloat(priceRupees);
    if (!isFinite(n) || n <= 0) return 0;
    return Math.round(n * 100);
  }, [priceRupees]);

  const dateValid = effectiveFrom >= today;
  const reasonValid = reason.trim().length >= 10 && reason.trim().length <= 500;
  const priceValid = newPricePaise > 0;
  const priceChanged = newPricePaise !== product.price_paise;
  const isImmediate = effectiveFrom <= today;
  const formValid = dateValid && reasonValid && priceValid && priceChanged;

  async function submit() {
    setBusy(true);
    try {
      await apiFetch(`/admin/products/${product.id}/price-change`, {
        method: 'POST',
        body: {
          new_price_paise: newPricePaise,
          effective_from: effectiveFrom,
          reason: reason.trim(),
        },
      });
      toast.success(
        isImmediate
          ? 'Price updated — applies to orders generated from today'
          : `Price change scheduled for ${formatDate(effectiveFrom)}`,
      );
      setConfirmOpen(false);
      onOpenChange(false);
      onDone();
    } catch (e: any) {
      const err = e as ApiError;
      const code = err.body?.detail?.code;
      if (code === 'cannot_backdate') {
        toast.error('Effective date must be today or later');
      } else {
        toast.error(err.message || 'Price change failed');
      }
    } finally {
      setBusy(false);
    }
  }

  const diff = newPricePaise - product.price_paise;
  const pct = product.price_paise > 0 ? (diff / product.price_paise) * 100 : 0;

  return (
    <>
      <Dialog open={open} onOpenChange={(v) => { if (!busy) onOpenChange(v); }}>
        <DialogContent className="sm:max-w-[480px]" data-testid="price-change-modal">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-primary" />
              Change price
            </DialogTitle>
            <DialogDescription>
              Historical orders keep their snapshotted price. Active orders generated before the effective date are unaffected.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 pt-1">
            {/* Current price readout */}
            <div className="flex items-baseline justify-between rounded-lg bg-muted/40 px-3 py-2">
              <div className="text-[10px] uppercase tracking-widest text-muted-foreground">Current</div>
              <div className="font-display font-bold text-lg tabular-nums">
                {paiseToRupees(product.price_paise)}
              </div>
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                New price (₹)
              </label>
              <Input
                data-testid="price-change-new-price"
                type="number"
                inputMode="decimal"
                step="0.01"
                min="0.01"
                value={priceRupees}
                onChange={(e) => setPriceRupees(e.target.value)}
                className="text-lg font-semibold tabular-nums"
              />
              {priceValid && priceChanged && (
                <div
                  data-testid="price-change-diff"
                  className={`text-[11px] tabular-nums ${diff > 0 ? 'text-accent' : 'text-secondary'}`}
                >
                  {diff > 0 ? '↑' : '↓'} {paiseToRupees(Math.abs(diff))} ({pct >= 0 ? '+' : ''}
                  {pct.toFixed(1)}%) vs current
                </div>
              )}
              {priceValid && !priceChanged && (
                <div className="text-[11px] text-muted-foreground">
                  No change from current price.
                </div>
              )}
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                Effective from
              </label>
              <Input
                data-testid="price-change-effective-from"
                type="date"
                min={today}
                value={effectiveFrom}
                onChange={(e) => setEffectiveFrom(e.target.value)}
              />
              {!dateValid && (
                <div className="text-[11px] text-destructive">
                  Cannot backdate. Pick today or later.
                </div>
              )}
            </div>

            {/* Preview banner */}
            {formValid && (
              <div
                data-testid="price-change-preview"
                className={`rounded-lg px-3 py-2.5 text-xs border ${
                  isImmediate
                    ? 'bg-accent/10 border-accent/30 text-accent-foreground'
                    : 'bg-secondary/10 border-secondary/30 text-secondary-foreground'
                }`}
              >
                <div className="font-semibold flex items-center gap-1.5">
                  {isImmediate ? (
                    <>
                      <CheckCircle2 className="w-3.5 h-3.5 text-accent" />
                      <span>Applies immediately</span>
                    </>
                  ) : (
                    <>
                      <Clock className="w-3.5 h-3.5 text-secondary" />
                      <span>Scheduled for {formatDate(effectiveFrom)}</span>
                    </>
                  )}
                </div>
                <div className="mt-1 text-muted-foreground">
                  {isImmediate
                    ? 'Orders generated from today onwards will use the new price. Existing delivery orders for today (already generated) keep their snapshot.'
                    : 'Current orders and today\u2019s deliveries are unaffected. The new price locks in for orders generated on the effective date.'}
                </div>
                <div className="mt-1.5 flex items-center gap-1.5 text-muted-foreground">
                  <Users className="w-3 h-3" />
                  <span>
                    <span className="font-semibold text-foreground tabular-nums">{product.active_subscribers_count}</span>{' '}
                    active subscriber{product.active_subscribers_count === 1 ? '' : 's'} will see this change
                  </span>
                </div>
              </div>
            )}

            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center justify-between">
                <span>Reason</span>
                <span className={`normal-case font-mono tabular-nums text-[10px] ${reasonValid ? 'text-muted-foreground' : 'text-destructive'}`}>
                  {reason.trim().length}/10+ chars
                </span>
              </label>
              <Textarea
                data-testid="price-change-reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                rows={3}
                placeholder="e.g. Raw milk procurement cost up 8% from local dairy co-op (Mar 2026)."
              />
              {reason.length > 0 && !reasonValid && (
                <div className="text-[11px] text-destructive">
                  Reason must be 10-500 characters.
                </div>
              )}
            </div>
          </div>

          <DialogFooter className="gap-2">
            <Button
              variant="ghost"
              onClick={() => onOpenChange(false)}
              disabled={busy}
            >
              Cancel
            </Button>
            <Button
              data-testid="price-change-submit"
              onClick={() => setConfirmOpen(true)}
              disabled={!formValid || busy}
              className="gap-2"
            >
              Review &amp; confirm
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Confirmation AlertDialog */}
      <AlertDialog open={confirmOpen} onOpenChange={(v) => { if (!busy) setConfirmOpen(v); }}>
        <AlertDialogContent data-testid="price-change-confirm">
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-accent" />
              Confirm price change
            </AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-2 text-sm">
                <div>
                  <span className="font-semibold">{product.name}</span> · {product.sku}
                </div>
                <div className="tabular-nums">
                  {paiseToRupees(product.price_paise)} →{' '}
                  <span className="font-bold text-foreground">
                    {paiseToRupees(newPricePaise)}
                  </span>
                </div>
                <div className="text-muted-foreground">
                  Effective from <span className="font-semibold text-foreground">{formatDate(effectiveFrom)}</span>{' '}
                  {isImmediate ? '(today — applies immediately)' : '(future — scheduled)'}
                </div>
                <div className="text-muted-foreground">
                  {product.active_subscribers_count} active subscriber
                  {product.active_subscribers_count === 1 ? '' : 's'} will be impacted.
                </div>
                <div className="text-[11px] text-muted-foreground italic border-l-2 border-border pl-2 mt-2">
                  &ldquo;{reason.trim()}&rdquo;
                </div>
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel data-testid="price-change-confirm-cancel" disabled={busy}>
              Go back
            </AlertDialogCancel>
            <AlertDialogAction
              data-testid="price-change-confirm-submit"
              onClick={(e) => {
                e.preventDefault();
                submit();
              }}
              disabled={busy}
            >
              {busy ? (
                <><Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" /> Submitting…</>
              ) : (
                'Confirm price change'
              )}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

// -------- Metadata edit form --------

function MetadataForm({ product, onSaved }: { product: ProductDetail; onSaved: () => void }) {
  const [name, setName] = useState(product.name);
  const [description, setDescription] = useState(product.description ?? '');
  const [imageUrl, setImageUrl] = useState(product.image_url ?? '');
  const [requiresBottle, setRequiresBottle] = useState(product.requires_bottle);
  const [active, setActive] = useState(product.active);
  const [busy, setBusy] = useState(false);

  // Re-sync if product prop changes (refetch)
  useEffect(() => {
    setName(product.name);
    setDescription(product.description ?? '');
    setImageUrl(product.image_url ?? '');
    setRequiresBottle(product.requires_bottle);
    setActive(product.active);
  }, [product.id, product.name, product.description, product.image_url, product.requires_bottle, product.active]);

  const dirty =
    name !== product.name ||
    description !== (product.description ?? '') ||
    imageUrl !== (product.image_url ?? '') ||
    requiresBottle !== product.requires_bottle ||
    active !== product.active;

  const valid = name.trim().length >= 1;

  async function save() {
    if (!valid || !dirty) return;
    setBusy(true);
    try {
      await apiFetch(`/admin/products/${product.id}`, {
        method: 'PATCH',
        body: {
          name: name.trim(),
          description: description.trim() || null,
          image_url: imageUrl.trim() || null,
          requires_bottle: requiresBottle,
          active,
        },
      });
      toast.success('Product updated');
      onSaved();
    } catch (e: any) {
      toast.error(e.message || 'Update failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4" data-testid="product-metadata-form">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Name</label>
          <Input
            data-testid="product-edit-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Image URL</label>
          <Input
            data-testid="product-edit-image-url"
            value={imageUrl}
            onChange={(e) => setImageUrl(e.target.value)}
            placeholder="https://…"
          />
        </div>
      </div>

      <div className="space-y-1.5">
        <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Description</label>
        <Textarea
          data-testid="product-edit-description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
        />
      </div>

      <div className="flex flex-wrap gap-5">
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <Checkbox
            checked={requiresBottle}
            onCheckedChange={(v) => setRequiresBottle(!!v)}
            data-testid="product-edit-requires-bottle"
          />
          <span className="flex items-center gap-1.5">
            <Milk className="w-3.5 h-3.5 text-secondary" /> Returnable bottle
          </span>
        </label>
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <Checkbox
            checked={active}
            onCheckedChange={(v) => setActive(!!v)}
            data-testid="product-edit-active"
          />
          <span>Active (visible to customers)</span>
        </label>
      </div>

      <div className="flex items-center gap-3 pt-1">
        <Button
          onClick={save}
          disabled={!dirty || !valid || busy}
          data-testid="product-edit-save"
          className="gap-2"
        >
          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
          Save changes
        </Button>
        {dirty && (
          <span className="text-xs text-muted-foreground" data-testid="product-edit-dirty">
            Unsaved changes
          </span>
        )}
      </div>
    </div>
  );
}

// -------- Page --------

export default function AdminProductDetailPage() {
  const params = useParams();
  const router = useRouter();
  const qc = useQueryClient();
  const id = params?.id as string;
  const [priceOpen, setPriceOpen] = useState(false);

  const query = useQuery<ProductDetail>({
    queryKey: ['admin', 'products', id],
    queryFn: () => apiFetch<ProductDetail>(`/admin/products/${id}`),
    enabled: !!id,
  });

  if (query.isLoading || !query.data) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (query.isError) {
    return (
      <div className="py-20 text-center space-y-3">
        <div className="text-sm text-muted-foreground">Product not found.</div>
        <Button asChild variant="outline" size="sm">
          <Link href="/admin/products">Back to products</Link>
        </Button>
      </div>
    );
  }

  const p = query.data;
  const today = todayIstIso();

  function refresh() {
    qc.invalidateQueries({ queryKey: ['admin', 'products', id] });
    qc.invalidateQueries({ queryKey: ['admin', 'products', 'list'] });
  }

  return (
    <div className="space-y-6" data-testid="admin-product-detail-page">
      {/* Header / breadcrumb */}
      <div>
        <Link
          href="/admin/products"
          data-testid="product-back-link"
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> All products
        </Link>
        <div className="mt-2 flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="font-display text-3xl font-bold tracking-tight flex items-center gap-3">
              {p.name}
              {p.active ? (
                <Badge
                  variant="outline"
                  className="rounded-full text-[10px] uppercase tracking-wider bg-secondary/15 text-secondary border-secondary/30"
                >
                  Active
                </Badge>
              ) : (
                <Badge variant="secondary" className="rounded-full text-[10px] uppercase tracking-wider">
                  Inactive
                </Badge>
              )}
            </h1>
            <div className="mt-1 text-xs text-muted-foreground flex items-center gap-3 flex-wrap">
              <span>
                SKU{' '}
                <span className="font-mono bg-muted/50 text-foreground/80 px-1.5 py-0.5 rounded">
                  {p.sku}
                </span>
              </span>
              <span>
                Unit <span className="text-foreground font-semibold uppercase">{p.unit}</span>
              </span>
              <span>Created {formatDate(p.created_at)}</span>
            </div>
          </div>
        </div>
      </div>

      {/* 2-column layout: price (left) | subscribers (right) */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div
          data-testid="product-current-price-card"
          className="md:col-span-2 rounded-2xl border-2 border-primary/20 bg-primary/5 p-5 relative overflow-hidden"
        >
          <div className="absolute -right-4 -top-4 opacity-10">
            <TrendingUp className="w-24 h-24 text-primary" />
          </div>
          <div className="text-[10px] font-semibold uppercase tracking-widest text-primary">
            Current price
          </div>
          <div className="mt-2 font-display font-bold text-5xl tabular-nums" data-testid="product-current-price">
            {paiseToRupees(p.price_paise)}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            per <span className="uppercase">{p.unit}</span>
            {p.last_price_change_date && (
              <>
                {' · '}
                Last changed {formatDate(p.last_price_change_date)}
              </>
            )}
          </div>
          <Button
            data-testid="open-price-change-modal"
            onClick={() => setPriceOpen(true)}
            size="sm"
            className="mt-4 gap-2 relative z-10"
          >
            <TrendingUp className="w-3.5 h-3.5" /> Change price
          </Button>
        </div>

        <div className="rounded-2xl border border-border/60 bg-card p-5">
          <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
            Impact
          </div>
          <div className="mt-3 space-y-2.5">
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Active subscribers</span>
              <span
                className="font-semibold tabular-nums"
                data-testid="product-active-subscribers"
              >
                {p.active_subscribers_count}
              </span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Bottle required</span>
              <span className="font-semibold">{p.requires_bottle ? 'Yes' : 'No'}</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Price history</span>
              <span className="font-semibold tabular-nums">{p.price_history.length} entr{p.price_history.length === 1 ? 'y' : 'ies'}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Metadata edit card */}
      <div className="rounded-2xl border border-border/60 bg-card p-5">
        <div className="flex items-center gap-2 mb-4">
          <Edit3 className="w-4 h-4 text-muted-foreground" />
          <h2 className="font-display text-lg font-semibold">Metadata</h2>
          <span className="text-[10px] uppercase tracking-widest text-muted-foreground ml-auto">
            SKU &amp; unit locked to preserve billing history
          </span>
        </div>
        <MetadataForm product={p} onSaved={refresh} />
      </div>

      {/* Price history timeline */}
      <div className="rounded-2xl border border-border/60 bg-card p-5">
        <div className="flex items-center gap-2 mb-4">
          <Calendar className="w-4 h-4 text-muted-foreground" />
          <h2 className="font-display text-lg font-semibold">Price history</h2>
          <span className="text-[10px] uppercase tracking-widest text-muted-foreground ml-auto">
            Reverse chronological
          </span>
        </div>
        {p.price_history.length === 0 ? (
          <div className="text-sm text-muted-foreground py-4" data-testid="price-history-empty">
            No price history yet.
          </div>
        ) : (
          <ul className="space-y-2.5" data-testid="price-history-list">
            {p.price_history.map((h) => {
              const isFuture = h.effective_from > today;
              const isCurrent =
                !isFuture && h.effective_from === p.last_price_change_date;
              return (
                <li
                  key={h.id}
                  data-testid={`price-history-row-${h.id}`}
                  className={`flex gap-4 items-start p-3 rounded-lg border ${
                    isFuture
                      ? 'border-secondary/40 bg-secondary/5'
                      : isCurrent
                        ? 'border-primary/40 bg-primary/5'
                        : 'border-border/60 bg-muted/20'
                  }`}
                >
                  <div className="shrink-0 w-28">
                    <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
                      Effective
                    </div>
                    <div className="font-semibold text-sm">{formatDate(h.effective_from)}</div>
                    {isFuture && (
                      <Badge
                        variant="outline"
                        className="mt-1 rounded-full text-[9px] uppercase tracking-wider bg-secondary/15 text-secondary border-secondary/30"
                      >
                        Scheduled
                      </Badge>
                    )}
                    {isCurrent && (
                      <Badge
                        variant="outline"
                        className="mt-1 rounded-full text-[9px] uppercase tracking-wider bg-primary/15 text-primary border-primary/30"
                      >
                        Applied
                      </Badge>
                    )}
                  </div>
                  <div className="flex-1 min-w-0 space-y-1">
                    <div className="flex items-baseline gap-3 flex-wrap">
                      <span className="font-display font-bold text-xl tabular-nums">
                        {paiseToRupees(h.price_paise)}
                      </span>
                      <span className="text-[11px] text-muted-foreground">
                        recorded {formatDateTime(h.created_at)}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                      <User className="w-3 h-3" />
                      <span>{h.changed_by_name || 'System'}</span>
                    </div>
                    {h.reason && (
                      <div className="flex items-start gap-1.5 text-[12px] text-foreground/80 border-l-2 border-border pl-2 mt-1">
                        <MessageSquare className="w-3 h-3 mt-0.5 text-muted-foreground" />
                        <span className="italic">{h.reason}</span>
                      </div>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <PriceChangeModal
        product={p}
        open={priceOpen}
        onOpenChange={setPriceOpen}
        onDone={refresh}
      />
    </div>
  );
}
