'use client';

import { useState } from 'react';
import Link from 'next/link';
import { signupUser } from '@/lib/api';
import { useApp } from '@/lib/context';

export default function SignupPage() {
  const { setCurrentUser, setUser, setAccount } = useApp();

  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [tenantId, setTenantId] = useState<'bajaj' | 'tata'>('bajaj');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleanName = name.trim();
    const cleanEmail = email.trim();
    const cleanPass = password.trim();

    if (!cleanName || !cleanEmail || !cleanPass) {
      setError('Please fill in all required fields.');
      return;
    }
    if (cleanPass.length < 6) {
      setError('Password must be at least 6 characters long.');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const res = await signupUser(cleanEmail, cleanPass, cleanName, tenantId);
      setCurrentUser(res.user);
      setUser(res.user.name || res.user.email);

      // Pre-set the chosen account
      const chosenAccount = tenantId === 'bajaj' ? 'bajaj' : 'tchfl';
      setAccount(chosenAccount);
      try {
        localStorage.setItem('karix_account', chosenAccount);
      } catch {}

      window.location.href = '/';
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen w-full flex items-center justify-center bg-gradient-to-br from-slate-50 via-gray-50 to-blue-50/40 p-4 sm:p-6 font-sans">
      <div className="w-full max-w-lg bg-white rounded-2xl shadow-xl border border-gray-200/80 p-6 sm:p-8 space-y-6">
        {/* Brand Header */}
        <div className="text-center space-y-2">
          <div className="inline-flex w-12 h-12 rounded-xl bg-gradient-to-br from-blue-600 to-indigo-700 text-white font-bold text-xl items-center justify-center shadow-md">
            K
          </div>
          <h1 className="text-xl font-bold text-gray-900 tracking-tight">Create Operator Account</h1>
          <p className="text-xs text-gray-500">Sign up to access your team&apos;s whitelisting workspace</p>
        </div>

        {/* Error Alert */}
        {error && (
          <div className="p-3 bg-red-50 border border-red-200 rounded-xl text-xs text-red-700 font-medium flex items-start gap-2.5">
            <span className="text-sm shrink-0 mt-0.5">⚠️</span>
            <div className="flex-1 leading-relaxed">
              <span className="font-semibold">Registration failed: </span>
              <span>{error}</span>
            </div>
          </div>
        )}

        {/* Signup Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1.5">
              Full Name
            </label>
            <input
              type="text"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Naman Dugad"
              className="w-full border border-gray-300 rounded-lg px-3.5 py-2.5 text-xs focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition font-sans"
            />
          </div>

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
                placeholder="At least 6 characters"
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

          {/* Organization Selection */}
          <div className="pt-2 space-y-2">
            <label className="block text-xs font-bold text-gray-700 uppercase tracking-wider">
              Choose Organization Workspace
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
              {/* Option 1: Bajaj Finserv */}
              <div
                onClick={() => setTenantId('bajaj')}
                role="button"
                tabIndex={0}
                className={`p-3.5 rounded-xl border text-left cursor-pointer transition-all ${
                  tenantId === 'bajaj'
                    ? 'bg-blue-50/90 border-blue-600 ring-2 ring-blue-500/20 shadow-xs'
                    : 'bg-white border-gray-200 hover:bg-gray-50'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-base">🏢</span>
                  <span
                    className={`w-4 h-4 rounded-full border-2 flex items-center justify-center ${
                      tenantId === 'bajaj' ? 'border-blue-600 bg-blue-600 text-white text-[9px]' : 'border-gray-300'
                    }`}
                  >
                    {tenantId === 'bajaj' ? '✓' : ''}
                  </span>
                </div>
                <h3 className="text-xs font-bold text-gray-900 mt-2">Bajaj Finserv</h3>
                <p className="text-[10px] text-gray-500 font-mono mt-0.5">WABA ID: 286109054585247</p>
              </div>

              {/* Option 2: Tata Capital */}
              <div
                onClick={() => setTenantId('tata')}
                role="button"
                tabIndex={0}
                className={`p-3.5 rounded-xl border text-left cursor-pointer transition-all ${
                  tenantId === 'tata'
                    ? 'bg-blue-50/90 border-blue-600 ring-2 ring-blue-500/20 shadow-xs'
                    : 'bg-white border-gray-200 hover:bg-gray-50'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-base">🏢</span>
                  <span
                    className={`w-4 h-4 rounded-full border-2 flex items-center justify-center ${
                      tenantId === 'tata' ? 'border-blue-600 bg-blue-600 text-white text-[9px]' : 'border-gray-300'
                    }`}
                  >
                    {tenantId === 'tata' ? '✓' : ''}
                  </span>
                </div>
                <h3 className="text-xs font-bold text-gray-900 mt-2">Tata Capital</h3>
                <p className="text-[10px] text-gray-500 font-mono mt-0.5">TCHFL, TCL Promo, Trans</p>
              </div>
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
                <span>Creating account...</span>
              </>
            ) : (
              <span>Create Account & Launch Workspace →</span>
            )}
          </button>
        </form>

        {/* Sign in link */}
        <div className="text-center text-xs text-gray-500 pt-1 border-t border-gray-100">
          <span>Already have an account? </span>
          <Link href="/login" className="text-blue-600 hover:underline font-semibold">
            Sign In
          </Link>
        </div>
      </div>
    </div>
  );
}
