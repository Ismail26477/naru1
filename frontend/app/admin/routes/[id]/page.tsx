"use client";
import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  DndContext,
  closestCenter,
  PointerSensor,
  useSensor,
  useSensors,
  DragEndEvent,
} from '@dnd-kit/core';
import {
  SortableContext,
  verticalListSortingStrategy,
  useSortable,
  arrayMove,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import {
  ArrowLeft,
  GripVertical,
  Plus,
  Trash2,
  MapPin,
  Loader2,
  Check,
  Search,
  AlertCircle,
  UserCircle2,
  Phone as PhoneIcon,
  PowerOff,
} from 'lucide-react';
import { toast } from 'sonner';
import { apiFetch } from '@/lib/api';
import { formatDate } from '@/lib/format';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { cn } from '@/lib/utils';

type Stop = {
  id: string;
  sequence: number;
  customer_id: string;
  customer_name: string | null;
  customer_phone: string;
  customer_area: string | null;
  customer_lat: number | null;
  customer_lng: number | null;
  bottle_balance: number;
};

type RouteDetail = {
  id: string;
  name: string;
  area: string | null;
  active: boolean;
  delivery_boy_id: string | null;
  delivery_boy_name: string | null;
  delivery_boy_phone: string | null;
  stops: Stop[];
};

function SortableStopRow({
  stop,
  disabled,
  onRemove,
}: {
  stop: Stop;
  disabled: boolean;
  onRemove: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: stop.id,
    disabled,
  });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };
  return (
    <div
      ref={setNodeRef}
      style={style}
      data-testid={`route-stop-${stop.id}`}
      data-sequence={stop.sequence}
      className={cn(
        'flex items-center gap-3 p-3 border-b border-border/50 bg-card hover:bg-muted/40 transition-colors',
        isDragging && 'shadow-lg ring-1 ring-primary/40 z-10 bg-muted',
      )}
    >
      <button
        {...attributes}
        {...listeners}
        disabled={disabled}
        className={cn(
          'p-1 text-muted-foreground hover:text-foreground cursor-grab active:cursor-grabbing',
          disabled && 'opacity-30 cursor-not-allowed',
        )}
        data-testid={`drag-handle-${stop.id}`}
        aria-label="Drag to reorder"
      >
        <GripVertical className="w-4 h-4" />
      </button>
      <div className="w-8 h-8 rounded-lg bg-muted font-display font-bold text-sm flex items-center justify-center tabular-nums" data-testid={`seq-${stop.id}`}>
        {stop.sequence}
      </div>
      <div className="flex-1 min-w-0">
        <div className="font-medium text-sm truncate flex items-center gap-2">
          {stop.customer_name || 'Unnamed'}
          <span className="text-[11px] text-muted-foreground tabular-nums">· {stop.customer_phone}</span>
        </div>
        <div className="text-[11px] text-muted-foreground flex items-center gap-2 mt-0.5 truncate">
          <MapPin className="w-3 h-3 flex-shrink-0" /> {stop.customer_area || '—'}
          <span className="mx-1">·</span>
          <span>Bottles: <span className="tabular-nums">{stop.bottle_balance}</span></span>
        </div>
      </div>
      <Link
        href={`/admin/customers/${stop.customer_id}`}
        className="text-[11px] text-primary hover:underline"
        data-testid={`stop-view-customer-${stop.id}`}
      >
        View →
      </Link>
      <Button
        data-testid={`stop-remove-${stop.id}`}
        variant="ghost"
        size="sm"
        onClick={onRemove}
        disabled={disabled}
        className="h-8 w-8 p-0 text-muted-foreground hover:text-accent"
        aria-label="Remove from route"
      >
        <Trash2 className="w-3.5 h-3.5" />
      </Button>
    </div>
  );
}

