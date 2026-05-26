"use client";
import { useEffect, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { auth } from '@/lib/api';
import BottomNav from '@/components/bottom-nav';
import { Loader2 } from 'lucide-react';

export default function AuthedLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const u = auth.getUser();
    if (!u) {
      router.replace('/login');
      return;
    }
    if (u.role === 'admin') {
      router.replace('/admin/dashboard');
      return;
    }
    setReady(true);
  }, [router, pathname]);

  if (!ready) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="max-w-md mx-auto min-h-screen bg-background sm:border-x sm:border-border shadow-xl relative pb-safe">
      {children}
      <BottomNav />
    </div>
  );
}
