'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { loginUser, loginWithGoogle, authorizedAccount, clearAuthToken, accountOrganization, isPendingUser, type AuthResponse } from '@/lib/api';
import GoogleSignIn from '@/components/google-sign-in';


export default function LoginPage() {

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [organization, setOrganization] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(false);
  const submitting = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const completeLogin = (res: AuthResponse) => {
    if (isPendingUser(res.user)) {
      window.location.href = '/signup';
      return;
    }

    const matchesOrganization = !organization || res.user.role === 'superadmin' ||
      accountOrganization(res.user.tenant_id) === organization;
    if (!matchesOrganization) {
      clearAuthToken();
      throw new Error('This account does not have access to the selected organization. Choose your own organization or contact its administrator.');
    }

    const preferredAccount = organization
      ? (organization === 'tata' ? 'tcl_promo' : organization)
      : localStorage.getItem('karix_account');
    const targetAccount = authorizedAccount(res.user, preferredAccount);
    try {
      localStorage.setItem('karix_account', targetAccount);
    } catch {}

    window.location.href = targetAccount === 'apparel' ? '/apparel/attribution' : '/';
  };

  const signIn = async (authenticate: () => Promise<AuthResponse>) => {
    if (!mounted.current || submitting.current) throw new Error('A sign-in is already in progress. Please wait.');
    submitting.current = true;
    setLoading(true);
    setError(null);
    try {
      const res = await authenticate();
      if (mounted.current) completeLogin(res);
    } catch (err) {
      submitting.current = false;
      if (mounted.current) setLoading(false);
      throw err;
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting.current) return;
    const finalEmail = email.trim();
    const finalPass = password;

    if (!finalEmail || !finalPass) {
      setError('Please enter both work email and password.');
      return;
    }

    try {
      await signIn(() => loginUser(finalEmail, finalPass));
    } catch (err) {
      if (mounted.current) setError(err instanceof Error ? err.message : String(err));
    }
  };


  return (
    <div className="workspace-page min-h-screen w-full flex items-center justify-center bg-gray-50 px-4 py-8 sm:px-6 sm:py-12">
      <main className="w-full max-w-md bg-white rounded-xl shadow-sm border border-gray-200 p-6 sm:p-8 space-y-6">
        {/* Brand Header */}
        <div className="space-y-3">
          <div className="inline-flex items-center gap-3">
            <img src="/logo.svg" alt="" className="w-10 h-10 rounded-lg" />
            <span className="workspace-eyebrow">Attributics · Campaign operations</span>
          </div>
          <h1 className="workspace-heading">Sign in to campaign operations</h1>
          <p className="workspace-description">Sign in to your organization workspace. Access is limited to the accounts assigned to you.</p>
        </div>

        {/* Error Alert */}
        {error && (
          <div role="alert" id="login-error" className="p-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
            <div className="flex-1 leading-relaxed">
              <span className="font-medium">Sign in failed: </span>
              <span>{error}</span>
            </div>
          </div>
        )}

        {/* Sign In Form */}
        <form onSubmit={handleSubmit} className="space-y-4" aria-busy={loading} aria-describedby={error ? 'login-error' : undefined}>
          <div>
            <label htmlFor="login-organization" className="block text-sm font-medium text-gray-700  mb-2">
              Organization
            </label>
            <select
              id="login-organization"
              value={organization}
              onChange={(e) => setOrganization(e.target.value)}
              disabled={loading}
              className="workspace-select"
            >
              <option value="">Use my account&apos;s organization</option>
              <option value="bajaj">Bajaj Finserv</option>
              <option value="tata">Tata Capital</option>
              <option value="apparel">Apparel</option>
            </select>
          </div>
          <div>
            <label htmlFor="login-email" className="block text-sm font-medium text-gray-700 mb-2">
              <span>Work email</span>
            </label>
            <input
              id="login-email"
              disabled={loading}
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              className="workspace-input"
            />
          </div>

          <div>
            <label htmlFor="login-password" className="block text-sm font-medium text-gray-700  mb-2">
              Password
            </label>
            <div className="relative">
              <input
                id="login-password"
                required
                disabled={loading}
                type={showPassword ? 'text' : 'password'}
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••••••"
                className="workspace-input w-full pr-16"
              />
              <button
                type="button"
                disabled={loading}
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-600 hover:text-gray-900 text-sm font-medium p-1 rounded"
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                aria-pressed={showPassword}
              >
                {showPassword ? 'Hide' : 'Show'}
              </button>
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 text-white rounded-lg text-sm font-medium shadow-sm transition-colors flex items-center justify-center gap-2 mt-2"
          >
            {loading ? (
              <>
                <span>Signing in...</span>
              </>
            ) : (
              <span>Sign in to workspace</span>
            )}
          </button>
        </form>

        <GoogleSignIn
          disabled={loading}
          onCredential={(credential, signal) => signIn(() => loginWithGoogle(credential, signal))}
        />
        <p className="workspace-guide text-sm text-gray-600">New to the workspace? Request company access below. An administrator must approve your request before company data becomes available.</p>


        {/* Sign up link */}
        <div className="text-center text-sm text-gray-500 pt-1 border-t border-gray-100">
          <span>Don&apos;t have an account? </span>
          <Link href="/signup" className="text-indigo-600 hover:underline font-medium">
            Request company access
          </Link>
        </div>
      </main>
    </div>
  );
}
