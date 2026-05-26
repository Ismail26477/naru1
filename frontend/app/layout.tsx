import type { Metadata, Viewport } from 'next';
import { Outfit, Karla, JetBrains_Mono } from 'next/font/google';
import './globals.css';
import Providers from './providers';
import { Toaster } from '@/components/ui/sonner';

const outfit = Outfit({ subsets: ['latin'], variable: '--font-outfit', display: 'swap' });
const karla = Karla({ subsets: ['latin'], variable: '--font-karla', display: 'swap' });
const jetbrains = JetBrains_Mono({ subsets: ['latin'], variable: '--font-jetbrains', display: 'swap' });

export const metadata: Metadata = {
  title: 'Posuhtik — Fresh Dairy, Delivered',
  description: 'Subscription-based fresh milk & dairy delivery in Nagpur.',
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  maximumScale: 1,
  themeColor: '#FDFBF7',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${outfit.variable} ${karla.variable} ${jetbrains.variable}`}>
      <body className="min-h-screen bg-muted/40">
        <Providers>{children}</Providers>
        <Toaster richColors closeButton position="top-center" />
      </body>
    </html>
  );
}
