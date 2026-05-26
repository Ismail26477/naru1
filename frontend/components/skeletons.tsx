"use client";
import { Skeleton } from '@/components/ui/skeleton';

export function CardSkeleton() {
  return (
    <div className="bg-card rounded-2xl p-5 border border-border/50 space-y-3">
      <Skeleton className="h-4 w-32" />
      <Skeleton className="h-6 w-48" />
      <Skeleton className="h-4 w-24" />
    </div>
  );
}

export function RowSkeleton() {
  return (
    <div className="flex items-center gap-3 p-4 bg-card rounded-xl">
      <Skeleton className="w-12 h-12 rounded-xl" />
      <div className="flex-1 space-y-2">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-3 w-24" />
      </div>
      <Skeleton className="h-6 w-16 rounded-full" />
    </div>
  );
}
