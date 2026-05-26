"use client";
import { useEffect, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import Link from 'next/link';
import {
  LayoutDashboard,
  Users,
  Route,
  Truck,
  Package,
  Receipt,
  BarChart3,
  LogOut,
  Loader2,
  Menu,
  X,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { auth } from '@/lib/api';

const NAV = [
  { href: '/admin/dashboard', label: 'Dashboard', icon: LayoutDashboard, testid: 'nav-dashboard' },
  { href: '/admin/customers', label: 'Customers', icon: Users, testid: 'nav-customers' },
  { href: '/admin/routes', label: 'Routes', icon: Route, testid: 'nav-routes' },
  { href: '/admin/delivery-orders', label: 'Deliveries', icon: Truck, testid: 'nav-delivery-orders' },
  { href: '/admin/products', label: 'Products', icon: Package, testid: 'nav-products' },
  { href: '/admin/billing', label: 'Billing', icon: Receipt, testid: 'nav-billing' },
  { href: '/admin/reports', label: 'Reports', icon: BarChart3, testid: 'nav-reports' },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [ready, setReady] = useState(false);
  const [user, setUser] = useState<{ name: string | null; role: string } | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);

  // Login page is public — skip the guard entirely.
  const isLoginPage = pathname === '/admin/login';

  useEffect(() => {
    if (isLoginPage) {
      setReady(true);
      return;
    }
    const u = auth.getUser();
    if (!u) {
      router.replace('/admin/login');
      return;
    }
    if (u.role !== 'admin') {
      auth.logout();
      // Hard redirect (not router.replace) to guarantee the ?error=not_admin
      // query string is preserved and any in-memory app state is flushed.
      if (typeof window !== 'undefined') {
        window.location.replace('/admin/login?error=not_admin');
      }
      return;
    }
    setUser({ name: u.name, role: u.role });
    setReady(true);
  }, [pathname, router, isLoginPage]);

  // Close mobile drawer on navigation
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  if (!ready) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[hsl(30_15%_96%)]">
        <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  // Login page renders without shell
  if (isLoginPage) {
    return <>{children}</>;
  }

  function handleLogout() {
    auth.logout();
    router.replace('/admin/login');
  }

  return (
    <div className="min-h-screen bg-[hsl(30_15%_96%)] text-foreground">
      {/* Topbar */}
      <header
        data-testid="admin-topbar"
        className="sticky top-0 z-30 flex items-center justify-between h-14 px-4 md:pl-64 border-b border-border/60 bg-[hsl(44_40%_98%)]/90 backdrop-blur"
      >
        <button
          className="md:hidden p-2 -ml-2 rounded-lg hover:bg-muted"
          onClick={() => setMobileOpen((v) => !v)}
          data-testid="admin-menu-toggle"
          aria-label="Toggle navigation"
        >
          {mobileOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
        </button>
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-foreground text-background flex items-center justify-center font-display font-bold text-sm">
            P
          </div>
          <div className="hidden sm:block">
            <div className="font-display font-semibold text-sm leading-none">Posuhtik Admin</div>
            <div className="text-[10px] text-muted-foreground uppercase tracking-widest">Nagpur · Ops</div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-right hidden sm:block">
            <div className="text-xs font-semibold leading-none" data-testid="admin-user-name">
              {user?.name ?? 'Admin'}
            </div>
            <div className="text-[10px] text-muted-foreground uppercase tracking-wider mt-0.5">admin</div>
          </div>
          <button
            onClick={handleLogout}
            data-testid="admin-logout-button"
            className="p-2 rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground"
            aria-label="Log out"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </header>

      {/* Sidebar (desktop + mobile drawer) */}
      <aside
        data-testid="admin-sidebar"
        className={cn(
          'fixed inset-y-0 left-0 z-40 w-64 bg-foreground text-background/90 border-r border-black/20 flex flex-col',
          'transition-transform duration-200',
          mobileOpen ? 'translate-x-0' : '-translate-x-full',
          'md:translate-x-0',
        )}
      >
        <div className="h-14 flex items-center px-5 border-b border-white/10">
          <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center font-display font-bold text-sm text-primary-foreground">
            P
          </div>
          <div className="ml-3">
            <div className="font-display font-bold text-sm text-background leading-none">Posuhtik</div>
            <div className="text-[10px] text-background/50 uppercase tracking-widest mt-0.5">Admin console</div>
          </div>
        </div>
        <nav className="flex-1 p-3 space-y-0.5 overflow-y-auto">
          {NAV.map((it) => {
            const active = pathname === it.href || pathname?.startsWith(it.href + '/');
            const Icon = it.icon;
            return (
              <Link
                key={it.href}
                href={it.href}
                data-testid={it.testid}
                className={cn(
                  'flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
                  active
                    ? 'bg-primary text-primary-foreground shadow-sm'
                    : 'text-background/70 hover:bg-white/5 hover:text-background',
                )}
              >
                <Icon className="w-4 h-4 flex-shrink-0" />
                {it.label}
              </Link>
            );
          })}
        </nav>
        <div className="p-3 border-t border-white/10 text-[10px] text-background/40 uppercase tracking-widest">
          v0.2 · Phase 2B
        </div>
      </aside>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="md:hidden fixed inset-0 z-30 bg-black/40 backdrop-blur-sm"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Main */}
      <main className="md:pl-64">
        <div className="p-4 md:p-6 lg:p-8 max-w-[1400px]">{children}</div>
      </main>
    </div>
  );
}
