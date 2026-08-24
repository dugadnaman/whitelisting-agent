'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { loginUser } from '@/lib/api';
import { useApp } from '@/lib/context';

export default function LoginPage() {
  const router = useRouter();
  const { setCurrentUser, setUser } = useApp();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e?: React.FormEvent, customEmail?: string, customPass?: string) => {
    if (e) e.preventDefault();
    const finalEmail = (customEmail || email).trim();
    const finalPass = (customPass || password).trim();

    if (!finalEmail || !finalPass) {
      setError('Please enter both email and password.');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const res = await loginUser(finalEmail, finalPass);
      setCurrentUser(res.user);
      setUser(res.user.name || res.user.email);
      router.push('/');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const handleQuickLogin = (demoEmail: string, demoPass: string) => {
    setEmail(demoEmail);
    setPassword(demoPass);
    handleSubmit(undefined, demoEmail, demoPass);
  };

  return (
    <div className="min-h-screen -ml-64 -m-8 flex items-center justify-center bg-gray-50/70 p-6">
      <div className="w-full max-w-md bg-white rounded-2xl shadow-xl border border-gray-200/80 p-8 space-y-6">
        {/* Brand Header */}
        <div className="text-center space-y-2">
          <div className="inline-flex w-12 h-12 rounded-xl bg-blue-600 text-white font-bold text-xl items-center justify-center shadow-md">
            K
          </div>
          <h1 className="text-xl font-bold text-gray-900 tracking-tight">Karix Whitelisting Agent</h1>
          <p className="text-xs text-gray-500">Sign in to your organization workspace</p>
        </div>

        {/* Error Alert */}
        {error && (
          <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700 font-medium flex items-center gap-2">
            <span>⚠️</span>
            <span>{error}</span>
          </div>
        )}

        {/* Sign In Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1.5">
              Work Email
            </label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="e.g. operator@bajajfinserv.in"
              className="w-full border border-gray-300 rounded-lg px-3.5 py-2 text-xs focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition font-sans"
            />
          </div>

          <div>
            <label className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1.5">
              Password
            </label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••••••"
              className="w-full border border-gray-300 rounded-lg px-3.5 py-2 text-xs focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition font-sans"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white rounded-lg text-xs font-semibold shadow-sm transition flex items-center justify-center gap-2"
          >
            {loading ? (
              <>
                <span className="w-2.5 h-2.5 rounded-full bg-white animate-pulse" />
                <span>Signing in...</span>
              </>
            ) : (
              <span>Sign In to Workspace</span>
            )}
          </button>
        </form>

        {/* Quick Demo Credentials */}
        <div className="pt-4 border-t border-gray-100 space-y-2.5">
          <p className="text-[10px] font-bold text-gray-400 uppercase tracking-wider text-center">
            Quick One-Click Demo Access
          </p>
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => handleQuickLogin('bajaj@karix.com', 'Bajaj@123')}
              className="p-2 bg-emerald-50/70 hover:bg-emerald-100 border border-emerald-200 text-emerald-800 rounded-lg text-[11px] font-semibold text-left transition"
            >
              <div className="font-bold">Bajaj Finserv</div>
              <div className="text-[10px] text-emerald-600 font-mono">bajaj@karix.com</div>
            </button>

            <button
              type="button"
              onClick={() => handleQuickLogin('tata@karix.com', 'Tata@123')}
              className="p-2 bg-blue-50/70 hover:bg-blue-100 border border-blue-200 text-blue-800 rounded-lg text-[11px] font-semibold text-left transition"
            >
              <div className="font-bold">Tata Capital</div>
              <div className="text-[10px] text-blue-600 font-mono">tata@karix.com</div>
            </button>
          </div>
          <button
            type="button"
            onClick={() => handleQuickLogin('admin@karix.com', 'Admin@123')}
            className="w-full p-2 bg-gray-100 hover:bg-gray-200 border border-gray-300 text-gray-800 rounded-lg text-[11px] font-semibold text-center transition"
          >
            🔑 Login as Platform SuperAdmin (admin@karix.com)
          </button>
        </div>

        {/* Sign up link */}
        <div className="text-center text-xs text-gray-500 pt-2">
          <span>Don&apos;t have an account? </span>
          <Link href="/signup" className="text-blue-600 hover:underline font-semibold">
            Create new account
          </Link>
        </div>
      </div>
    </div>
  );
}
