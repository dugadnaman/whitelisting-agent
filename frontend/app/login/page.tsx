'use client';

import { useState } from 'react';
import Link from 'next/link';
import { loginUser } from '@/lib/api';
import { useApp } from '@/lib/context';


export default function LoginPage() {
  const { setCurrentUser, setUser, setAccount } = useApp();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e?: React.FormEvent, customEmail?: string, customPass?: string) => {
    if (e) e.preventDefault();
    const finalEmail = (customEmail || email).trim();
    const finalPass = (customPass || password).trim();

    if (!finalEmail || !finalPass) {
      setError('Please enter both work email and password.');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const res = await loginUser(finalEmail, finalPass);
      setCurrentUser(res.user);
      setUser(res.user.name || res.user.email);

      // Pre-select the appropriate account in localStorage
      const tenant = (res.user.tenant_id || 'bajaj').toLowerCase();
      const targetAccount = tenant === 'tata' ? 'tchfl' : tenant === 'all' ? 'bajaj' : tenant;
      setAccount(targetAccount);
      try {
        localStorage.setItem('karix_account', targetAccount);
      } catch {}

      window.location.href = '/';
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setLoading(false);
    }
  };


  return (
    <div className="min-h-screen w-full flex items-center justify-center bg-gradient-to-br from-slate-50 via-gray-50 to-blue-50/40 p-4 sm:p-6 font-sans">
      <div className="w-full max-w-md bg-white rounded-2xl shadow-xl border border-gray-200/80 p-6 sm:p-8 space-y-6">
        {/* Brand Header */}
        <div className="text-center space-y-2">
          <div className="inline-flex w-12 h-12 rounded-xl bg-gradient-to-br from-blue-600 to-indigo-700 text-white font-bold text-xl items-center justify-center shadow-md">
            K
          </div>
          <h1 className="text-xl font-bold text-gray-900 tracking-tight">Karix Whitelisting Platform</h1>
          <p className="text-xs text-gray-500">Sign in to your organization workspace</p>
        </div>

        {/* Error Alert */}
        {error && (
          <div className="p-3 bg-red-50 border border-red-200 rounded-xl text-xs text-red-700 font-medium flex items-start gap-2.5">
            <span className="text-sm shrink-0 mt-0.5">⚠️</span>
            <div className="flex-1 leading-relaxed">
              <span className="font-semibold">Sign in failed: </span>
              <span>{error}</span>
            </div>
          </div>
        )}

        {/* Sign In Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1.5 flex items-center justify-between">
              <span>Work Email</span>
              <span className="text-[10px] text-blue-600 font-normal">e.g. @attributics.com</span>
            </label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="e.g. namandugad@attributics.com"
              className="w-full border border-gray-300 rounded-lg px-3.5 py-2.5 text-xs focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition font-sans"
            />
          </div>

          <div>
            <label className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1.5">
              Password
            </label>
            <div className="relative">
              <input
                type={showPassword ? 'text' : 'password'}
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••••••"
                className="w-full border border-gray-300 rounded-lg px-3.5 py-2.5 pr-10 text-xs focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition font-sans"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 text-xs font-medium p-1"
                aria-label={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? '👁️' : '👁️‍🗨️'}
              </button>
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white rounded-lg text-xs font-semibold shadow-sm transition flex items-center justify-center gap-2 mt-2"
          >
            {loading ? (
              <>
                <span className="w-2.5 h-2.5 rounded-full bg-white animate-pulse" />
                <span>Signing in...</span>
              </>
            ) : (
              <span>Sign In to Workspace →</span>
            )}
          </button>
        </form>


        {/* Sign up link */}
        <div className="text-center text-xs text-gray-500 pt-1 border-t border-gray-100">
          <span>Don&apos;t have an account? </span>
          <Link href="/signup" className="text-blue-600 hover:underline font-semibold">
            Create new account
          </Link>
        </div>
      </div>
    </div>
  );
}
