"use client";
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Milk, Phone, ArrowRight, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { InputOTP, InputOTPGroup, InputOTPSlot } from '@/components/ui/input-otp';
import { apiFetch, auth } from '@/lib/api';

export default function LoginPage() {
  const router = useRouter();
  const [phone, setPhone] = useState('');
  const [otp, setOtp] = useState('');
  const [step, setStep] = useState<'phone' | 'otp'>('phone');
  const [loading, setLoading] = useState(false);
  const [devOtp, setDevOtp] = useState<string | null>(null);

  const sanitizedPhone = phone.startsWith('+') ? phone : phone.length === 10 ? `+91${phone}` : `+${phone}`;

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
      auth.setTokens(r.access_token, r.refresh_token, {
        user_id: r.user_id,
        role: r.role,
        name: r.name,
        approved: r.approved,
      });
      if (r.role === 'admin') {
        auth.logout();
        toast.error('Please use /admin/login to sign in as admin.');
        router.replace('/admin/login');
        return;
      }
      if (r.role === 'delivery') {
        auth.logout();
        toast.error('Delivery app is not yet available.');
        return;
      }
      toast.success('Welcome back!');
      router.replace('/dashboard');
    } catch (e: any) {
      toast.error(e.message || 'Invalid OTP');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="max-w-md mx-auto min-h-screen bg-background sm:border-x sm:border-border shadow-xl relative flex flex-col px-6 pt-16 pb-12 overflow-hidden">
      {/* Warm ambient glow */}
      <div aria-hidden className="absolute -top-24 -right-24 w-72 h-72 rounded-full bg-primary/20 blur-3xl" />
      <div aria-hidden className="absolute bottom-12 -left-24 w-72 h-72 rounded-full bg-secondary/15 blur-3xl" />

      <div className="relative z-10 flex items-center gap-3 mb-16">
        <div className="w-12 h-12 rounded-2xl bg-primary flex items-center justify-center shadow-lg shadow-primary/30">
          <Milk className="w-6 h-6 text-primary-foreground" />
        </div>
        <div>
          <div className="font-display font-bold text-2xl tracking-tight">Posuhtik</div>
          <div className="text-xs text-muted-foreground">Fresh dairy, delivered daily</div>
        </div>
      </div>

      {step === 'phone' && (
        <div className="relative z-10 animate-fade-in">
          <h1 className="font-display text-4xl font-bold leading-tight mb-3">
            Welcome.
            <br />
            <span className="text-primary">Let's get your milk.</span>
          </h1>
          <p className="text-muted-foreground mb-10 leading-relaxed">
            Enter your phone number. We'll send a one-time code to log you in.
          </p>

          <label className="block text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-2">
            Phone number
          </label>
          <div className="relative">
            <span className="absolute inset-y-0 left-4 flex items-center text-muted-foreground">
              <Phone className="w-4 h-4" />
            </span>
            <Input
              data-testid="login-phone-input"
              inputMode="tel"
              autoComplete="tel"
              placeholder="+91 90000 00001"
              value={phone}
              onChange={(e) => setPhone(e.target.value.replace(/[^\d+]/g, ''))}
              className="pl-11 h-14 text-lg rounded-2xl"
            />
          </div>

          <Button
            data-testid="login-send-otp-button"
            onClick={requestOtp}
            disabled={loading}
            className="mt-8 w-full h-14 rounded-full text-base font-medium shadow-[0_8px_24px_-8px_hsl(var(--primary)/0.6)]"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <>Continue <ArrowRight className="w-4 h-4 ml-2" /></>}
          </Button>

          <p className="text-xs text-muted-foreground mt-8 text-center leading-relaxed">
            By continuing, you agree to Posuhtik's terms of service.
            <br />Dev OTP: <span className="font-mono font-semibold text-foreground">123456</span>
          </p>
        </div>
      )}

      {step === 'otp' && (
        <div className="relative z-10 animate-fade-in">
          <h1 className="font-display text-3xl font-bold mb-2">Enter the code</h1>
          <p className="text-muted-foreground mb-8">
            Sent to <span className="font-semibold text-foreground">{sanitizedPhone}</span>.{' '}
            <button onClick={() => setStep('phone')} className="text-primary font-semibold underline-offset-2 hover:underline">
              Change
            </button>
          </p>

          <InputOTP
            data-testid="login-otp-input"
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
                <InputOTPSlot key={i} index={i} className="w-12 h-14 text-xl font-mono rounded-xl border-2" />
              ))}
            </InputOTPGroup>
          </InputOTP>

          {devOtp && (
            <div className="mt-6 p-4 rounded-2xl bg-muted border border-border text-sm">
              <div className="font-semibold mb-1">Dev helper</div>
              <div className="text-muted-foreground">
                Real OTP: <span className="font-mono text-foreground">{devOtp}</span> · or use <span className="font-mono text-foreground">123456</span>
              </div>
            </div>
          )}

          <Button
            data-testid="login-verify-otp-button"
            onClick={() => verifyOtp(otp)}
            disabled={loading || otp.length !== 6}
            className="mt-8 w-full h-14 rounded-full text-base font-medium"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Verify & log in'}
          </Button>
        </div>
      )}
    </div>
  );
}
