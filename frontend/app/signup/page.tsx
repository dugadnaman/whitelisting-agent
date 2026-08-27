'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { signupUser } from '@/lib/api';
import { useApp } from '@/lib/context';

export default function SignupPage() {
  const router = useRouter();
  const { setCurrentUser, setUser, setAccount } = useApp();

  // Step 1: Credentials, Step 2: Choose Organization & Workspace
  const [step, setStep] = useState<1 | 2>(1);

  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [tenantId, setTenantId] = useState<'bajaj' | 'tata'>('bajaj');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleStep1Submit = (e: React.FormEvent) => {
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
    setError(null);
    setStep(2);
  };

  const handleFinalSignup = async () => {
    setLoading(true);
    setError(null);

    try {
      const res = await signupUser(email.trim(), password.trim(), name.trim(), tenantId);
      setCurrentUser(res.user);
      setUser(res.user.name || res.user.email);
      
      // Pre-set the chosen sub-account
      const chosenAccount = tenantId === 'bajaj' ? 'bajaj' : 'tata';
      setAccount(chosenAccount);
      try {
        localStorage.setItem('active_account', chosenAccount);
      } catch {}

      window.location.href = '/';
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen -ml-64 -m-8 flex items-center justify-center bg-gray-50/70 p-6">
      <div className="w-full max-w-lg bg-white rounded-2xl shadow-xl border border-gray-200/80 p-8 space-y-6">
        {/* Brand Header */}
        <div className="text-center space-y-2">
          <div className="inline-flex w-12 h-12 rounded-xl bg-blue-600 text-white font-bold text-xl items-center justify-center shadow-md">
            K
          </div>
          <h1 className="text-xl font-bold text-gray-900 tracking-tight">
            {step === 1 ? 'Create Operator Account' : 'Choose Your Organization Workspace'}
          </h1>
          <p className="text-xs text-gray-500">
            {step === 1
              ? 'Step 1 of 2: Enter your work details'
              : `Step 2 of 2: Select which enterprise workspace you need access to`}
          </p>
        </div>

        {/* Progress Bar */}
        <div className="flex items-center gap-2">
          <div className={`h-1 flex-1 rounded-full ${step >= 1 ? 'bg-blue-600' : 'bg-gray-200'}`} />
          <div className={`h-1 flex-1 rounded-full ${step >= 2 ? 'bg-blue-600' : 'bg-gray-200'}`} />
        </div>

        {/* Error Alert */}
        {error && (
          <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700 font-medium flex items-center gap-2">
            <span>⚠️</span>
            <span>{error}</span>
          </div>
        )}

        {/* STEP 1: Account Credentials */}
        {step === 1 && (
          <form onSubmit={handleStep1Submit} className="space-y-4">
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

            <button
              type="submit"
              className="w-full py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-semibold shadow-sm transition flex items-center justify-center gap-2"
            >
              <span>Continue to Select Workspace →</span>
            </button>
          </form>
        )}

        {/* STEP 2: Choose Organization & Workspace */}
        {step === 2 && (
          <div className="space-y-5">
            <div className="space-y-3">
              {/* Option 1: Bajaj Finserv */}
              <div
                onClick={() => setTenantId('bajaj')}
                role="button"
                tabIndex={0}
                className={`p-4 rounded-xl border text-left cursor-pointer transition-all ${
                  tenantId === 'bajaj'
                    ? 'bg-blue-50/90 border-blue-600 ring-2 ring-blue-500/20 shadow-xs'
                    : 'bg-white border-gray-200 hover:bg-gray-50'
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <span className="text-xl">🏢</span>
                    <div>
                      <h3 className="text-xs font-bold text-gray-900">Bajaj Finserv</h3>
                      <p className="text-[10px] text-gray-500 font-mono mt-0.5">WABA ID: 286109054585247</p>
                    </div>
                  </div>
                  <span
                    className={`w-4 h-4 rounded-full border-2 flex items-center justify-center ${
                      tenantId === 'bajaj' ? 'border-blue-600 bg-blue-600 text-white text-[9px]' : 'border-gray-300'
                    }`}
                  >
                    {tenantId === 'bajaj' ? '✓' : ''}
                  </span>
                </div>
                <p className="text-[11px] text-gray-600 mt-2.5 leading-relaxed">
                  Dedicated workspace for Bajaj Finserv WhatsApp & RCS message templates.
                </p>
              </div>

              {/* Option 2: Tata Capital */}
              <div
                onClick={() => setTenantId('tata')}
                role="button"
                tabIndex={0}
                className={`p-4 rounded-xl border text-left cursor-pointer transition-all ${
                  tenantId === 'tata'
                    ? 'bg-blue-50/90 border-blue-600 ring-2 ring-blue-500/20 shadow-xs'
                    : 'bg-white border-gray-200 hover:bg-gray-50'
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <span className="text-xl">🏢</span>
                    <div>
                      <h3 className="text-xs font-bold text-gray-900">Tata Capital</h3>
                      <p className="text-[10px] text-gray-500 font-mono mt-0.5">Multi-Entity Enterprise</p>
                    </div>
                  </div>
                  <span
                    className={`w-4 h-4 rounded-full border-2 flex items-center justify-center ${
                      tenantId === 'tata' ? 'border-blue-600 bg-blue-600 text-white text-[9px]' : 'border-gray-300'
                    }`}
                  >
                    {tenantId === 'tata' ? '✓' : ''}
                  </span>
                </div>
                <p className="text-[11px] text-gray-600 mt-2.5 leading-relaxed">
                  Unified access to all Tata Capital sub-entities (TCHFL, TCL Promo, TCL Trans, Wealth, Moneyfy).
                </p>
              </div>
            </div>

            <div className="p-3 bg-gray-50 rounded-xl border border-gray-200 text-[11px] text-gray-500 flex items-center gap-2">
              <span>🔒</span>
              <span>
                Your account will be strictly locked to <strong>{tenantId === 'bajaj' ? 'Bajaj Finserv' : 'Tata Capital'}</strong> to protect enterprise client confidentiality.
              </span>
            </div>

            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => setStep(1)}
                disabled={loading}
                className="px-4 py-2.5 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-lg text-xs font-semibold transition"
              >
                ← Back
              </button>
              <button
                type="button"
                onClick={handleFinalSignup}
                disabled={loading}
                className="flex-1 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white rounded-lg text-xs font-semibold shadow-sm transition flex items-center justify-center gap-2"
              >
                {loading ? (
                  <>
                    <span className="w-2.5 h-2.5 rounded-full bg-white animate-pulse" />
                    <span>Setting up workspace...</span>
                  </>
                ) : (
                  <span>Launch Workspace & Log In →</span>
                )}
              </button>
            </div>
          </div>
        )}

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
