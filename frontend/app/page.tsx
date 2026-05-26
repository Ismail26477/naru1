"use client";
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { auth } from '@/lib/api';

export default function RootIndex() {
  const router = useRouter();
  useEffect(() => {
    const u = auth.getUser();
    if (!u) {
      router.replace('/login');
    } else if (u.role === 'admin') {
      router.replace('/admin/dashboard');
    } else {
      router.replace('/dashboard');
    }
  }, [router]);
  return (
    <div className="flex items-center justify-center min-h-screen">
      <div className="text-muted-foreground text-sm">Loading…</div>
    </div>
  );
}
