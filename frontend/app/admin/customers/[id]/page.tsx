"use client";
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  CheckCircle2,
  XCircle,
  Wallet,
  Activity,
  LogOut,
  Loader2,
  MapPin,
  Mail,
  Phone as PhoneIcon,
  Calendar,
  ShieldOff,
  Plus,
  Minus,
  PauseCircle,
  PlayCircle,
  Slash,
} from 'lucide-react';
import { toast } from 'sonner';
import { apiFetch } from '@/lib/api';
import { paiseToRupees, formatDate, formatDateTime, STATUS_LABEL, FREQUENCY_LABEL } from '@/lib/format';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
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
import { Textarea } from '@/components/ui/textarea';
import { AdjustmentModal } from '@/components/admin/adjustment-modal';

type Detail = {
  id: string;
  phone: string;
  name: string | null;
  email: string | null;
  role: string;
  approved_at: string | null;
  is_active: boolean;
  wallet_balance_paise: number;
  bottle_balance: number;
  created_at: string;
  addresses: Array<{ id: string; line1: string; line2: string | null; area: string; city: string; pincode: string; is_default: boolean }>;
  active_subs_count: number;
  total_subs_count: number;
  invoice_count: number;
  open_invoices_paise: number;
};

function ReasonDialog({
  open, onOpenChange, title, description, actionLabel, destructive, onConfirm, minLength = 10,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: string;
  description: string;
  actionLabel: string;
  destructive?: boolean;
  onConfirm: (reason: string) => Promise<void>;
  minLength?: number;
}) {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const valid = reason.trim().length >= minLength;

  async function go() {
    setBusy(true);
    try {
      await onConfirm(reason.trim());
      setReason('');
      onOpenChange(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={(v) => { if (!v) setReason(''); onOpenChange(v); }}>
      <AlertDialogContent data-testid="reason-dialog">
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <div>
          <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Reason (min {minLength} characters)
          </label>
          <Textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            className="mt-1"
            maxLength={500}
            data-testid="reason-dialog-input"
          />
          <div className="text-[11px] text-muted-foreground mt-1">
            {reason.trim().length} / {minLength} min
          </div>
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel data-testid="reason-dialog-cancel">Cancel</AlertDialogCancel>
          <AlertDialogAction
            onClick={(e) => { e.preventDefault(); if (valid && !busy) go(); }}
            disabled={!valid || busy}
            className={destructive ? 'bg-accent hover:bg-accent/90' : ''}
            data-testid="reason-dialog-confirm"
          >
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : actionLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export default function CustomerDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = String(params.id);
  const qc = useQueryClient();

  const [walletOpen, setWalletOpen] = useState(false);
  const [bottleOpen, setBottleOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [revokeOpen, setRevokeOpen] = useState(false);
  const [pauseSubId, setPauseSubId] = useState<string | null>(null);
  const [cancelSubId, setCancelSubId] = useState<string | null>(null);

  const detail = useQuery<Detail>({
    queryKey: ['admin', 'customer', id],
    queryFn: () => apiFetch<Detail>(`/admin/customers/${id}`),
  });

  const subs = useQuery<any[]>({
    queryKey: ['admin', 'customer', id, 'subs'],
    queryFn: () => apiFetch(`/admin/customers/${id}/subscriptions`),
    enabled: !!detail.data,
  });

  const deliveries = useQuery<any[]>({
    queryKey: ['admin', 'customer', id, 'deliveries'],
    queryFn: () => apiFetch(`/admin/customers/${id}/deliveries?page=1&page_size=60`),
    enabled: !!detail.data,
  });

  const invoices = useQuery<any[]>({
    queryKey: ['admin', 'customer', id, 'invoices'],
    queryFn: () => apiFetch(`/admin/customers/${id}/invoices?page=1&page_size=24`),
    enabled: !!detail.data,
  });

  const wallet = useQuery<{ balance_paise: number; items: any[]; total: number }>({
    queryKey: ['admin', 'customer', id, 'wallet'],
    queryFn: () => apiFetch(`/admin/customers/${id}/wallet-transactions?page=1&page_size=30`),
    enabled: !!detail.data,
  });

  const bottles = useQuery<{ balance: number; items: any[]; total: number }>({
    queryKey: ['admin', 'customer', id, 'bottles'],
    queryFn: () => apiFetch(`/admin/customers/${id}/bottle-ledger?page=1&page_size=30`),
    enabled: !!detail.data,
  });

  const audit = useQuery<any[]>({
    queryKey: ['admin', 'customer', id, 'audit'],
    queryFn: () => apiFetch(`/admin/customers/${id}/audit-log`),
    enabled: !!detail.data,
  });

  const d = detail.data;

  function refreshAll() {
    qc.invalidateQueries({ queryKey: ['admin', 'customer', id] });
  }

  async function approve() {
    try {
      await apiFetch(`/admin/customers/${id}/approve`, { method: 'POST', body: { reason: null } });
      toast.success('Customer approved');
      refreshAll();
    } catch (e: any) {
      toast.error(e.message || 'Approve failed');
    }
  }

  async function reject(reason: string) {
    try {
      await apiFetch(`/admin/customers/${id}/reject`, { method: 'POST', body: { reason } });
      toast.success('Customer rejected');
      refreshAll();
    } catch (e: any) {
      toast.error(e.message || 'Reject failed');
    }
  }

  async function revokeTokens(reason: string) {
    try {
      await apiFetch(`/admin/customers/${id}/revoke-tokens`, { method: 'POST', body: { reason } });
      toast.success('All tokens revoked');
      refreshAll();
    } catch (e: any) {
      toast.error(e.message || 'Revoke failed');
    }
  }

  async function pauseSub(sid: string, reason: string) {
    try {
      await apiFetch(`/admin/subscriptions/${sid}/pause`, { method: 'POST', body: { reason } });
      toast.success('Subscription paused');
      qc.invalidateQueries({ queryKey: ['admin', 'customer', id, 'subs'] });
    } catch (e: any) {
      toast.error(e.message || 'Pause failed');
    }
  }

  async function resumeSub(sid: string) {
    try {
      await apiFetch(`/admin/subscriptions/${sid}/resume`, { method: 'POST', body: { reason: null } });
      toast.success('Subscription resumed');
      qc.invalidateQueries({ queryKey: ['admin', 'customer', id, 'subs'] });
    } catch (e: any) {
      toast.error(e.message || 'Resume failed');
    }
  }

  async function cancelSub(sid: string, reason: string) {
    try {
      await apiFetch(`/admin/subscriptions/${sid}/cancel`, { method: 'POST', body: { reason } });
      toast.success('Subscription cancelled');
      qc.invalidateQueries({ queryKey: ['admin', 'customer', id, 'subs'] });
    } catch (e: any) {
      toast.error(e.message || 'Cancel failed');
    }
  }

  if (detail.isLoading) {
    return <div className="flex items-center justify-center py-20"><Loader2 className="w-5 h-5 animate-spin text-muted-foreground" /></div>;
  }
  if (detail.isError || !d) {
    return (
      <div className="space-y-4">
        <Link href="/admin/customers" className="text-xs text-primary">← Back to customers</Link>
        <div className="text-sm text-accent">Customer not found.</div>
      </div>
    );
  }

  const pending = !d.approved_at;

  return (
    <div className="space-y-5" data-testid="admin-customer-detail-page">
      <Link
        href="/admin/customers"
        className="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1"
        data-testid="back-to-customers"
      >
        <ArrowLeft className="w-3 h-3" /> Back to customers
      </Link>

      {/* Hero */}
      <header className="bg-card border border-border/60 rounded-xl p-5 flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className="w-14 h-14 rounded-xl bg-primary/15 text-primary flex items-center justify-center font-display font-bold text-xl">
            {(d.name ?? '?').slice(0, 1).toUpperCase()}
          </div>
          <div>
            <div className="font-display text-2xl font-bold tracking-tight" data-testid="customer-name">
              {d.name || 'Unnamed customer'}
            </div>
            <div className="text-sm text-muted-foreground tabular-nums flex items-center gap-2 mt-1">
              <PhoneIcon className="w-3.5 h-3.5" /> {d.phone}
              {d.email && <><Mail className="w-3.5 h-3.5 ml-2" /> {d.email}</>}
            </div>
            <div className="flex items-center gap-2 mt-2">
              {pending ? (
                <Badge className="rounded-full bg-accent/15 text-accent border-accent/30" variant="outline">Pending approval</Badge>
              ) : (
                <Badge className="rounded-full bg-secondary/15 text-secondary border-secondary/30" variant="outline">Approved</Badge>
              )}
              {!d.is_active && <Badge variant="secondary" className="rounded-full">Inactive</Badge>}
              <span className="text-[11px] text-muted-foreground">
                Joined {formatDate(d.created_at)}
              </span>
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {pending && (
            <Button data-testid="approve-button" onClick={approve} size="sm" className="gap-1.5 h-9 text-xs">
              <CheckCircle2 className="w-3.5 h-3.5" /> Approve
            </Button>
          )}
          <Button data-testid="reject-button" variant="outline" size="sm" className="gap-1.5 h-9 text-xs" onClick={() => setRejectOpen(true)}>
            <XCircle className="w-3.5 h-3.5" /> {pending ? 'Reject' : 'Deactivate'}
          </Button>
          <Button data-testid="revoke-button" variant="outline" size="sm" className="gap-1.5 h-9 text-xs" onClick={() => setRevokeOpen(true)}>
            <ShieldOff className="w-3.5 h-3.5" /> Revoke tokens
          </Button>
        </div>
      </header>

      {/* KPI strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="bg-card border border-border/60 rounded-xl p-4">
          <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Wallet</div>
          <div className="font-display text-2xl font-bold tabular-nums mt-1" data-testid="kpi-wallet">
            {paiseToRupees(d.wallet_balance_paise)}
          </div>
        </div>
        <div className="bg-card border border-border/60 rounded-xl p-4">
          <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Bottles with customer</div>
          <div className="font-display text-2xl font-bold tabular-nums mt-1" data-testid="kpi-bottles">
            {d.bottle_balance}
          </div>
        </div>
        <div className="bg-card border border-border/60 rounded-xl p-4">
          <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Active subs</div>
          <div className="font-display text-2xl font-bold tabular-nums mt-1">
            {d.active_subs_count}<span className="text-muted-foreground text-base">/{d.total_subs_count}</span>
          </div>
        </div>
        <div className="bg-card border border-border/60 rounded-xl p-4">
          <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Open invoices</div>
          <div className="font-display text-2xl font-bold tabular-nums mt-1">
            {paiseToRupees(d.open_invoices_paise)}
          </div>
        </div>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="profile" data-testid="customer-tabs">
        <TabsList className="bg-muted">
          <TabsTrigger value="profile" data-testid="tab-profile" className="text-xs">Profile</TabsTrigger>
          <TabsTrigger value="subscriptions" data-testid="tab-subs" className="text-xs">Subscriptions</TabsTrigger>
          <TabsTrigger value="deliveries" data-testid="tab-deliveries" className="text-xs">Deliveries</TabsTrigger>
          <TabsTrigger value="invoices" data-testid="tab-invoices" className="text-xs">Invoices</TabsTrigger>
          <TabsTrigger value="wallet" data-testid="tab-wallet" className="text-xs">Wallet</TabsTrigger>
          <TabsTrigger value="bottles" data-testid="tab-bottles" className="text-xs">Bottles</TabsTrigger>
          <TabsTrigger value="audit" data-testid="tab-audit" className="text-xs">Audit</TabsTrigger>
        </TabsList>

        {/* PROFILE */}
        <TabsContent value="profile" className="mt-4 space-y-3">
          <div className="bg-card border border-border/60 rounded-xl p-4 space-y-3">
            <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Addresses ({d.addresses.length})</div>
            {d.addresses.length === 0 && <div className="text-sm text-muted-foreground">No addresses on file.</div>}
            {d.addresses.map((a) => (
              <div key={a.id} className="flex gap-3 p-3 rounded-lg bg-muted/40 border border-border/50">
                <MapPin className="w-4 h-4 mt-0.5 text-muted-foreground" />
                <div className="flex-1">
                  <div className="font-medium text-sm">
                    {a.line1}{a.line2 ? `, ${a.line2}` : ''}
                  </div>
                  <div className="text-xs text-muted-foreground mt-0.5">
                    {a.area} · {a.city} {a.pincode}
                    {a.is_default && <Badge variant="outline" className="ml-2 rounded-full text-[10px]">default</Badge>}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </TabsContent>

        {/* SUBSCRIPTIONS */}
        <TabsContent value="subscriptions" className="mt-4">
          <div className="bg-card border border-border/60 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-[10px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="text-left px-3 py-2 font-semibold">Product</th>
                  <th className="text-right px-3 py-2 font-semibold">Qty</th>
                  <th className="text-left px-3 py-2 font-semibold">Frequency</th>
                  <th className="text-left px-3 py-2 font-semibold">Status</th>
                  <th className="text-left px-3 py-2 font-semibold">Start</th>
                  <th className="text-right px-3 py-2 font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody>
                {(subs.data || []).map((s: any) => (
                  <tr key={s.id} data-testid={`sub-row-${s.id}`} className="border-t border-border/50 h-[40px]">
                    <td className="px-3 py-1.5 truncate max-w-[220px]">{s.product_id.slice(0, 8)}…</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{s.quantity}</td>
                    <td className="px-3 py-1.5 text-xs">{FREQUENCY_LABEL[s.frequency] || s.frequency}</td>
                    <td className="px-3 py-1.5">
                      <Badge variant="outline" className="rounded-full capitalize text-[10px]">{s.status}</Badge>
                    </td>
                    <td className="px-3 py-1.5 text-xs text-muted-foreground">{formatDate(s.start_date)}</td>
                    <td className="px-3 py-1.5 text-right">
                      <div className="flex gap-1 justify-end">
                        {s.status === 'active' && (
                          <Button data-testid={`sub-pause-${s.id}`} size="sm" variant="ghost" className="h-7 text-xs" onClick={() => setPauseSubId(s.id)}>
                            <PauseCircle className="w-3.5 h-3.5" />
                          </Button>
                        )}
                        {s.status === 'paused' && (
                          <Button data-testid={`sub-resume-${s.id}`} size="sm" variant="ghost" className="h-7 text-xs" onClick={() => resumeSub(s.id)}>
                            <PlayCircle className="w-3.5 h-3.5" />
                          </Button>
                        )}
                        {s.status !== 'cancelled' && (
                          <Button data-testid={`sub-cancel-${s.id}`} size="sm" variant="ghost" className="h-7 text-xs text-accent" onClick={() => setCancelSubId(s.id)}>
                            <Slash className="w-3.5 h-3.5" />
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
                {!subs.isLoading && (subs.data?.length ?? 0) === 0 && (
                  <tr><td colSpan={6} className="px-3 py-10 text-center text-muted-foreground text-sm">No subscriptions yet.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </TabsContent>

        {/* DELIVERIES */}
        <TabsContent value="deliveries" className="mt-4">
          <div className="bg-card border border-border/60 rounded-xl overflow-hidden">
            <table className="w-full text-sm" data-testid="deliveries-table">
              <thead className="bg-muted/40 text-[10px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="text-left px-3 py-2 font-semibold">Date</th>
                  <th className="text-right px-3 py-2 font-semibold">Qty</th>
                  <th className="text-right px-3 py-2 font-semibold">Delivered</th>
                  <th className="text-left px-3 py-2 font-semibold">Status</th>
                  <th className="text-left px-3 py-2 font-semibold">Locked</th>
                </tr>
              </thead>
              <tbody>
                {(deliveries.data || []).map((o: any) => (
                  <tr key={o.id} className="border-t border-border/50 h-[40px]">
                    <td className="px-3 py-1.5 tabular-nums">{formatDate(o.delivery_date)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{o.quantity}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{o.delivered_quantity ?? '—'}</td>
                    <td className="px-3 py-1.5">
                      <Badge variant="outline" className="rounded-full capitalize text-[10px]">{o.status}</Badge>
                    </td>
                    <td className="px-3 py-1.5 text-xs text-muted-foreground">{o.cutoff_locked_at ? 'yes' : '—'}</td>
                  </tr>
                ))}
                {!deliveries.isLoading && (deliveries.data?.length ?? 0) === 0 && (
                  <tr><td colSpan={5} className="px-3 py-10 text-center text-muted-foreground text-sm">No deliveries in the last 60 days.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </TabsContent>

        {/* INVOICES */}
        <TabsContent value="invoices" className="mt-4">
          <div className="bg-card border border-border/60 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-[10px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="text-left px-3 py-2 font-semibold">Period</th>
                  <th className="text-right px-3 py-2 font-semibold">Total</th>
                  <th className="text-left px-3 py-2 font-semibold">Status</th>
                  <th className="text-left px-3 py-2 font-semibold">Issued</th>
                  <th className="text-left px-3 py-2 font-semibold">Due</th>
                </tr>
              </thead>
              <tbody>
                {(invoices.data || []).map((i: any) => (
                  <tr key={i.id} className="border-t border-border/50 h-[40px]">
                    <td className="px-3 py-1.5 tabular-nums">{String(i.month).padStart(2, '0')}/{i.year}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums font-semibold">{paiseToRupees(i.total_paise)}</td>
                    <td className="px-3 py-1.5"><Badge variant="outline" className="rounded-full capitalize text-[10px]">{i.status}</Badge></td>
                    <td className="px-3 py-1.5 text-xs text-muted-foreground">{i.issued_at ? formatDate(i.issued_at) : '—'}</td>
                    <td className="px-3 py-1.5 text-xs text-muted-foreground">{i.due_date ? formatDate(i.due_date) : '—'}</td>
                  </tr>
                ))}
                {!invoices.isLoading && (invoices.data?.length ?? 0) === 0 && (
                  <tr><td colSpan={5} className="px-3 py-10 text-center text-muted-foreground text-sm">No invoices yet.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </TabsContent>

        {/* WALLET */}
        <TabsContent value="wallet" className="mt-4 space-y-3">
          <div className="flex items-start justify-between bg-card border border-border/60 rounded-xl p-4">
            <div>
              <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Current balance</div>
              <div className="font-display text-3xl font-bold tabular-nums mt-1">
                {paiseToRupees(wallet.data?.balance_paise ?? d.wallet_balance_paise)}
              </div>
            </div>
            <Button data-testid="wallet-adjust-button" onClick={() => setWalletOpen(true)} size="sm" className="gap-1.5 h-9 text-xs">
              <Wallet className="w-3.5 h-3.5" /> Manual adjustment
            </Button>
          </div>
          <div className="bg-card border border-border/60 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-[10px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="text-left px-3 py-2 font-semibold">Date</th>
                  <th className="text-right px-3 py-2 font-semibold">Change</th>
                  <th className="text-right px-3 py-2 font-semibold">Balance after</th>
                  <th className="text-left px-3 py-2 font-semibold">Reason</th>
                </tr>
              </thead>
              <tbody>
                {(wallet.data?.items || []).map((t: any) => (
                  <tr key={t.id} className="border-t border-border/50 h-[40px]">
                    <td className="px-3 py-1.5 text-xs text-muted-foreground">{formatDateTime(t.created_at)}</td>
                    <td className={`px-3 py-1.5 text-right tabular-nums font-semibold ${t.change_paise >= 0 ? 'text-secondary' : 'text-accent'}`}>
                      {t.change_paise >= 0 ? '+' : ''}{paiseToRupees(t.change_paise)}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{paiseToRupees(t.balance_after_paise)}</td>
                    <td className="px-3 py-1.5 text-xs text-muted-foreground truncate max-w-[380px]">{t.reason}</td>
                  </tr>
                ))}
                {!wallet.isLoading && (wallet.data?.items?.length ?? 0) === 0 && (
                  <tr><td colSpan={4} className="px-3 py-10 text-center text-muted-foreground text-sm">No wallet transactions.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </TabsContent>

        {/* BOTTLES */}
        <TabsContent value="bottles" className="mt-4 space-y-3">
          <div className="flex items-start justify-between bg-card border border-border/60 rounded-xl p-4">
            <div>
              <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Bottles with customer</div>
              <div className="font-display text-3xl font-bold tabular-nums mt-1">
                {bottles.data?.balance ?? d.bottle_balance}
              </div>
            </div>
            <Button data-testid="bottle-adjust-button" onClick={() => setBottleOpen(true)} size="sm" className="gap-1.5 h-9 text-xs">
              <Activity className="w-3.5 h-3.5" /> Manual adjustment
            </Button>
          </div>
          <div className="bg-card border border-border/60 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-[10px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="text-left px-3 py-2 font-semibold">Date</th>
                  <th className="text-right px-3 py-2 font-semibold">Change</th>
                  <th className="text-left px-3 py-2 font-semibold">Reason</th>
                  <th className="text-left px-3 py-2 font-semibold">Note</th>
                </tr>
              </thead>
              <tbody>
                {(bottles.data?.items || []).map((t: any) => (
                  <tr key={t.id} className="border-t border-border/50 h-[40px]">
                    <td className="px-3 py-1.5 text-xs text-muted-foreground">{formatDateTime(t.created_at)}</td>
                    <td className={`px-3 py-1.5 text-right tabular-nums font-semibold ${t.change >= 0 ? 'text-primary' : 'text-secondary'}`}>
                      {t.change >= 0 ? '+' : ''}{t.change}
                    </td>
                    <td className="px-3 py-1.5 capitalize text-xs">{t.reason}</td>
                    <td className="px-3 py-1.5 text-xs text-muted-foreground truncate max-w-[380px]">{t.note || '—'}</td>
                  </tr>
                ))}
                {!bottles.isLoading && (bottles.data?.items?.length ?? 0) === 0 && (
                  <tr><td colSpan={4} className="px-3 py-10 text-center text-muted-foreground text-sm">No bottle ledger entries.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </TabsContent>

        {/* AUDIT */}
        <TabsContent value="audit" className="mt-4">
          <div className="bg-card border border-border/60 rounded-xl overflow-hidden">
            <table className="w-full text-sm" data-testid="customer-audit-table">
              <thead className="bg-muted/40 text-[10px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="text-left px-3 py-2 font-semibold">When</th>
                  <th className="text-left px-3 py-2 font-semibold">Action</th>
                  <th className="text-left px-3 py-2 font-semibold">Actor</th>
                  <th className="text-left px-3 py-2 font-semibold">Reason</th>
                </tr>
              </thead>
              <tbody>
                {(audit.data || []).map((a: any) => (
                  <tr key={a.id} className="border-t border-border/50 h-[40px]">
                    <td className="px-3 py-1.5 text-xs text-muted-foreground tabular-nums">{formatDateTime(a.created_at)}</td>
                    <td className="px-3 py-1.5 font-mono text-[11px]">{a.action}</td>
                    <td className="px-3 py-1.5 text-xs capitalize">{a.actor_role || 'system'}</td>
                    <td className="px-3 py-1.5 text-xs text-muted-foreground truncate max-w-[380px]">{a.reason || '—'}</td>
                  </tr>
                ))}
                {!audit.isLoading && (audit.data?.length ?? 0) === 0 && (
                  <tr><td colSpan={4} className="px-3 py-10 text-center text-muted-foreground text-sm">No audit entries for this customer yet.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </TabsContent>
      </Tabs>

      {/* Modals */}
      <AdjustmentModal
        open={walletOpen}
        onOpenChange={setWalletOpen}
        kind="wallet"
        customerId={id}
        currentBalance={wallet.data?.balance_paise ?? d.wallet_balance_paise}
        onDone={() => { qc.invalidateQueries({ queryKey: ['admin', 'customer', id] }); }}
      />
      <AdjustmentModal
        open={bottleOpen}
        onOpenChange={setBottleOpen}
        kind="bottle"
        customerId={id}
        currentBalance={bottles.data?.balance ?? d.bottle_balance}
        onDone={() => { qc.invalidateQueries({ queryKey: ['admin', 'customer', id] }); }}
      />
      <ReasonDialog
        open={rejectOpen}
        onOpenChange={setRejectOpen}
        title={pending ? 'Reject customer application' : 'Deactivate customer'}
        description="This marks the customer inactive and writes an audit entry."
        actionLabel="Confirm rejection"
        destructive
        onConfirm={reject}
      />
      <ReasonDialog
        open={revokeOpen}
        onOpenChange={setRevokeOpen}
        title="Revoke all tokens"
        description="The customer will be logged out of every device. Requires admin reactivation to log back in."
        actionLabel="Revoke"
        destructive
        onConfirm={revokeTokens}
      />
      <ReasonDialog
        open={!!pauseSubId}
        onOpenChange={(v) => { if (!v) setPauseSubId(null); }}
        title="Pause subscription"
        description="Pauses deliveries. The customer can resume later (admin override)."
        actionLabel="Pause"
        onConfirm={async (r) => { if (pauseSubId) { await pauseSub(pauseSubId, r); setPauseSubId(null); } }}
      />
      <ReasonDialog
        open={!!cancelSubId}
        onOpenChange={(v) => { if (!v) setCancelSubId(null); }}
        title="Cancel subscription"
        description="Permanently stops this subscription. Past deliveries and invoices are retained."
        actionLabel="Cancel subscription"
        destructive
        onConfirm={async (r) => { if (cancelSubId) { await cancelSub(cancelSubId, r); setCancelSubId(null); } }}
      />
    </div>
  );
}