// --- Add Customer dialog with debounced search ---
function AddCustomerDialog({
  open,
  onOpenChange,
  onAdd,
  existingCustomerIds,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onAdd: (customerId: string) => Promise<void>;
  existingCustomerIds: Set<string>;
}) {
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  const q = useQuery<{ items: any[] }>({
    queryKey: ['customers-picker', debounced],
    queryFn: () =>
      apiFetch('/admin/customers', {
        query: { search: debounced || undefined, status: 'approved', page_size: 30 },
      }),
    enabled: open,
  });

  const rows = (q.data?.items || []).filter((r: any) => !existingCustomerIds.has(r.id));

  async function go() {
    if (!selected) return;
    setBusy(true);
    try {
      await onAdd(selected);
      setSelected(null); setSearch(''); setDebounced('');
      onOpenChange(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) { setSelected(null); setSearch(''); } onOpenChange(v); }}>
      <DialogContent data-testid="add-customer-dialog" className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Add customer to route</DialogTitle>
          <DialogDescription>Customers already on this route are hidden. Other routes filtered server-side at save.</DialogDescription>
        </DialogHeader>
        <div className="relative mt-1">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input
            data-testid="add-customer-search"
            placeholder="Search name, phone, address"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
            autoFocus
          />
        </div>
        <div className="max-h-[320px] overflow-y-auto border border-border/50 rounded-lg">
          {q.isLoading && <div className="p-6 text-center text-muted-foreground text-sm"><Loader2 className="inline w-4 h-4 animate-spin" /> Loading…</div>}
          {!q.isLoading && rows.length === 0 && <div className="p-6 text-center text-muted-foreground text-sm">No matching customers.</div>}
          {rows.map((r: any) => (
            <button
              key={r.id}
              data-testid={`picker-row-${r.id}`}
              onClick={() => setSelected(r.id)}
              className={cn(
                'w-full text-left px-3 py-2 border-b border-border/40 hover:bg-muted/50 flex items-center gap-3',
                selected === r.id && 'bg-primary/10',
              )}
            >
              <UserCircle2 className="w-4 h-4 text-muted-foreground flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium truncate">{r.name || 'Unnamed'}</div>
                <div className="text-[11px] text-muted-foreground tabular-nums flex items-center gap-2">
                  <PhoneIcon className="w-3 h-3" /> {r.phone} {r.area && <><span>·</span><span className="truncate">{r.area}</span></>}
                </div>
              </div>
              {selected === r.id && <Check className="w-4 h-4 text-primary" />}
            </button>
          ))}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button data-testid="add-customer-submit" onClick={go} disabled={!selected || busy}>
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Add to route'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---- main page ----
export default function RouteDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = String(params.id);
  const qc = useQueryClient();

  const [stopsLocal, setStopsLocal] = useState<Stop[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [deactivateOpen, setDeactivateOpen] = useState(false);
  const [deactReason, setDeactReason] = useState('');
  const [boyDraft, setBoyDraft] = useState<string | null>(null);

  const detail = useQuery<RouteDetail>({
    queryKey: ['admin', 'route', id],
    queryFn: () => apiFetch<RouteDetail>(`/admin/routes/${id}`),
  });

  const boys = useQuery<{ id: string; name: string | null; phone: string }[]>({
    queryKey: ['delivery-boys'],
    queryFn: () => apiFetch('/admin/users?role=delivery'),
    staleTime: 60_000,
  });

  // Reset local order whenever fresh data arrives
  useEffect(() => {
    if (detail.data) setStopsLocal(detail.data.stops);
  }, [detail.data]);

  const d = detail.data;
  const stops = stopsLocal ?? d?.stops ?? [];
  const existingCustomerIds = useMemo(() => new Set(stops.map((s) => s.customer_id)), [stops]);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

  async function persistOrder(newStops: Stop[]) {
    if (!d) return;
    const sequence = newStops.map((s, i) => ({ stop_id: s.id, sequence: i + 1 }));
    const oldStops = d.stops;
    setSaving(true);
    try {
      const r = await apiFetch<RouteDetail>(`/admin/routes/${id}/stops`, {
        method: 'PATCH',
        body: { sequence },
      });
      qc.setQueryData(['admin', 'route', id], r);
      setStopsLocal(r.stops);
      toast.success('Order saved');
    } catch (e: any) {
      // Revert optimistic update
      setStopsLocal(oldStops);
      toast.error(e.message || 'Save failed — reverted', {
        description: 'Please retry.',
      });
    } finally {
      setSaving(false);
    }
  }

  function onDragEnd(e: DragEndEvent) {
    const { active, over } = e;
    if (!over || active.id === over.id || !stopsLocal) return;
    const oldIdx = stopsLocal.findIndex((s) => s.id === active.id);
    const newIdx = stopsLocal.findIndex((s) => s.id === over.id);
    if (oldIdx < 0 || newIdx < 0) return;
    const reordered = arrayMove(stopsLocal, oldIdx, newIdx).map((s, i) => ({ ...s, sequence: i + 1 }));
    setStopsLocal(reordered);
    persistOrder(reordered);
  }

  async function addCustomer(customerId: string) {
    try {
      const r = await apiFetch<RouteDetail>(`/admin/routes/${id}/stops`, {
        method: 'POST',
        body: { customer_id: customerId },
      });
      qc.setQueryData(['admin', 'route', id], r);
      setStopsLocal(r.stops);
      toast.success('Customer added');
    } catch (e: any) {
      const msg = e.message || 'Add failed';
      toast.error(msg.includes('other route') || msg.includes('on_other_route') ? 'Customer is already on another route. Remove them there first.' : msg);
      throw e;
    }
  }

  async function removeStop(stopId: string) {
    try {
      const r = await apiFetch<RouteDetail>(`/admin/routes/${id}/stops/${stopId}`, { method: 'DELETE' });
      qc.setQueryData(['admin', 'route', id], r);
      setStopsLocal(r.stops);
      toast.success('Stop removed · remaining stops renumbered');
    } catch (e: any) {
      toast.error(e.message || 'Remove failed');
    }
  }

  async function saveBoy() {
    if (!d || !boyDraft) return;
    try {
      const r = await apiFetch<RouteDetail>(`/admin/routes/${id}`, {
        method: 'PATCH',
        body: { delivery_boy_id: boyDraft === 'unassign' ? null : boyDraft },
      });
      qc.setQueryData(['admin', 'route', id], r);
      setStopsLocal(r.stops);
      setBoyDraft(null);
      toast.success('Delivery boy updated');
    } catch (e: any) {
      toast.error(e.message || 'Reassign failed');
    }
  }

  async function deactivate() {
    if (deactReason.trim().length < 10) return;
    try {
      const r = await apiFetch<RouteDetail>(`/admin/routes/${id}/deactivate`, {
        method: 'PATCH',
        body: { reason: deactReason.trim() },
      });
      qc.setQueryData(['admin', 'route', id], r);
      toast.success('Route deactivated');
      setDeactivateOpen(false);
      setDeactReason('');
    } catch (e: any) {
      const msg = e.message || 'Deactivate failed';
      if (msg.includes('pending_deliveries')) {
        toast.error('Cannot deactivate — route has pending deliveries for tomorrow.');
      } else {
        toast.error(msg);
      }
    }
  }

  // Haversine stub distance (consecutive stops with lat/lng)
  const estDistanceKm = useMemo(() => {
    let total = 0;
    for (let i = 1; i < stops.length; i++) {
      const a = stops[i - 1];
      const b = stops[i];
      if (a.customer_lat == null || a.customer_lng == null || b.customer_lat == null || b.customer_lng == null) continue;
      const R = 6371;
      const dLat = ((b.customer_lat - a.customer_lat) * Math.PI) / 180;
      const dLon = ((b.customer_lng - a.customer_lng) * Math.PI) / 180;
      const s1 = Math.sin(dLat / 2) ** 2 + Math.cos((a.customer_lat * Math.PI) / 180) * Math.cos((b.customer_lat * Math.PI) / 180) * Math.sin(dLon / 2) ** 2;
      total += 2 * R * Math.asin(Math.sqrt(s1));
    }
    return total;
  }, [stops]);

  if (detail.isLoading || !d) {
    return <div className="flex items-center justify-center py-20"><Loader2 className="w-5 h-5 animate-spin text-muted-foreground" /></div>;
  }

  return (
    <div className="space-y-5" data-testid="admin-route-detail-page">
      <Link href="/admin/routes" className="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1" data-testid="back-to-routes">
        <ArrowLeft className="w-3 h-3" /> Back to routes
      </Link>

      {/* Header */}
      <header className="bg-card border border-border/60 rounded-xl p-5 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="font-display text-2xl font-bold tracking-tight truncate">{d.name}</h1>
            {d.active ? (
              <Badge variant="outline" className="rounded-full text-[10px] uppercase tracking-wider bg-secondary/15 text-secondary border-secondary/30">Active</Badge>
            ) : (
              <Badge variant="secondary" className="rounded-full text-[10px] uppercase tracking-wider">Inactive</Badge>
            )}
          </div>
          <div className="text-sm text-muted-foreground mt-1 flex items-center gap-3 flex-wrap">
            {d.area && <span className="flex items-center gap-1"><MapPin className="w-3.5 h-3.5" /> {d.area}</span>}
            <span>· {stops.length} stops · ~{estDistanceKm.toFixed(1)} km (straight-line stub)</span>
          </div>
          <div className="mt-3 flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-widest font-semibold text-muted-foreground">Delivery boy:</span>
            <Select
              value={boyDraft ?? (d.delivery_boy_id || 'unassign')}
              onValueChange={(v) => setBoyDraft(v)}
            >
              <SelectTrigger data-testid="reassign-boy" className="h-8 w-[220px] text-xs">
                <SelectValue placeholder="Unassigned" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="unassign">Unassigned</SelectItem>
                {(boys.data || []).map((b) => (
                  <SelectItem key={b.id} value={b.id}>{b.name || b.phone}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            {boyDraft && boyDraft !== (d.delivery_boy_id || 'unassign') && (
              <Button data-testid="reassign-save" size="sm" onClick={saveBoy} className="h-8 text-xs">Save</Button>
            )}
          </div>
        </div>
        <div className="flex gap-2 flex-wrap">
          <Button data-testid="add-stop-button" size="sm" onClick={() => setAddOpen(true)} className="gap-1.5 h-9 text-xs">
            <Plus className="w-3.5 h-3.5" /> Add customer
          </Button>
          {d.active && (
            <Button data-testid="deactivate-button" variant="outline" size="sm" onClick={() => setDeactivateOpen(true)} className="gap-1.5 h-9 text-xs text-accent border-accent/40">
              <PowerOff className="w-3.5 h-3.5" /> Deactivate
            </Button>
          )}
        </div>
      </header>

      {/* Saving indicator */}
      <div className="text-[11px] text-muted-foreground flex items-center gap-2 h-5" data-testid="save-status">
        {saving ? <><Loader2 className="w-3 h-3 animate-spin" /> Saving order…</> : <><Check className="w-3 h-3 text-secondary" /> Up to date</>}
      </div>

      {/* Map stub */}
      <div className="bg-muted/40 border border-border/60 rounded-xl h-[140px] flex items-center justify-center text-xs text-muted-foreground" data-testid="route-map-stub">
        <MapPin className="w-4 h-4 mr-2" /> Map preview coming in Phase 2C · {stops.filter((s) => s.customer_lat && s.customer_lng).length} of {stops.length} stops geocoded
      </div>

      {/* Drag-drop list */}
      <div className="bg-card border border-border/60 rounded-xl overflow-hidden" data-testid="stops-list">
        {stops.length === 0 ? (
          <div className="py-16 text-center text-sm text-muted-foreground" data-testid="stops-empty-state">
            <AlertCircle className="inline w-5 h-5 opacity-40 mb-2" /><br />
            No stops yet. Click <span className="font-semibold text-foreground">Add customer</span> above.
          </div>
        ) : (
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
            <SortableContext items={stops.map((s) => s.id)} strategy={verticalListSortingStrategy}>
              {stops.map((s) => (
                <SortableStopRow
                  key={s.id}
                  stop={s}
                  disabled={saving}
                  onRemove={() => removeStop(s.id)}
                />
              ))}
            </SortableContext>
          </DndContext>
        )}
      </div>

      <AddCustomerDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        existingCustomerIds={existingCustomerIds}
        onAdd={addCustomer}
      />

      {/* Deactivate dialog */}
      <Dialog open={deactivateOpen} onOpenChange={setDeactivateOpen}>
        <DialogContent data-testid="deactivate-dialog">
          <DialogHeader>
            <DialogTitle>Deactivate route</DialogTitle>
            <DialogDescription>
              Route will no longer appear in active lists. Requires no pending deliveries for tomorrow.
            </DialogDescription>
          </DialogHeader>
          <div>
            <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Reason (min 10 characters)</label>
            <Textarea
              data-testid="deactivate-reason"
              value={deactReason}
              onChange={(e) => setDeactReason(e.target.value)}
              rows={3}
              className="mt-1"
              maxLength={500}
            />
            <div className="text-[11px] text-muted-foreground mt-1">{deactReason.trim().length} / 10 min</div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeactivateOpen(false)}>Cancel</Button>
            <Button data-testid="deactivate-confirm" onClick={deactivate} disabled={deactReason.trim().length < 10} className="bg-accent hover:bg-accent/90">
              Deactivate
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
