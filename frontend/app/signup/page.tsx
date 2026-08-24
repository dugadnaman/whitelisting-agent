'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { signupUser } from '@/lib/api';
import { useApp } from '@/lib/context';

export default function SignupPage() {
  const router = useRouter();
  const { setCurrentUser, setUser } = useApp();

  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [tenantId, setTenantId] = useState('bajaj');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleanName = name.trim();
    const cleanEmail = email.trim();
    const cleanPass = password.trim();

    if (!cleanName || !cleanEmail || !cleanPass) {
      setError('Please fill in all fields.');
      return;
    }
    if (cleanPass.length < 6) {
      setError('Password must be at least 6 characters.');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const res = await signupUser(cleanEmail, cleanPass, cleanName, tenantId);
      setCurrentUser(res.user);
      setUser(res.user.name || res.user.email);
      window.location.href = '/';
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen -ml-64 -m-8 flex items-center justify-center bg-gray-50/70 p-6">
      <div className="w-full max-w-md bg-white rounded-2xl shadow-xl border border-gray-200/80 p-8 space-y-6">
        {/* Brand Header */}
        <div className="text-center space-y-2">
          <div className="inline-flex w-12 h-12 rounded-xl bg-blue-600 text-white font-bold text-xl items-center justify-center shadow-md">
            K
          </div>
          <h1 className="text-xl font-bold text-gray-900 tracking-tight">Create Operator Account</h1>
          <p className="text-xs text-gray-500">Join your organization workspace on Karix</p>
        </div>

        {/* Error Alert */}
        {error && (
          <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700 font-medium flex items-center gap-2">
            <span>⚠️</span>
            <span>{error}</span>
          </div>
        )}

        {/* Sign Up Form */}
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
              className="w-full border border-gray-300 rounded-lg px-3.5 py-2 text-xs focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition font-sans"
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
              placeholder="At least 6 characters"
              className="w-full border border-gray-300 rounded-lg px-3.5 py-2 text-xs focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition font-sans"
            />
          </div>

          <div>
            <label className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1.5">
              Select Your Organization / Sub-Product
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 max-h-56 overflow-y-auto p-1 border border-gray-200 rounded-xl bg-gray-50/40">
              {/* Bajaj Finserv */}
              <label
                onClick={() => setTenantId('bajaj')}
                className={`p-2.5 rounded-lg border text-left cursor-pointer transition-all ${
                  tenantId === 'bajaj'
                    ? 'bg-blue-50/80 border-blue-600 ring-1 ring-blue-500/30'
                    : 'bg-white border-gray-200 hover:bg-gray-50'
                }`}
              >
                <div className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="tenant"
                    checked={tenantId === 'bajaj'}
                    onChange={() => setTenantId('bajaj')}
                    className="text-blue-600 focus:ring-blue-500"
                  />
                  <span className="text-xs font-bold text-gray-900">Bajaj Finserv</span>
                </div>
                <p className="text-[10px] text-gray-500 mt-0.5 pl-5">
                  WABA: 286109054585247
                </p>
              </label>

              {/* TCL Promotional */}
              <label
                onClick={() => setTenantId('tcl_promo')}
                className={`p-2.5 rounded-lg border text-left cursor-pointer transition-all ${
                  tenantId === 'tcl_promo'
                    ? 'bg-blue-50/80 border-blue-600 ring-1 ring-blue-500/30'
                    : 'bg-white border-gray-200 hover:bg-gray-50'
                }`}
              >
                <div className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="tenant"
                    checked={tenantId === 'tcl_promo'}
                    onChange={() => setTenantId('tcl_promo')}
                    className="text-blue-600 focus:ring-blue-500"
                  />
                  <span className="text-xs font-bold text-gray-900">TCL — Promo (PL, BL, UCL)</span>
                </div>
                <p className="text-[10px] text-gray-500 mt-0.5 pl-5">
                  Headers: PLTATA, TATABL, ALTATA
                </p>
              </label>

              {/* TCL Transactional */}
              <label
                onClick={() => setTenantId('tcl_trans')}
                className={`p-2.5 rounded-lg border text-left cursor-pointer transition-all ${
                  tenantId === 'tcl_trans'
                    ? 'bg-blue-50/80 border-blue-600 ring-1 ring-blue-500/30'
                    : 'bg-white border-gray-200 hover:bg-gray-50'
                }`}
              >
                <div className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="tenant"
                    checked={tenantId === 'tcl_trans'}
                    onChange={() => setTenantId('tcl_trans')}
                    className="text-blue-600 focus:ring-blue-500"
                  />
                  <span className="text-xs font-bold text-gray-900">TCL — Trans (LAP, Services)</span>
                </div>
                <p className="text-[10px] text-gray-500 mt-0.5 pl-5">
                  Headers: TCLLAP, Tatacl
                </p>
              </label>

              {/* TCHFL Housing Finance */}
              <label
                onClick={() => setTenantId('tchfl')}
                className={`p-2.5 rounded-lg border text-left cursor-pointer transition-all ${
                  tenantId === 'tchfl'
                    ? 'bg-blue-50/80 border-blue-600 ring-1 ring-blue-500/30'
                    : 'bg-white border-gray-200 hover:bg-gray-50'
                }`}
              >
                <div className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="tenant"
                    checked={tenantId === 'tchfl'}
                    onChange={() => setTenantId('tchfl')}
                    className="text-blue-600 focus:ring-blue-500"
                  />
                  <span className="text-xs font-bold text-gray-900">TCHFL — Housing Finance</span>
                </div>
                <p className="text-[10px] text-gray-500 mt-0.5 pl-5">
                  Header: HLTATA
                </p>
              </label>

              {/* Wealth */}
              <label
                onClick={() => setTenantId('wealth')}
                className={`p-2.5 rounded-lg border text-left cursor-pointer transition-all ${
                  tenantId === 'wealth'
                    ? 'bg-blue-50/80 border-blue-600 ring-1 ring-blue-500/30'
                    : 'bg-white border-gray-200 hover:bg-gray-50'
                }`}
              >
                <div className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="tenant"
                    checked={tenantId === 'wealth'}
                    onChange={() => setTenantId('wealth')}
                    className="text-blue-600 focus:ring-blue-500"
                  />
                  <span className="text-xs font-bold text-gray-900">Tata Wealth & Securities</span>
                </div>
                <p className="text-[10px] text-gray-500 mt-0.5 pl-5">
                  Header: TATAWL
                </p>
              </label>

              {/* Moneyfy */}
              <label
                onClick={() => setTenantId('moneyfy')}
                className={`p-2.5 rounded-lg border text-left cursor-pointer transition-all ${
                  tenantId === 'moneyfy'
                    ? 'bg-blue-50/80 border-blue-600 ring-1 ring-blue-500/30'
                    : 'bg-white border-gray-200 hover:bg-gray-50'
                }`}
              >
                <div className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="tenant"
                    checked={tenantId === 'moneyfy'}
                    onChange={() => setTenantId('moneyfy')}
                    className="text-blue-600 focus:ring-blue-500"
                  />
                  <span className="text-xs font-bold text-gray-900">Tata Moneyfy</span>
                </div>
                <p className="text-[10px] text-gray-500 mt-0.5 pl-5">
                  Mutual Funds & Investments
                </p>
              </label>

              {/* Tata Capital All */}
              <label
                onClick={() => setTenantId('tata')}
                className={`p-2.5 rounded-lg border text-left cursor-pointer transition-all sm:col-span-2 ${
                  tenantId === 'tata'
                    ? 'bg-blue-50/80 border-blue-600 ring-1 ring-blue-500/30'
                    : 'bg-white border-gray-200 hover:bg-gray-50'
                }`}
              >
                <div className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="tenant"
                    checked={tenantId === 'tata'}
                    onChange={() => setTenantId('tata')}
                    className="text-blue-600 focus:ring-blue-500"
                  />
                  <span className="text-xs font-bold text-gray-900">Tata Capital (All Sub-Products Master)</span>
                </div>
                <p className="text-[10px] text-gray-500 mt-0.5 pl-5">
                  Full access across all TCL, TCHFL, Wealth & Moneyfy sub-entities
                </p>
              </label>
            </div>
            <p className="text-[10px] text-gray-400 mt-1.5">
              🔒 Your account will be strictly locked to this organization to protect client confidentiality.
            </p>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white rounded-lg text-xs font-semibold shadow-sm transition flex items-center justify-center gap-2"
          >
            {loading ? (
              <>
                <span className="w-2.5 h-2.5 rounded-full bg-white animate-pulse" />
                <span>Creating account...</span>
              </>
            ) : (
              <span>Create Account & Log In</span>
            )}
          </button>
        </form>

        {/* Sign in link */}
        <div className="text-center text-xs text-gray-500 pt-2 border-t border-gray-100">
          <span>Already have an account? </span>
          <Link href="/login" className="text-blue-600 hover:underline font-semibold">
            Sign In
          </Link>
        </div>
      </div>
    </div>
  );
}
