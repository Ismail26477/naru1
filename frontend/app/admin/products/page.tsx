"use client";
import { useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Plus,
  Package,
  Search,
  Filter,
  Download,
  Loader2,
  AlertCircle,
  MilkOff,
  Milk,
  X,
} from 'lucide-react';
import { toast } from 'sonner';
import { apiFetch } from '@/lib/api';
import { paiseToRupees, formatDate } from '@/lib/format';
import { downloadCsv } from '@/lib/csv';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Textarea } from '@/components/ui/textarea';
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

const UNITS = [
  { value: 'litre', label: 'Litre' },
  { value: 'kg', label: 'Kilogram' },
  { value: 'piece', label: 'Piece' },
];

type ProductRow = {
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
};

function CreateProductDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onCreated: (id: string) => void;
}) {
  const [name, setName] = useState('');
  const [sku, setSku] = useState('');
  const [unit, setUnit] = useState<string>('litre');
  const [priceRupees, setPriceRupees] = useState<string>('');
  const [requiresBottle, setRequiresBottle] = useState(false);
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState(false);

  const pricePaise = useMemo(() => {
    const n = parseFloat(priceRupees);
    if (!isFinite(n) || n <= 0) return 0;
    return Math.round(n * 100);
  }, [priceRupees]);

  const valid =
    name.trim().length >= 1 &&
    sku.trim().length >= 1 &&
    pricePaise > 0 &&
    UNITS.some((u) => u.value === unit);

  function reset() {
    setName('');
    setSku('');
    setUnit('litre');
    setPriceRupees('');
    setRequiresBottle(false);
    setDescription('');
  }

  async function submit() {
    if (!valid) return;
    setBusy(true);
    try {
      const r = await apiFetch<{ id: string }>(`/admin/products`, {
        method: 'POST',
        body: {
          name: name.trim(),
          sku: sku.trim(),
          unit,
          price_paise: pricePaise,
          requires_bottle: requiresBottle,
          description: description.trim() || null,
        },
      });
      toast.success('Product created');
      reset();
      onOpenChange(false);
      onCreated(r.id);
    } catch (e: any) {
      if (e.body?.detail?.code === 'sku_conflict') {
        toast.error('SKU already in use');
      } else {
        toast.error(e.message || 'Create failed');
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!busy) onOpenChange(v); }}>
      <DialogContent className="sm:max-w-[480px]" data-testid="create-product-dialog">
        <DialogHeader>
          <DialogTitle>New product</DialogTitle>
          <DialogDescription>Add a product to the catalogue. SKU and unit cannot be changed later.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3 pt-1">
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Name</label>
            <Input
              data-testid="create-product-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Cow Milk 500 ml"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">SKU</label>
              <Input
                data-testid="create-product-sku"
                value={sku}
                onChange={(e) => setSku(e.target.value.toUpperCase())}
                placeholder="CM-500"
                className="font-mono"
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Unit</label>
              <Select value={unit} onValueChange={setUnit}>
                <SelectTrigger data-testid="create-product-unit">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {UNITS.map((u) => (
                    <SelectItem key={u.value} value={u.value}>{u.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Price (₹)
            </label>
            <Input
              data-testid="create-product-price"
              type="number"
              inputMode="decimal"
              step="0.01"
              min="0.01"
              value={priceRupees}
              onChange={(e) => setPriceRupees(e.target.value)}
              placeholder="35.00"
            />
            <div className="text-[11px] text-muted-foreground tabular-nums">
              Stored as <span className="font-semibold">{pricePaise}</span> paise
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm" data-testid="create-product-bottle-label">
            <Checkbox
              checked={requiresBottle}
              onCheckedChange={(v) => setRequiresBottle(!!v)}
              data-testid="create-product-requires-bottle"
            />
            Returnable glass bottle (+1 on delivery, -1 on return)
          </label>
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Description <span className="normal-case font-normal text-muted-foreground/70">· optional</span>
            </label>
            <Textarea
              data-testid="create-product-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              placeholder="Full-fat cow milk, pasteurised daily in Nagpur."
            />
          </div>
        </div>
        <DialogFooter className="gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>Cancel</Button>
          <Button
            onClick={submit}
            disabled={!valid || busy}
            data-testid="create-product-submit"
            className="gap-2"
          >
            {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Create product
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function AdminProductsPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [openCreate, setOpenCreate] = useState(false);

  const query = useQuery<ProductRow[]>({
    queryKey: ['admin', 'products', 'list'],
    queryFn: () => apiFetch<ProductRow[]>('/admin/products'),
  });

  const all = query.data ?? [];
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return all.filter((p) => {
      if (statusFilter === 'active' && !p.active) return false;
      if (statusFilter === 'inactive' && p.active) return false;
      if (!q) return true;
      return (
        p.name.toLowerCase().includes(q) ||
        p.sku.toLowerCase().includes(q)
      );
    });
  }, [all, search, statusFilter]);

  function exportCsv() {
    if (!filtered.length) return;
    downloadCsv(
      `posuhtik-products-${new Date().toISOString().slice(0, 10)}.csv`,
      filtered.map((p) => ({
        id: p.id,
        name: p.name,
        sku: p.sku,
        unit: p.unit,
        price_rupees: (p.price_paise / 100).toFixed(2),
        requires_bottle: p.requires_bottle,
        active: p.active,
        last_price_change: p.last_price_change_date,
        created_at: p.created_at,
      })),
    );
    toast.success('CSV downloaded');
  }

  function clearFilters() {
    setSearch('');
    setStatusFilter('all');
  }

  return (
    <div className="space-y-5" data-testid="admin-products-page">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
            Catalogue
          </div>
          <h1 className="font-display text-3xl font-bold tracking-tight mt-1">Products</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {all.length} product{all.length === 1 ? '' : 's'} ·{' '}
            <span className="text-foreground font-semibold">
              {all.filter((p) => p.active).length} active
            </span>
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            data-testid="products-export-csv"
            variant="outline"
            size="sm"
            onClick={exportCsv}
            disabled={!filtered.length}
            className="gap-2 h-9 text-xs"
          >
            <Download className="w-3.5 h-3.5" /> Export CSV
          </Button>
          <Button
            onClick={() => setOpenCreate(true)}
            data-testid="products-new-button"
            size="sm"
            className="h-9 text-xs gap-2"
          >
            <Plus className="w-3.5 h-3.5" /> New product
          </Button>
        </div>
      </header>

      {/* Filters */}
      <div className="flex flex-wrap gap-2 items-center bg-card border border-border/60 rounded-xl p-3">
        <div className="relative flex-1 min-w-[220px]">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input
            data-testid="products-search"
            placeholder="Search name or SKU"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 h-9 text-sm"
          />
        </div>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="h-9 w-[160px] text-sm" data-testid="products-status-filter">
            <Filter className="w-3.5 h-3.5 mr-1.5" />
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All</SelectItem>
            <SelectItem value="active">Active only</SelectItem>
            <SelectItem value="inactive">Inactive only</SelectItem>
          </SelectContent>
        </Select>
        {(search || statusFilter !== 'all') && (
          <Button
            variant="ghost"
            size="sm"
            onClick={clearFilters}
            className="h-9 text-xs gap-1"
            data-testid="products-clear-filters"
          >
            <X className="w-3.5 h-3.5" /> Clear
          </Button>
        )}
      </div>

      {/* Table */}
      <div className="bg-card border border-border/60 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="products-table">
            <thead className="bg-muted/40 text-[10px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="text-left px-3 py-2 font-semibold">Product</th>
                <th className="text-left px-3 py-2 font-semibold">SKU</th>
                <th className="text-left px-3 py-2 font-semibold">Unit</th>
                <th className="text-right px-3 py-2 font-semibold">Current price</th>
                <th className="text-left px-3 py-2 font-semibold">Last change</th>
                <th className="text-center px-3 py-2 font-semibold">Bottle</th>
                <th className="text-center px-3 py-2 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody>
              {query.isLoading && (
                <tr>
                  <td colSpan={7} className="px-3 py-16 text-center text-muted-foreground">
                    <Loader2 className="inline w-4 h-4 animate-spin" /> Loading…
                  </td>
                </tr>
              )}
              {!query.isLoading && filtered.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-3 py-16 text-center">
                    <div
                      className="text-muted-foreground text-sm flex flex-col items-center gap-2"
                      data-testid="products-empty-state"
                    >
                      <AlertCircle className="w-6 h-6 opacity-40" />
                      <div>
                        {all.length === 0
                          ? 'No products yet. Create your first product to get started.'
                          : 'No products match your filters.'}
                      </div>
                      {(search || statusFilter !== 'all') && (
                        <Button variant="link" size="sm" onClick={clearFilters}>
                          Clear filters
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              )}
              {filtered.map((p) => (
                <tr
                  key={p.id}
                  data-testid={`product-row-${p.id}`}
                  className="border-t border-border/50 hover:bg-muted/30 cursor-pointer h-[40px]"
                  onClick={() => router.push(`/admin/products/${p.id}`)}
                >
                  <td className="px-3 py-1.5">
                    <div className="font-medium truncate max-w-[280px]">{p.name}</div>
                    {p.description && (
                      <div className="text-[11px] text-muted-foreground truncate max-w-[280px]">
                        {p.description}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-1.5">
                    <span className="font-mono text-[11px] bg-muted/50 text-foreground/80 px-1.5 py-0.5 rounded">
                      {p.sku}
                    </span>
                  </td>
                  <td className="px-3 py-1.5 text-muted-foreground uppercase text-[11px] tracking-wider">
                    {p.unit}
                  </td>
                  <td className="px-3 py-1.5 text-right font-semibold tabular-nums">
                    {paiseToRupees(p.price_paise)}
                  </td>
                  <td className="px-3 py-1.5 text-muted-foreground text-xs">
                    {p.last_price_change_date ? formatDate(p.last_price_change_date) : '—'}
                  </td>
                  <td className="px-3 py-1.5 text-center">
                    {p.requires_bottle ? (
                      <Milk
                        className="w-4 h-4 inline text-secondary"
                        aria-label="Returnable bottle"
                      />
                    ) : (
                      <MilkOff className="w-4 h-4 inline text-muted-foreground/40" aria-label="No bottle" />
                    )}
                  </td>
                  <td className="px-3 py-1.5 text-center">
                    {p.active ? (
                      <Badge
                        variant="outline"
                        className="rounded-full text-[10px] uppercase tracking-wider bg-secondary/15 text-secondary border-secondary/30"
                      >
                        Active
                      </Badge>
                    ) : (
                      <Badge
                        variant="secondary"
                        className="rounded-full text-[10px] uppercase tracking-wider"
                      >
                        Inactive
                      </Badge>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <CreateProductDialog
        open={openCreate}
        onOpenChange={setOpenCreate}
        onCreated={(id) => {
          qc.invalidateQueries({ queryKey: ['admin', 'products'] });
          router.push(`/admin/products/${id}`);
        }}
      />
    </div>
  );
}
