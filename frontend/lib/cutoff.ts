// Cutoff logic mirroring backend — for UI countdown & locked-day indication.
// Cutoff for delivery date D = day (D-1) at 20:00 IST.

const IST_OFFSET_MIN = 330; // +5:30
const CUTOFF_HOUR_IST = 20;

/** Convert a Date to "IST wall clock time" parts. */
export function nowIstParts(): { y: number; m: number; d: number; h: number; min: number } {
  const now = new Date();
  const utcMs = now.getTime();
  const ist = new Date(utcMs + IST_OFFSET_MIN * 60_000);
  return {
    y: ist.getUTCFullYear(),
    m: ist.getUTCMonth() + 1,
    d: ist.getUTCDate(),
    h: ist.getUTCHours(),
    min: ist.getUTCMinutes(),
  };
}

/** The cutoff moment (UTC Date) for a given delivery ISO date string (yyyy-mm-dd). */
export function cutoffForDelivery(deliveryYmd: string): Date {
  const [y, m, d] = deliveryYmd.split('-').map(Number);
  // cutoff = (D-1) 20:00 IST → convert to UTC.
  // 20:00 IST = 14:30 UTC. We compute (D at 00:00 UTC) − 1 day + (20:00 IST − offset) in ms.
  return new Date(
    Date.UTC(y, m - 1, d, 0, 0, 0)
      - 24 * 60 * 60 * 1000
      + (CUTOFF_HOUR_IST * 60 - IST_OFFSET_MIN) * 60_000,
  );
}

/** true iff today IST < deliveryYmd-1 at 20:00 IST (can still modify). */
export function isModifiable(deliveryYmd: string, now = new Date()): boolean {
  return now.getTime() < cutoffForDelivery(deliveryYmd).getTime();
}

/** Next cutoff moment for tomorrow IST — for dashboard countdown. */
export function tomorrowIstYmd(): string {
  const p = nowIstParts();
  const d = new Date(Date.UTC(p.y, p.m - 1, p.d));
  d.setUTCDate(d.getUTCDate() + 1);
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, '0');
  const dd = String(d.getUTCDate()).padStart(2, '0');
  return `${y}-${m}-${dd}`;
}

export function todayIstYmd(): string {
  const p = nowIstParts();
  return `${p.y}-${String(p.m).padStart(2, '0')}-${String(p.d).padStart(2, '0')}`;
}

export function addDaysYmd(ymd: string, delta: number): string {
  const [y, m, d] = ymd.split('-').map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  dt.setUTCDate(dt.getUTCDate() + delta);
  const ny = dt.getUTCFullYear();
  const nm = String(dt.getUTCMonth() + 1).padStart(2, '0');
  const nd = String(dt.getUTCDate()).padStart(2, '0');
  return `${ny}-${nm}-${nd}`;
}

/** Format milliseconds as Hh Mm Ss for the countdown. */
export function formatCountdown(ms: number): string {
  if (ms <= 0) return '00:00:00';
  const s = Math.floor(ms / 1000);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (n: number) => n.toString().padStart(2, '0');
  return `${pad(h)}:${pad(m)}:${pad(sec)}`;
}
