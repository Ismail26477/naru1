// Formatting helpers — ₹ paise, IST dates, friendly distances.
import { format, formatDistanceToNowStrict, parseISO } from 'date-fns';

export function paiseToRupees(paise: number): string {
  const rupees = paise / 100;
  return '₹' + rupees.toLocaleString('en-IN', { maximumFractionDigits: 2, minimumFractionDigits: 0 });
}

export function formatDate(iso: string | Date, fmt = 'dd MMM yyyy'): string {
  const d = typeof iso === 'string' ? parseISO(iso) : iso;
  return format(d, fmt);
}

export function formatDateTime(iso: string | Date): string {
  const d = typeof iso === 'string' ? parseISO(iso) : iso;
  return format(d, "dd MMM yyyy, h:mm a");
}

export function humanDate(iso: string | Date): string {
  const d = typeof iso === 'string' ? parseISO(iso) : iso;
  return formatDistanceToNowStrict(d, { addSuffix: true });
}

export function initials(name: string | null | undefined): string {
  if (!name) return '?';
  const parts = name.trim().split(/\s+/);
  return (parts[0][0] + (parts[1]?.[0] ?? '')).toUpperCase();
}

export const FREQUENCY_LABEL: Record<string, string> = {
  daily: 'Daily',
  alternate: 'Alternate days',
  weekly: 'Weekly',
  custom: 'Custom',
};

export const STATUS_LABEL: Record<string, string> = {
  active: 'Active',
  paused: 'Paused',
  cancelled: 'Cancelled',
  pending: 'Pending',
  delivered: 'Delivered',
  skipped: 'Skipped',
  failed: 'Failed',
  draft: 'Draft',
  issued: 'Issued',
  paid: 'Paid',
  overdue: 'Overdue',
};

export const WEEKDAY_SHORT = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
