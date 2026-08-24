'use client';

import { usePathname } from 'next/navigation';
import Nav from '@/components/nav';
import ChatWidget from '@/components/chat-widget';

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isAuthPage = pathname === '/login' || pathname === '/signup';

  return (
    <>
      {!isAuthPage && <Nav />}
      <main className={isAuthPage ? 'min-h-screen' : 'ml-64 p-8'}>{children}</main>
      {!isAuthPage && <ChatWidget />}
    </>
  );
}
