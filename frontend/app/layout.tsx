import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';
import Nav from '@/components/nav';
import { AppProvider } from '@/lib/context';

const inter = Inter({ subsets: ['latin'] });

export const metadata: Metadata = {
  title: 'Karix — Template Whitelisting',
  description: 'WhatsApp template submission and tracking',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <AppProvider>
          <Nav />
          <main className="ml-64 p-8">{children}</main>
        </AppProvider>
      </body>
    </html>
  );
}
