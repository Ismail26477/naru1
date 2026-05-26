"use client";
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Home, CalendarDays, Receipt, User, Package } from 'lucide-react';
import { cn } from '@/lib/utils';

const items = [
  { href: '/dashboard', label: 'Home', icon: Home, testid: 'dashboard-tab' },
  { href: '/subscriptions', label: 'Subs', icon: Package, testid: 'subscriptions-tab' },
  { href: '/calendar', label: 'Calendar', icon: CalendarDays, testid: 'calendar-tab' },
  { href: '/invoices', label: 'Bills', icon: Receipt, testid: 'invoices-tab' },
  { href: '/profile', label: 'Profile', icon: User, testid: 'profile-tab' },
];

export default function BottomNav() {
  const pathname = usePathname();
  return (
    <nav className="fixed bottom-0 left-1/2 -translate-x-1/2 w-full max-w-md bg-white/95 backdrop-blur border-t border-border z-50 rounded-t-2xl shadow-[0_-8px_30px_-15px_rgba(0,0,0,0.15)]">
      <ul className="flex justify-between items-stretch px-2 py-2">
        {items.map((it) => {
          const active = pathname === it.href || pathname?.startsWith(it.href + '/');
          const Icon = it.icon;
          return (
            <li key={it.href} className="flex-1">
              <Link
                href={it.href}
                data-testid={it.testid}
                className={cn(
                  'flex flex-col items-center justify-center gap-1 py-2 rounded-xl transition-all',
                  active ? 'text-primary' : 'text-muted-foreground hover:text-foreground',
                )}
              >
                <Icon className={cn('w-5 h-5 transition-transform', active && 'scale-110')} />
                <span className={cn('text-[10px] font-semibold tracking-wide', active && 'text-primary')}>
                  {it.label}
                </span>
                {active && <div className="w-1 h-1 rounded-full bg-primary -mt-0.5" />}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
