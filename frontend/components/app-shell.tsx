'use client';

import { useEffect, useRef, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import Link from 'next/link';
import { useApp } from '@/lib/context';
import { getAuthToken, isPendingUser } from '@/lib/api';
import { useTabState, clearTabState } from '@/lib/tab-state';
import Nav from '@/components/nav';
import ChatWidget from '@/components/chat-widget';
import DestinationSwitcher from '@/components/DestinationSwitcher';

const TAB_META: Record<string, { label: string }> = {
  '/': { label: 'Dashboard' },
  '/submit': { label: 'Upload templates' },
  '/moengage-campaigns': { label: 'MoEngage Campaigns' },
  '/activity': { label: 'Activity Logs' },
  '/briefs': { label: 'Jira Briefs' },
  '/work-management': { label: 'Work Management' },
  '/moengage-ops': { label: 'MoEngage Ops' },
  '/apparel/attribution': { label: 'Apparel Attribution' },
  '/apparel/campaigns': { label: 'Apparel WhatsApp Drafts' },
  '/settings': { label: 'Settings' },
  '/tata/click-count': { label: 'Tata Clicks' },
};
export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { account, channel, currentUser, authLoading, refreshSession } = useApp();
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
  const scopeKey = `${currentUser?.id ?? ''}:${currentUser?.tenant_id ?? ''}:${account}:${channel}`;
  const visibleTabs = openTabs.filter((path) => path !== '/login' && path !== '/signup');
  const previousScope = useRef(scopeKey);
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

  // The provider clears old drafts before the keyed destination content mounts.
  useEffect(() => {
    if (previousScope.current !== scopeKey) {
      previousScope.current = scopeKey;
      setOpenTabs([pathname]);
      window.scrollTo(0, 0);
    }
  }, [scopeKey, pathname, setOpenTabs]);

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
            <h1 className="font-medium">Session verification unavailable</h1>
            <p role="alert">{sessionError || 'The service could not verify your session. Your sign-in is retained, and protected workspace data stays hidden until verification succeeds.'}</p>
            <button type="button" onClick={() => { void retrySession(); }} disabled={retryingSession} className="rounded-lg bg-blue-600 px-4 py-2 font-medium text-white disabled:opacity-50">
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
      {!isAuthPage && <a href="#workspace-main" className="workspace-skip-link">Skip to content</a>}
      {!isAuthPage && <Nav />}
      <main id="workspace-main" tabIndex={-1} className={isAuthPage ? 'min-h-screen' : 'workspace-shell min-w-0 md:ml-64 focus:outline-none'}>
        {isAuthPage ? (
          children
        ) : (
          <div className="flex flex-col min-h-screen">
            <div className="workspace-chrome sticky top-14 md:top-0 z-20 border-b border-gray-200">
              <DestinationSwitcher />
            {/* Workspace Tab Bar */}
            {visibleTabs.length > 1 && <div aria-label="Open workspace pages" className="border-t border-gray-100 px-4 sm:px-6 xl:px-8 flex items-center gap-1 overflow-x-auto">
              {visibleTabs.map((path) => {
                const meta = TAB_META[path] || { label: path.replace(/^\//, '') };
                const isActive = pathname === path;
                return (
                  <div
                    key={path}
                    className={`group inline-flex shrink-0 whitespace-nowrap items-center gap-2 px-3 py-2.5 text-xs font-medium border-b-2 transition-colors ${
                      isActive
                        ? 'border-blue-600 text-gray-900 font-medium'
                        : 'border-transparent text-gray-500 hover:text-gray-900 hover:bg-gray-50'
                    }`}
                  >
                    <Link href={path} aria-current={isActive ? 'page' : undefined} className="inline-flex items-center gap-1.5 truncate max-w-[160px]">
                      <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full shrink-0 ${isActive ? 'bg-blue-600' : 'bg-gray-300'}`} />
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
                        className="text-gray-500 hover:text-red-700 rounded p-1 transition-colors text-xs"
                        title={`Close ${meta.label} tab`}
                        aria-label={`Close ${meta.label} tab`}
                      >
                        <svg aria-hidden="true" className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5"><path strokeLinecap="round" d="M5 5l10 10M15 5L5 15" /></svg>
                      </button>
                    )}
                  </div>
                );
              })}
            </div>}
            </div>

            {/* Page Content */}
            <div key={scopeKey} className="workspace-content p-4 pb-24 sm:p-6 sm:pb-20 xl:p-8 xl:pb-20 flex-1 min-w-0">{children}</div>
          </div>
        )}
      </main>
      {!isAuthPage && <ChatWidget />}
    </>
  );
}
