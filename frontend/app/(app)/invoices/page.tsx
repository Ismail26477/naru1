"use client";
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { Receipt, ChevronRight } from 'lucide-react';
import { apiFetch } from '@/lib/api';
import { paiseToRupees, formatDate } from '@/lib/format';
import { Badge } from '@/components/ui/badge';
import { RowSkeleton } from '@/components/skeletons';

const STATUS_COLOR: Record<string, string> = {
  paid: 'bg-secondary/15 text-secondary-foreground border-secondary/30',
  issued: 'bg-primary/10 text-primary border-primary/30',
  overdue: 'bg-accent/10 text-accent border-accent/30',
  draft: 'bg-muted text-muted-foreground border-border',
};

const MONTHS = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export default function InvoicesPage() {
  const q = useQuery({ queryKey: ['invoices'], queryFn: () => apiFetch<any[]>('/me/invoices') });
  const items = q.data || [];
  const outstanding = items.filter((i) => i.status === 'issued' || i.status === 'overdue')
    .reduce((acc, i) => acc + (i.total_paise || 0), 0);

  return (
    <div className="p-5 pb-4 animate-fade-in">
      <header className="mb-5">
        <div className="text-xs text-muted-foreground uppercase tracking-widest">Billing</div>
        <h1 className="text-3xl font-display font-bold tracking-tight mt-0.5">Invoices</h1>
      </header>

      <div className="bg-gradient-to-br from-primary to-primary/80 text-primary-foreground rounded-3xl p-5 mb-5 relative overflow-hidden">
        <div aria-hidden className="absolute -right-8 -top-8 w-32 h-32 rounded-full bg-white/10 blur-2xl" />
        <div className="relative">
          <div className="text-xs opacity-80 uppercase tracking-widest">Outstanding</div>
          <div className="font-display text-4xl font-bold mt-1" data-testid="invoices-outstanding-value">
            {paiseToRupees(outstanding)}
          </div>
          <div className="text-xs opacity-80 mt-1">{items.filter((i) => i.status === 'issued' || i.status === 'overdue').length} unpaid</div>
        </div>
      </div>

      {q.isLoading && <div className="space-y-2"><RowSkeleton /><RowSkeleton /></div>}

      <div className="space-y-2">
        {items.map((inv: any) => (
          <Link
            key={inv.id}
            data-testid={`invoice-row-${inv.id}`}
            href={`/invoices/${inv.id}`}
            className="flex items-center gap-3 p-4 bg-card rounded-2xl border border-border/40 hover:shadow-sm transition-shadow"
          >
            <div className="w-12 h-12 rounded-xl bg-muted flex items-center justify-center">
              <Receipt className="w-5 h-5 text-muted-foreground" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="font-display font-semibold">{MONTHS[inv.month]} {inv.year}</div>
              <div className="text-xs text-muted-foreground">
                {inv.issued_at ? `Issued ${formatDate(inv.issued_at, 'd MMM')}` : 'Draft'}
                {inv.due_date && ` · due ${formatDate(inv.due_date, 'd MMM')}`}
              </div>
            </div>
            <div className="text-right flex flex-col items-end gap-1.5">
              <div className="font-display font-bold">{paiseToRupees(inv.total_paise)}</div>
              <Badge className={`rounded-full text-[10px] capitalize border ${STATUS_COLOR[inv.status] || ''}`}>{inv.status}</Badge>
            </div>
            <ChevronRight className="w-4 h-4 text-muted-foreground" />
          </Link>
        ))}
        {!q.isLoading && !items.length && (
          <div className="text-center py-12 text-sm text-muted-foreground">
            <Receipt className="w-10 h-10 mx-auto mb-2 opacity-40" />
            No invoices yet. Monthly bills appear on the 1st.
          </div>
        )}
      </div>
    </div>
  );
}
