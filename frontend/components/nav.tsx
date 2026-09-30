'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useApp } from '@/lib/context';

const primarySections = [
  {
    id: 'whitelisting',
    href: '/briefs',
    label: 'Whitelisting Workspace',
    subtitle: 'Jira Briefs, File Upload & Status',
    matchPaths: ['/briefs', '/submit', '/'],
    subLinks: [
      { href: '/briefs', label: '📋 Jira Ticket Queue' },
      { href: '/submit', label: '📤 File / Paste Upload' },
      { href: '/', label: '✅ Live WABA Inventory' },
    ],
    icon: (
      <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 4h12v12H4z" />
        <path d="M4 9h12" />
        <path d="M9 4v12" />
      </svg>
    ),
  },
  {
    id: 'ops',
    href: '/work-management',
    label: 'Operations & SLA',
    subtitle: 'Workload, MoEngage & Audit Logs',
    matchPaths: ['/work-management', '/moengage-ops', '/activity'],
    subLinks: [
      { href: '/work-management', label: '👥 Team SLA & Workload' },
      { href: '/moengage-ops', label: '📈 MoEngage Analytics' },
      { href: '/activity', label: '🕒 Submission Audit Logs' },
    ],
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
        <line x1="16" y1="2" x2="16" y2="6" />
        <line x1="8" y1="2" x2="8" y2="6" />
        <line x1="3" y1="10" x2="21" y2="10" />
        <path d="m9 16 2 2 4-4" />
      </svg>
    ),
  },
  {
    id: 'settings',
    href: '/settings',
    label: 'Settings',
    subtitle: 'Session Cookies & Team',
    matchPaths: ['/settings'],
    subLinks: [],
    icon: (
      <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="10" cy="10" r="3" />
        <path d="M16.24 7.76a6 6 0 0 1 0 4.48m-2.48 2.48a6 6 0 0 1-4.48 0m-2.48-2.48a6 6 0 0 1 0-4.48m2.48-2.48a6 6 0 0 1 4.48 0" />
      </svg>
    ),
  },
];

export default function Nav() {
  const pathname = usePathname();
  const {
    account,
    user,
    currentUser,
    logout,
  } = useApp();

  if (pathname === '/login' || pathname === '/signup') {
    return null;
  }

  const isPathMatch = (href: string) => {
    if (href === '/') return pathname === '/';
    return pathname === href || pathname.startsWith(`${href}/`);
  };

  return (
    <aside className="fixed top-0 left-0 w-64 h-screen bg-white border-r border-gray-200 flex flex-col z-30">
      {/* Brand Header */}
      <div className="p-5 border-b border-gray-100">
        <Link href="/briefs" className="flex items-center gap-2.5 group">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center text-white font-bold text-base shadow-sm group-hover:bg-blue-700 transition">
            K
          </div>
          <div>
            <div className="text-base font-bold text-gray-900 leading-tight">Karix</div>
            <div className="text-[11px] text-gray-400 font-medium leading-none mt-0.5">
              2-Click Whitelisting Hub
            </div>
          </div>
        </Link>
      </div>

      {/* Streamlined 3-Section Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-2 overflow-y-auto">
        {primarySections.map((section) => {
          const sectionActive = section.matchPaths.some((p) => isPathMatch(p));
          return (
            <div key={section.id} className="space-y-1">
              <Link
                href={section.href}
                className={
                  sectionActive
                    ? 'flex items-start gap-3 px-3 py-2.5 rounded-xl text-sm font-bold bg-blue-600 text-white shadow-sm transition-all'
                    : 'flex items-start gap-3 px-3 py-2.5 rounded-xl text-sm font-semibold text-gray-700 hover:bg-gray-100 transition-colors'
                }
              >
                <span className="mt-0.5 shrink-0">{section.icon}</span>
                <div className="min-w-0">
                  <div className="leading-tight">{section.label}</div>
                  <div
                    className={`text-[10px] font-normal mt-0.5 truncate ${
                      sectionActive ? 'text-blue-100' : 'text-gray-400'
                    }`}
                  >
                    {section.subtitle}
                  </div>
                </div>
              </Link>

              {/* Contextual Sub-Links when section is active */}
              {sectionActive && section.subLinks.length > 0 && (
                <div className="pl-5 pr-1 py-1 space-y-0.5 border-l-2 border-blue-100 ml-4">
                  {section.subLinks.map((sub) => {
                    const subActive = isPathMatch(sub.href);
                    return (
                      <Link
                        key={sub.href}
                        href={sub.href}
                        className={
                          subActive
                            ? 'block px-2.5 py-1.5 rounded-lg text-xs font-bold bg-blue-50 text-blue-700'
                            : 'block px-2.5 py-1.5 rounded-lg text-xs font-medium text-gray-500 hover:text-gray-900 hover:bg-gray-50'
                        }
                      >
                        {sub.label}
                      </Link>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}

        {/* AI Copilot Trigger */}
        <div className="pt-3 mt-3 border-t border-gray-100">
          <button
            type="button"
            onClick={() => window.dispatchEvent(new CustomEvent('toggle-copilot'))}
            className="w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-xs font-semibold text-gray-700 hover:bg-emerald-50 hover:text-emerald-800 border border-gray-200/80 hover:border-emerald-200 transition-colors group text-left"
          >
            <div className="flex items-center gap-2.5">
              <span className="text-sm">✨</span>
              <span>AI Whitelisting Copilot</span>
            </div>
            <kbd className="px-1.5 py-0.5 bg-gray-100 text-[10px] text-gray-500 rounded font-mono border border-gray-200 group-hover:bg-white transition">
              ⌘K
            </kbd>
          </button>
        </div>
      </nav>

      {/* Active Operator Footer */}
      <div className="p-3.5 border-t border-gray-200/80 bg-gray-50/60 space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <div className="w-7 h-7 rounded-full bg-blue-600 text-white font-bold text-xs flex items-center justify-center shrink-0 shadow-xs">
              {(currentUser?.name || user || 'U').charAt(0).toUpperCase()}
            </div>
            <div className="min-w-0">
              <p className="text-[11px] font-semibold text-gray-900 truncate">
                {currentUser?.name || user || 'Operator'}
              </p>
              <p className="text-[10px] text-gray-400 truncate">
                {currentUser?.email || (currentUser?.role ? `${currentUser.role.toUpperCase()}` : 'Operator')}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={logout}
            className="text-[10px] font-bold text-red-600 hover:text-red-800 bg-red-50 hover:bg-red-100 px-2 py-1 rounded border border-red-200 transition-colors shrink-0"
            title="Sign out of account"
          >
            Log Out
          </button>
        </div>

        <div className="flex items-center justify-between text-[10px] text-gray-400 pt-1 border-t border-gray-200/60">
          <span>Workspace Scope</span>
          <span className="font-mono font-bold text-gray-700 uppercase">
            {currentUser?.tenant_id || account}
          </span>
        </div>
      </div>
    </aside>
  );
}
