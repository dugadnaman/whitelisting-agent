'use client';

import { useEffect, useRef, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import Link from 'next/link';
import { useApp } from '@/lib/context';
import { getAuthToken, isPendingUser } from '@/lib/api';
import { useTabState, clearTabState } from '@/lib/tab-state';
import Nav from '@/components/nav';
import ChatWidget from '@/components/chat-widget';

const TAB_META: Record<string, { label: string; icon: string }> = {
  '/': { label: 'Dashboard', icon: '📊' },
  '/submit': { label: 'Submit Templates', icon: '🚀' },
  '/moengage-campaigns': { label: 'MoEngage Campaigns', icon: '🎯' },
  '/activity': { label: 'Activity Logs', icon: '🕒' },
  '/briefs': { label: 'Jira Briefs', icon: '📄' },
  '/work-management': { label: 'Work Management', icon: '📋' },
  '/moengage-ops': { label: 'MoEngage Ops', icon: '⚙️' },
  '/apparel/attribution': { label: 'Apparel Attribution', icon: '👔' },
  '/settings': { label: 'Settings', icon: '⚙️' },
  '/tata/click-count': { label: 'Tata Clicks', icon: '📈' },
};
export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { account, currentUser, authLoading, refreshSession } = useApp();
  const isAuthPage = pathname === '/login' || pathname === '/signup';
  const hasWorkspace = !authLoading && Boolean(currentUser) && !isPendingUser(currentUser);
  const [retryingSession, setRetryingSession] = useState(false);
  const [sessionError, setSessionError] = useState<string | null>(null);

  const retrySession = async () => {
    if (retryingSession) return;
    setRetryingSession(true);
    setSessionError(null);
    try {
      await refreshSession();
    } catch {
      setSessionError('Session verification is still unavailable. Your sign-in is retained; retry when the service is ready.');
    } finally {
      setRetryingSession(false);
    }
  };

  const [openTabs, setOpenTabs] = useTabState<string[]>('workspace_open_tabs', ['/']);
  const prevAccountRef = useRef(account);
  useEffect(() => {
    if (authLoading || isAuthPage) return;
    if (!currentUser && !getAuthToken()) router.replace('/login');
    else if (isPendingUser(currentUser)) router.replace('/signup');
  }, [authLoading, currentUser, isAuthPage, router]);


  // Keep open tabs updated as user navigates
  useEffect(() => {
    if (isAuthPage || !hasWorkspace) return;
    setOpenTabs((prev) => {
      if (prev.includes(pathname)) return prev;
      return [...prev, pathname];
    });
  }, [pathname, isAuthPage, hasWorkspace, setOpenTabs]);

  // When account changes, clear cached drafts so they don't leak across tenants
  useEffect(() => {
    if (prevAccountRef.current !== account) {
      prevAccountRef.current = account;
      clearTabState();
      setOpenTabs([pathname]);
    }
  }, [account, pathname, setOpenTabs]);

  const closeTab = (path: string) => {
    const remaining = openTabs.filter((t) => t !== path);
    const nextTabs = remaining.length > 0 ? remaining : ['/'];
    setOpenTabs(nextTabs);

    // Clear cached state for the closed tab
    const prefix = path === '/' ? 'dashboard_' : path.replace(/^\//, '').replace(/\//g, '_') + '_';
    clearTabState(prefix);

    if (pathname === path) {
      const target = nextTabs[nextTabs.length - 1];
      router.push(target);
    }
  };
  if (!isAuthPage && !hasWorkspace) {
    if (!authLoading && getAuthToken()) {
      return (
        <main className="min-h-screen flex items-center justify-center p-6">
          <div className="max-w-md space-y-4 rounded-xl border border-amber-200 bg-amber-50 p-6 text-sm text-gray-800">
            <h1 className="font-semibold">Session verification unavailable</h1>
            <p role="alert">{sessionError || 'The service could not verify your session. Your sign-in is retained, and protected workspace data stays hidden until verification succeeds.'}</p>
            <button type="button" onClick={() => { void retrySession(); }} disabled={retryingSession} className="rounded-lg bg-blue-600 px-4 py-2 font-semibold text-white disabled:opacity-50">
              {retryingSession ? 'Checking your session...' : 'Retry session verification'}
            </button>
          </div>
        </main>
      );
    }
    return <div className="min-h-screen flex items-center justify-center text-sm text-gray-500" role="status">{authLoading ? 'Checking your session...' : 'Redirecting to your account...'}</div>;
  }

  return (
    <>
      {!isAuthPage && <Nav />}
      <main className={isAuthPage ? 'min-h-screen' : 'min-w-0 md:ml-64'}>
        {isAuthPage ? (
          children
        ) : (
          <div className="flex flex-col min-h-screen">
            {/* Workspace Tab Bar */}
            <div className="sticky top-14 md:top-0 z-20 bg-gray-50/95 backdrop-blur-xs border-b border-gray-200 px-4 sm:px-6 pt-2 flex items-center gap-1.5 overflow-x-auto shadow-2xs">
              {openTabs.map((path) => {
                const meta = TAB_META[path] || { label: path.replace(/^\//, ''), icon: '📌' };
                const isActive = pathname === path;
                return (
                  <div
                    key={path}
                    className={`group inline-flex items-center gap-2 px-3 py-1.5 rounded-t-lg text-xs font-medium border border-b-0 transition-colors ${
                      isActive
                        ? 'bg-white border-gray-200 text-blue-700 font-semibold shadow-2xs -mb-px'
                        : 'bg-gray-100/70 border-transparent text-gray-500 hover:text-gray-800 hover:bg-gray-200/50'
                    }`}
                  >
                    <Link href={path} className="inline-flex items-center gap-1.5 truncate max-w-[160px]">
                      <span>{meta.icon}</span>
                      <span className="truncate">{meta.label}</span>
                    </Link>
                    {openTabs.length > 1 && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          closeTab(path);
                        }}
                        className="text-gray-400 hover:text-red-600 rounded p-0.5 transition-colors text-[10px]"
                        title="Close tab (clears saved draft)"
                      >
                        ✕
                      </button>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Page Content */}
            <div className="p-4 sm:p-8 flex-1 min-w-0">{children}</div>
          </div>
        )}
      </main>
      {!isAuthPage && <ChatWidget />}
    </>
  );
}
