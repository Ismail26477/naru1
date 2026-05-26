"use client";
import { Suspense, useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { ShieldCheck, Phone, ArrowRight, Loader2, AlertTriangle } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { InputOTP, InputOTPGroup, InputOTPSlot } from '@/components/ui/input-otp';
import { apiFetch, auth } from '@/lib/api';

function AdminLoginInner() {
  const router = useRouter();
  const params = useSearchParams();
  const [phone, setPhone] = useState('');
  const [otp, setOtp] = useState('');
  const [step, setStep] = useState<'phone' | 'otp'>('phone');
  const [loading, setLoading] = useState(false);
  const [devOtp, setDevOtp] = useState<string | null>(null);
  const [banner, setBanner] = useState<string | null>(null);

  const sanitizedPhone = phone.startsWith('+') ? phone : phone.length === 10 ? `+91${phone}` : `+${phone}`;

  useEffect(() => {
    if (params.get('error') === 'not_admin') {
      setBanner('This account does not have admin access.');
    }
  }, [params]);

  async function requestOtp() {
    if (phone.length < 10) {
      toast.error('Enter a valid phone number');
      return;
    }
    setLoading(true);
    try {
      const r = await apiFetch<{ otp: string | null; expires_in_seconds: number }>(
        '/auth/request-otp',
        { method: 'POST', body: { phone: sanitizedPhone }, auth: false },
      );
      setDevOtp(r.otp);
      setStep('otp');
      toast.success('OTP sent', { description: r.otp ? `Dev OTP: ${r.otp} or 123456` : undefined });
    } catch (e: any) {
      toast.error(e.message || 'Failed to send OTP');
    } finally {
      setLoading(false);
    }
  }

  async function verifyOtp(code: string) {
    setLoading(true);
    try {
      const r = await apiFetch<{
        access_token: string;
        refresh_token: string;
        role: string;
        user_id: string;
        name: string | null;
        approved: boolean;
      }>('/auth/verify-otp', {
        method: 'POST',
        body: { phone: sanitizedPhone, otp: code },
        auth: false,
      });
      if (r.role !== 'admin') {
        setBanner('This account does not have admin access.');
        toast.error('Admin access required', {
          description: 'Please sign in with an admin account.',
        });
        setOtp('');
        return; // token intentionally NOT stored
      }
      auth.setTokens(r.access_token, r.refresh_token, {
        user_id: r.user_id,
        role: r.role,
        name: r.name,
        approved: r.approved,
      });
      toast.success('Welcome back, admin.');
      router.replace('/admin/dashboard');
    } catch (e: any) {
      toast.error(e.message || 'Invalid OTP');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-foreground text-background relative overflow-hidden flex items-center justify-center px-6 py-12">
      {/* Atmosphere */}
      <div aria-hidden className="absolute -top-40 -right-40 w-[28rem] h-[28rem] rounded-full bg-primary/15 blur-[120px]" />
      <div aria-hidden className="absolute -bottom-40 -left-40 w-[28rem] h-[28rem] rounded-full bg-secondary/10 blur-[120px]" />
      <div
        aria-hidden
        className="absolute inset-0 opacity-[0.08]"
        style={{
          backgroundImage:
            'repeating-linear-gradient(90deg, transparent 0 40px, rgba(255,255,255,0.5) 40px 41px)',
        }}
      />

      <div className="relative z-10 w-full max-w-md">
        <div className="flex items-center gap-3 mb-12">
          <div className="w-10 h-10 rounded-xl bg-primary flex items-center justify-center">
            <ShieldCheck className="w-5 h-5 text-primary-foreground" />
          </div>
          <div>
            <div className="font-display font-bold text-xl leading-none">Posuhtik Admin</div>
            <div className="text-[10px] uppercase tracking-widest text-background/50 mt-1">
              Operations console · restricted
            </div>
          </div>
        </div>

        {banner && (
          <div
            data-testid="admin-login-error-banner"
            className="mb-6 flex items-start gap-3 p-4 rounded-xl bg-accent/15 border border-accent/30 text-sm"
          >
            <AlertTriangle className="w-4 h-4 mt-0.5 text-accent flex-shrink-0" />
            <div>
              <div className="font-semibold text-background">Access denied</div>
              <div className="text-background/70 mt-0.5">{banner}</div>
            </div>
          </div>
        )}

        {step === 'phone' && (
          <>
            <h1 className="font-display text-3xl font-bold leading-tight mb-2">
              Sign in to continue.
            </h1>
            <p className="text-background/60 mb-10 leading-relaxed text-sm">
              Enter your admin phone number. A one-time code will be sent to verify your identity.
            </p>

            <label className="block text-[10px] font-semibold uppercase tracking-widest text-background/50 mb-2">
              Phone number
            </label>
            <div className="relative">
              <span className="absolute inset-y-0 left-4 flex items-center text-background/40">
                <Phone className="w-4 h-4" />
              </span>
              <Input
                data-testid="admin-login-phone-input"
                inputMode="tel"
                autoComplete="tel"
                placeholder="+91 90000 00001"
                value={phone}
                onChange={(e) => setPhone(e.target.value.replace(/[^\d+]/g, ''))}
                className="pl-11 h-12 text-base rounded-lg bg-white/5 border-white/10 text-background placeholder:text-background/30 focus-visible:border-primary"
              />
            </div>

            <Button
              data-testid="admin-login-send-otp-button"
              onClick={requestOtp}
              disabled={loading}
              className="mt-8 w-full h-12 rounded-lg text-sm font-semibold"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <>Send one-time code <ArrowRight className="w-4 h-4 ml-2" /></>}
            </Button>

            <div className="mt-10 text-center text-[10px] uppercase tracking-widest text-background/40">
              Dev build · fixed OTP <span className="font-mono text-background/70">123456</span>
            </div>
          </>
        )}

        {step === 'otp' && (
          <>
            <h1 className="font-display text-3xl font-bold mb-2">Enter 6-digit code</h1>
            <p className="text-background/60 mb-8 text-sm">
              Sent to <span className="font-semibold text-background">{sanitizedPhone}</span>.{' '}
              <button onClick={() => { setStep('phone'); setOtp(''); }} className="text-primary font-semibold hover:underline">
                Change
              </button>
            </p>

            <InputOTP
              data-testid="admin-login-otp-input"
              maxLength={6}
              value={otp}
              onChange={(v) => {
                setOtp(v);
                if (v.length === 6) verifyOtp(v);
              }}
              autoFocus
            >
              <InputOTPGroup className="gap-2 w-full justify-between">
                {[0, 1, 2, 3, 4, 5].map((i) => (
                  <InputOTPSlot
                    key={i}
                    index={i}
                    className="w-12 h-14 text-xl font-mono rounded-lg border-2 bg-white/5 border-white/10 text-background"
                  />
                ))}
              </InputOTPGroup>
            </InputOTP>

            {devOtp && (
              <div className="mt-6 p-4 rounded-lg bg-white/5 border border-white/10 text-sm">
                <div className="font-semibold text-background mb-1">Dev helper</div>
                <div className="text-background/60">
                  Real OTP: <span className="font-mono text-background">{devOtp}</span> · or use{' '}
                  <span className="font-mono text-background">123456</span>
                </div>
              </div>
            )}

            <Button
              data-testid="admin-login-verify-otp-button"
              onClick={() => verifyOtp(otp)}
              disabled={loading || otp.length !== 6}
              className="mt-8 w-full h-12 rounded-lg text-sm font-semibold"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Verify & enter console'}
            </Button>
          </>
        )}
      </div>
    </div>
  );
}

export default function AdminLoginPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-foreground" />}> 
      <AdminLoginInner />
    </Suspense>
  );
}
