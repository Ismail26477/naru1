"use client";
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { LogOut, MapPin, Wallet, Leaf, Plus, Mail, Phone, Edit2, Loader2 } from 'lucide-react';
import { apiFetch, auth } from '@/lib/api';
import { paiseToRupees, formatDateTime } from '@/lib/format';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';

export default function ProfilePage() {
  const router = useRouter();
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ['me'], queryFn: () => apiFetch<any>('/me') });
  const addr = useQuery({ queryKey: ['addresses'], queryFn: () => apiFetch<any[]>('/me/addresses') });
  const wallet = useQuery({ queryKey: ['wallet'], queryFn: () => apiFetch<any>('/me/wallet') });
  const bottle = useQuery({ queryKey: ['bottle'], queryFn: () => apiFetch<{ balance: number }>('/me/bottle-balance') });

  const [editOpen, setEditOpen] = useState(false);
  const [addrOpen, setAddrOpen] = useState(false);
  const [form, setForm] = useState<{ name: string; email: string }>({ name: '', email: '' });
  const [addrForm, setAddrForm] = useState({ line1: '', line2: '', area: '', pincode: '' });

  const updateMe = useMutation({
    mutationFn: async () => apiFetch('/me', { method: 'PATCH', body: form }),
    onSuccess: () => {
      toast.success('Profile updated');
      qc.invalidateQueries({ queryKey: ['me'] });
      setEditOpen(false);
    },
    onError: (e: any) => toast.error(e.message),
  });

  const addAddr = useMutation({
    mutationFn: async () => apiFetch('/me/addresses', { method: 'POST', body: { ...addrForm, is_default: !(addr.data?.length) } }),
    onSuccess: () => {
      toast.success('Address added');
      qc.invalidateQueries({ queryKey: ['addresses'] });
      setAddrOpen(false);
      setAddrForm({ line1: '', line2: '', area: '', pincode: '' });
    },
    onError: (e: any) => toast.error(e.message),
  });

  function logout() {
    auth.logout();
    router.replace('/login');
  }

  return (
    <div className="p-5 pb-4 animate-fade-in">
      <header className="mb-5">
        <div className="text-xs text-muted-foreground uppercase tracking-widest">Profile</div>
        <h1 className="text-3xl font-display font-bold tracking-tight mt-0.5">Account</h1>
      </header>

      {/* User card */}
      <div className="bg-card rounded-3xl p-6 border border-border/50 mb-5">
        {me.isLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : (
          <>
            <div className="flex items-center gap-4">
              <div className="w-16 h-16 rounded-full bg-primary/10 text-primary font-display font-bold text-2xl flex items-center justify-center">
                {(me.data?.name || 'U').slice(0, 1).toUpperCase()}
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-display font-bold text-xl truncate" data-testid="profile-name">{me.data?.name || 'Unnamed'}</div>
                <div className="text-sm text-muted-foreground flex items-center gap-1 mt-0.5"><Phone className="w-3 h-3" />{me.data?.phone}</div>
                {me.data?.email && <div className="text-xs text-muted-foreground flex items-center gap-1 mt-0.5"><Mail className="w-3 h-3" />{me.data?.email}</div>}
              </div>
              <Button
                variant="outline"
                size="icon"
                data-testid="edit-profile-button"
                onClick={() => { setForm({ name: me.data?.name || '', email: me.data?.email || '' }); setEditOpen(true); }}
                className="rounded-full"
              >
                <Edit2 className="w-4 h-4" />
              </Button>
            </div>
          </>
        )}
      </div>

      <Tabs defaultValue="balances" className="mb-5">
        <TabsList className="w-full rounded-full bg-muted p-1">
          <TabsTrigger value="balances" className="flex-1 rounded-full">Balances</TabsTrigger>
          <TabsTrigger value="addresses" className="flex-1 rounded-full">Addresses</TabsTrigger>
        </TabsList>

        <TabsContent value="balances" className="mt-4 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-card rounded-2xl p-5 border border-border/50">
              <div className="flex items-center gap-2 mb-2">
                <div className="w-8 h-8 rounded-lg bg-primary/15 flex items-center justify-center"><Wallet className="w-4 h-4 text-primary" /></div>
                <div className="text-xs font-semibold text-muted-foreground uppercase">Wallet</div>
              </div>
              <div className="font-display text-2xl font-bold" data-testid="wallet-balance-profile">{paiseToRupees(wallet.data?.balance_paise ?? 0)}</div>
              <div className="text-[10px] text-muted-foreground mt-1">Recharge coming soon</div>
            </div>
            <div className="bg-card rounded-2xl p-5 border border-border/50">
              <div className="flex items-center gap-2 mb-2">
                <div className="w-8 h-8 rounded-lg bg-secondary/15 flex items-center justify-center"><Leaf className="w-4 h-4 text-secondary" /></div>
                <div className="text-xs font-semibold text-muted-foreground uppercase">Bottles</div>
              </div>
              <div className="font-display text-2xl font-bold" data-testid="bottle-balance-profile">{bottle.data?.balance ?? 0}</div>
              <div className="text-[10px] text-muted-foreground mt-1">returnable</div>
            </div>
          </div>

          {/* Recent wallet transactions */}
          <div className="bg-card rounded-2xl border border-border/50 overflow-hidden">
            <div className="p-4 border-b border-border/50">
              <div className="font-display font-semibold">Recent wallet activity</div>
            </div>
            <div className="divide-y divide-border/40">
              {(wallet.data?.recent_transactions || []).slice(0, 5).map((t: any) => (
                <div key={t.id} className="flex items-center justify-between p-3 text-sm">
                  <div className="min-w-0">
                    <div className="font-medium truncate capitalize">{t.reason.replace(/_/g, ' ')}</div>
                    <div className="text-xs text-muted-foreground">{formatDateTime(t.created_at)}</div>
                  </div>
                  <div className={`font-mono font-semibold ${t.change_paise >= 0 ? 'text-secondary' : 'text-accent'}`}>
                    {t.change_paise >= 0 ? '+' : ''}{paiseToRupees(t.change_paise)}
                  </div>
                </div>
              ))}
              {!(wallet.data?.recent_transactions?.length) && (
                <div className="text-center py-6 text-xs text-muted-foreground">No transactions yet.</div>
              )}
            </div>
          </div>
        </TabsContent>

        <TabsContent value="addresses" className="mt-4 space-y-3">
          {addr.isLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : (
            <>
              {(addr.data || []).map((a: any) => (
                <div key={a.id} data-testid={`address-${a.id}`} className="bg-card rounded-2xl p-4 border border-border/50 flex items-start gap-3">
                  <div className="w-9 h-9 rounded-xl bg-primary/10 flex items-center justify-center shrink-0"><MapPin className="w-4 h-4 text-primary" /></div>
                  <div className="flex-1 text-sm">
                    <div className="font-medium">{a.line1}{a.line2 ? `, ${a.line2}` : ''}</div>
                    <div className="text-muted-foreground text-xs mt-0.5">{a.area}, {a.city} {a.pincode}</div>
                    {a.is_default && <span className="inline-block mt-1.5 text-[10px] font-semibold bg-primary/10 text-primary px-2 py-0.5 rounded-full">DEFAULT</span>}
                  </div>
                </div>
              ))}
              <Button
                variant="outline"
                onClick={() => setAddrOpen(true)}
                data-testid="add-address-button"
                className="w-full rounded-full h-12 border-dashed border-2"
              >
                <Plus className="w-4 h-4 mr-2" /> Add address
              </Button>
            </>
          )}
        </TabsContent>
      </Tabs>

      <Button
        onClick={logout}
        variant="outline"
        data-testid="logout-button"
        className="w-full rounded-full h-12 border-accent/30 text-accent hover:bg-accent/5 hover:text-accent"
      >
        <LogOut className="w-4 h-4 mr-2" /> Log out
      </Button>

      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="rounded-3xl border-none">
          <DialogHeader>
            <DialogTitle className="font-display">Edit profile</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div>
              <Label className="text-xs uppercase tracking-widest text-muted-foreground">Name</Label>
              <Input data-testid="edit-name-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="rounded-xl h-12" />
            </div>
            <div>
              <Label className="text-xs uppercase tracking-widest text-muted-foreground">Email</Label>
              <Input data-testid="edit-email-input" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} className="rounded-xl h-12" />
            </div>
          </div>
          <DialogFooter>
            <Button onClick={() => updateMe.mutate()} disabled={updateMe.isPending} className="w-full rounded-full h-12" data-testid="save-profile-button">
              {updateMe.isPending ? 'Saving…' : 'Save'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={addrOpen} onOpenChange={setAddrOpen}>
        <DialogContent className="rounded-3xl border-none">
          <DialogHeader>
            <DialogTitle className="font-display">Add address</DialogTitle>
            <DialogDescription>For delivery in Nagpur.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div>
              <Label className="text-xs uppercase tracking-widest text-muted-foreground">House / Flat</Label>
              <Input data-testid="addr-line1-input" value={addrForm.line1} onChange={(e) => setAddrForm({ ...addrForm, line1: e.target.value })} className="rounded-xl h-12" />
            </div>
            <div>
              <Label className="text-xs uppercase tracking-widest text-muted-foreground">Landmark / Street</Label>
              <Input data-testid="addr-line2-input" value={addrForm.line2} onChange={(e) => setAddrForm({ ...addrForm, line2: e.target.value })} className="rounded-xl h-12" />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label className="text-xs uppercase tracking-widest text-muted-foreground">Area</Label>
                <Input data-testid="addr-area-input" value={addrForm.area} onChange={(e) => setAddrForm({ ...addrForm, area: e.target.value })} className="rounded-xl h-12" />
              </div>
              <div>
                <Label className="text-xs uppercase tracking-widest text-muted-foreground">Pincode</Label>
                <Input data-testid="addr-pincode-input" value={addrForm.pincode} onChange={(e) => setAddrForm({ ...addrForm, pincode: e.target.value })} className="rounded-xl h-12" />
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button
              onClick={() => addAddr.mutate()}
              disabled={addAddr.isPending || !addrForm.line1 || !addrForm.area || !addrForm.pincode}
              data-testid="save-address-button"
              className="w-full rounded-full h-12"
            >
              {addAddr.isPending ? 'Adding…' : 'Add address'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
