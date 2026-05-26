"use client";
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Route as RouteIcon, Loader2, X, Filter, AlertCircle, UserCircle2 } from 'lucide-react';
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

type Row = {
  id: string;
  name: string;
  area: string | null;
  active: boolean;
  delivery_boy_id: string | null;
  delivery_boy_name: string | null;
  delivery_boy_phone: string | null;
  stops_count: number;
  last_delivery_date: string | null;
};

type DeliveryBoy = { id: string; name: string | null; phone: string };

function CreateRouteDialog({
  open,
  onOpenChange,
  onCreated,
  boys,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onCreated: (id: string) => void;
  boys: DeliveryBoy[];
}) {
  const [name, setName] = useState('');
  const [area, setArea] = useState('');
  const [boyId, setBoyId] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const valid = name.trim().length >= 1;

  async function submit() {
    setBusy(true);
    try {
      const r = await apiFetch<{ id: string }>(`/admin/routes`, {
        method: 'POST',
        body: {
          name: name.trim(),
          area: area.trim() || null,
          delivery_boy_id: boyId || null,
        },
      });
      toast.success('Route created');
      onCreated(r.id);
      setName(''); setArea(''); setBoyId('');
      onOpenChange(false);
    } catch (e: any) {
      toast.error(e.message || 'Create failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="create-route-dialog" className="max-w-md">
        <DialogHeader>
          <DialogTitle>New route</DialogTitle>
          <DialogDescription>Add a new delivery route. You can assign customers after creation.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Name *</label>
            <Input data-testid="new-route-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Dharampeth Morning" className="mt-1" />
          </div>
          <div>
            <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Area</label>
            <Input data-testid="new-route-area" value={area} onChange={(e) => setArea(e.target.value)} placeholder="e.g. Dharampeth" className="mt-1" />
          </div>
          <div>
            <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Delivery boy</label>
            <Select value={boyId} onValueChange={setBoyId}>
              <SelectTrigger data-testid="new-route-boy" className="mt-1 h-10">
                <SelectValue placeholder="Unassigned" />
              </SelectTrigger>
              <SelectContent>
                {boys.map((b) => (
                  <SelectItem key={b.id} value={b.id}>{b.name || b.phone}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button data-testid="create-route-submit" onClick={submit} disabled={!valid || busy}>
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Create route'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function AdminRoutesPage() {
  const router = useRouter();
  const params = useSearchParams();
  const qc = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [boyFilter, setBoyFilter] = useState<string>(params.get('boy') || 'all');
  const [areaFilter, setAreaFilter] = useState<string>(params.get('area') || '');
  const [activeFilter, setActiveFilter] = useState<string>(params.get('active') || 'all');

  useEffect(() => {
    const qp = new URLSearchParams();
    if (boyFilter !== 'all') qp.set('boy', boyFilter);
    if (areaFilter) qp.set('area', areaFilter);
    if (activeFilter !== 'all') qp.set('active', activeFilter);
    const qs = qp.toString();
    router.replace(`/admin/routes${qs ? `?${qs}` : ''}`, { scroll: false });
  }, [boyFilter, areaFilter, activeFilter, router]);

  const boys = useQuery<DeliveryBoy[]>({
    queryKey: ['delivery-boys'],
    queryFn: () => apiFetch(`/admin/users?role=delivery`),
    staleTime: 60_000,
  });

  const q = useQuery<{ items: Row[]; total: number }>({
    queryKey: ['admin', 'routes', boyFilter, areaFilter, activeFilter],
    queryFn: () =>
      apiFetch('/admin/routes', {
        query: {
          delivery_boy_id: boyFilter === 'all' ? undefined : boyFilter,
          area: areaFilter || undefined,
          active: activeFilter === 'all' ? undefined : activeFilter === 'active',
          page_size: 100,
        },
      }),
    placeholderData: (prev) => prev,
  });

  const rows = q.data?.items ?? [];

  function clearFilters() {
    setBoyFilter('all');
    setAreaFilter('');
    setActiveFilter('all');
  }

  return (
    <div className="space-y-5" data-testid="admin-routes-page">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Operations</div>
          <h1 className="font-display text-3xl font-bold tracking-tight mt-1">Routes</h1>
        </div>
        <Button data-testid="new-route-button" onClick={() => setCreateOpen(true)} size="sm" className="gap-1.5 h-9 text-xs">
          <Plus className="w-3.5 h-3.5" /> New route
        </Button>
      </header>

      {/* Filters */}
      <div className="flex flex-wrap gap-2 items-center bg-card border border-border/60 rounded-xl p-3">
        <Select value={boyFilter} onValueChange={setBoyFilter}>
          <SelectTrigger className="h-9 w-[190px] text-sm" data-testid="routes-boy-filter">
            <UserCircle2 className="w-3.5 h-3.5 mr-1.5" />
            <SelectValue placeholder="Delivery boy" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All delivery boys</SelectItem>
            {(boys.data || []).map((b) => (
              <SelectItem key={b.id} value={b.id}>{b.name || b.phone}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input
          data-testid="routes-area-filter"
          placeholder="Area contains…"
          value={areaFilter}
          onChange={(e) => setAreaFilter(e.target.value)}
          className="h-9 w-[180px] text-sm"
        />
        <Select value={activeFilter} onValueChange={setActiveFilter}>
          <SelectTrigger className="h-9 w-[140px] text-sm" data-testid="routes-active-filter">
            <Filter className="w-3.5 h-3.5 mr-1.5" />
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All</SelectItem>
            <SelectItem value="active">Active</SelectItem>
            <SelectItem value="inactive">Inactive</SelectItem>
          </SelectContent>
        </Select>
        {(boyFilter !== 'all' || areaFilter || activeFilter !== 'all') && (
          <Button variant="ghost" size="sm" onClick={clearFilters} className="h-9 text-xs gap-1" data-testid="routes-clear-filters">
            <X className="w-3.5 h-3.5" /> Clear
          </Button>
        )}
      </div>

      {/* Table */}
      <div className="bg-card border border-border/60 rounded-xl overflow-hidden">
        <table className="w-full text-sm" data-testid="routes-table">
          <thead className="bg-muted/40 text-[10px] uppercase tracking-wider text-muted-foreground">
            <tr>
              <th className="text-left px-3 py-2 font-semibold">Name</th>
              <th className="text-left px-3 py-2 font-semibold">Area</th>
              <th className="text-left px-3 py-2 font-semibold">Delivery boy</th>
              <th className="text-right px-3 py-2 font-semibold">Stops</th>
              <th className="text-left px-3 py-2 font-semibold">Last delivery</th>
              <th className="text-left px-3 py-2 font-semibold">Status</th>
            </tr>
          </thead>
          <tbody>
            {q.isLoading && (
              <tr><td colSpan={6} className="px-3 py-16 text-center text-muted-foreground"><Loader2 className="inline w-4 h-4 animate-spin" /> Loading…</td></tr>
            )}
            {!q.isLoading && rows.length === 0 && (
              <tr><td colSpan={6} className="px-3 py-16 text-center text-muted-foreground" data-testid="routes-empty-state">
                <AlertCircle className="inline w-5 h-5 opacity-40 mb-2" /><br />
                No routes match your filters.
              </td></tr>
            )}
            {rows.map((r) => (
              <tr
                key={r.id}
                data-testid={`route-row-${r.id}`}
                className="border-t border-border/50 hover:bg-muted/30 cursor-pointer h-[40px]"
                onClick={() => router.push(`/admin/routes/${r.id}`)}
              >
                <td className="px-3 py-1.5 font-medium flex items-center gap-2">
                  <RouteIcon className="w-3.5 h-3.5 text-muted-foreground" /> {r.name}
                </td>
                <td className="px-3 py-1.5 text-muted-foreground">{r.area || '—'}</td>
                <td className="px-3 py-1.5 text-sm">
                  {r.delivery_boy_name ? (
                    <div>
                      <div className="truncate">{r.delivery_boy_name}</div>
                      <div className="text-[11px] text-muted-foreground tabular-nums">{r.delivery_boy_phone}</div>
                    </div>
                  ) : <span className="text-muted-foreground italic">Unassigned</span>}
                </td>
                <td className="px-3 py-1.5 text-right tabular-nums">{r.stops_count}</td>
                <td className="px-3 py-1.5 text-xs text-muted-foreground">{r.last_delivery_date ? formatDate(r.last_delivery_date) : '—'}</td>
                <td className="px-3 py-1.5">
                  {r.active ? (
                    <Badge variant="outline" className="rounded-full text-[10px] uppercase tracking-wider bg-secondary/15 text-secondary border-secondary/30">Active</Badge>
                  ) : (
                    <Badge variant="secondary" className="rounded-full text-[10px] uppercase tracking-wider">Inactive</Badge>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <CreateRouteDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        boys={boys.data || []}
        onCreated={(id) => {
          qc.invalidateQueries({ queryKey: ['admin', 'routes'] });
          router.push(`/admin/routes/${id}`);
        }}
      />
    </div>
  );
}
