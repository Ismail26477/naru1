"use client";
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Download, Loader2 } from 'lucide-react';
import { apiFetch } from '@/lib/api';
import { paiseToRupees, formatDate } from '@/lib/format';
import { Badge } from '@/components/ui/badge';

const MONTHS = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export default function InvoiceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const inv = useQuery({ queryKey: ['invoice', id], queryFn: () => apiFetch<any>(`/me/invoices/${id}`) });
  const products = useQuery({ queryKey: ['products'], queryFn: () => apiFetch<any[]>('/products') });
  const prodMap = new Map((products.data || []).map((p) => [p.id, p]));

  if (inv.isLoading) return <div className="p-10 flex justify-center"><Loader2 className="w-5 h-5 animate-spin" /></div>;
  if (!inv.data) return <div className="p-10 text-center text-muted-foreground">Invoice not found.</div>;
  const i = inv.data;

  return (
    <div className="pb-8 animate-fade-in">
      <div className="sticky top-0 z-40 bg-background/95 backdrop-blur border-b border-border/50 px-4 py-3 flex items-center gap-3">
        <button onClick={() => router.back()} className="w-9 h-9 rounded-full bg-muted flex items-center justify-center" data-testid="back-button">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div className="flex-1">
          <div className="font-display font-semibold">Invoice · {MONTHS[i.month]} {i.year}</div>
          <div className="text-xs text-muted-foreground">{i.issued_at ? formatDate(i.issued_at, 'd MMM yyyy') : 'Draft'}</div>
        </div>
        <Badge className="rounded-full capitalize" variant={i.status === 'paid' ? 'default' : 'outline'}>{i.status}</Badge>
      </div>

      <div className="p-5 space-y-5">
        {/* Amount card */}
        <div className="bg-card rounded-3xl p-6 border border-border/50">
          <div className="text-xs text-muted-foreground uppercase tracking-widest">Total</div>
          <div className="font-display text-5xl font-bold mt-2" data-testid="invoice-total-value">{paiseToRupees(i.total_paise)}</div>
          <div className="mt-4 space-y-1.5 text-sm">
            <div className="flex justify-between"><span className="text-muted-foreground">Subtotal</span><span className="font-mono">{paiseToRupees(i.subtotal_paise)}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Adjustments</span><span className="font-mono">{paiseToRupees(i.adjustments_paise)}</span></div>
            <div className="flex justify-between pt-2 border-t font-semibold"><span>Total</span><span className="font-mono">{paiseToRupees(i.total_paise)}</span></div>
          </div>
          {i.due_date && (
            <div className="mt-4 text-xs text-muted-foreground">Due by <span className="font-semibold text-foreground">{formatDate(i.due_date, 'd MMM yyyy')}</span></div>
          )}
        </div>

        {/* Line items */}
        <div className="bg-card rounded-3xl border border-border/50 overflow-hidden">
          <div className="p-4 border-b border-border/50">
            <div className="font-display font-semibold">Line items</div>
            <div className="text-xs text-muted-foreground">{i.line_items?.length ?? 0} deliveries</div>
          </div>
          <div className="divide-y divide-border/40">
            {(i.line_items || []).map((li: any) => {
              const p = prodMap.get(li.product_id);
              return (
                <div key={li.id} className="flex items-center justify-between p-4 text-sm">
                  <div>
                    <div className="font-medium">{p?.name || 'Product'}</div>
                    <div className="text-xs text-muted-foreground">{formatDate(li.date, 'd MMM')} · Qty {li.quantity} · {paiseToRupees(li.price_paise)}</div>
                  </div>
                  <div className="font-mono font-semibold">{paiseToRupees(li.total_paise)}</div>
                </div>
              );
            })}
          </div>
        </div>

        <button
          type="button"
          data-testid="download-invoice-pdf-link"
          onClick={() => {
            const token = typeof window !== 'undefined' ? localStorage.getItem('posuhtik.access_token') : null;
            const API_BASE = (process.env.NEXT_PUBLIC_BACKEND_URL || '').replace(/\/$/, '') + '/api';
            const filename = `posuhtik_invoice_${i.year}_${String(i.month).padStart(2, '0')}_${i.id.slice(0, 8)}.pdf`;
            fetch(`${API_BASE}/me/invoices/${i.id}/pdf?download=true`, {
              headers: token ? { Authorization: `Bearer ${token}` } : {},
            }).then(async (r) => {
              if (!r.ok) return;
              const blob = await r.blob();
              const href = URL.createObjectURL(blob);
              const a = document.createElement('a');
              a.href = href; a.download = filename;
              document.body.appendChild(a); a.click(); document.body.removeChild(a);
              URL.revokeObjectURL(href);
            });
          }}
          className="flex items-center justify-center gap-2 bg-primary text-primary-foreground py-4 rounded-full font-semibold w-full"
        >
          <Download className="w-4 h-4" /> Download PDF
        </button>
      </div>
    </div>
  );
}
