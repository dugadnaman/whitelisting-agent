'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useApp } from '@/lib/context';
import { signupUser, requestCompanyAccess, isPendingUser, authorizedAccount, getAuthToken } from '@/lib/api';
import type { RequestedTenant } from '@/lib/api';

export default function SignupPage() {
  const router = useRouter();
  const { currentUser, setCurrentUser, authLoading, refreshSession, logout, account, getAccountLabel } = useApp();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [organization, setOrganization] = useState<RequestedTenant | ''>('');
  const [loading, setLoading] = useState<'signup' | 'request' | 'refresh' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState('');

  useEffect(() => {
    if (!authLoading && currentUser && !isPendingUser(currentUser)) {
      const target = authorizedAccount(currentUser, account);
      router.replace(target === 'apparel' ? '/apparel/attribution' : '/');
    }
  }, [authLoading, currentUser, account, router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setStatus('');
    if (!organization) {
      setError('Choose the organization you want to request access to.');
      return;
    }
    if (!currentUser) {
      if (!name.trim() || !email.trim()) {
        setError('Enter your full name and work email.');
        return;
      }
      if ([...password].length < 12 || new TextEncoder().encode(password).length > 72) {
        setError('Use at least 12 characters and no more than 72 UTF-8 bytes for your password.');
        return;
      }
      if (password !== confirmation) {
        setError('The passwords do not match.');
        return;
      }
    }
    setLoading(currentUser ? 'request' : 'signup');
    const token = getAuthToken();
    try {
      const profile = currentUser
        ? await requestCompanyAccess(organization)
        : (await signupUser(email.trim(), password, name.trim(), organization)).user;
      if (currentUser && getAuthToken() !== token) return;
      setCurrentUser(profile);
      setPassword('');
      setConfirmation('');
      setStatus('Your request has been sent to the organization administrator.');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(null);
    }
  }

  async function handleRefresh() {
    setLoading('refresh');
    setError(null);
    setStatus('');
    try {
      const profile = await refreshSession();
      if (isPendingUser(profile)) setStatus('Your account is still awaiting administrator approval.');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(null);
    }
  }

  const inputClass = 'w-full border border-gray-300 rounded-lg px-4 py-2.5 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none disabled:bg-gray-100';
  const labelClass = 'block text-sm font-medium text-gray-700  mb-2';
  const errorDescription = error ? 'signup-error' : undefined;

  if (authLoading || (currentUser && !isPendingUser(currentUser))) {
    return <div className="min-h-screen flex items-center justify-center text-sm text-gray-500" role="status">{authLoading ? 'Checking your session...' : 'Opening your workspace...'}</div>;
  }

  return (
    <div className="workspace-page min-h-screen w-full flex items-center justify-center px-4 py-8 sm:px-6 sm:py-12">
      <main className="w-full max-w-md rounded-2xl border border-white/70 bg-white/80 backdrop-blur-xl p-6 sm:p-8 shadow-2xl space-y-6">
        <div className="space-y-2">
          <div className="inline-flex items-center gap-3">
            <img src="/logo.svg" alt="" className="w-10 h-10 rounded-lg" />
            <span className="workspace-eyebrow">Attributics · Company access</span>
          </div>
          <h1 className="workspace-heading">{currentUser ? 'Awaiting company approval' : 'Join your company workspace'}</h1>
          <p className="text-sm text-gray-600">
            {currentUser ? `Signed in as ${currentUser.name || currentUser.email}.` : 'Create an account and request access from your organization administrator.'}
            {' '}Company data is available only after your request is approved.
          </p>
        </div>

        {error && <div id="signup-error" role="alert" className="p-3 rounded-xl border border-red-200 bg-red-50 text-sm text-red-700">{error}</div>}
        {status && <p role="status" className="text-sm text-gray-700">{status}</p>}

        {currentUser?.requested_tenant_id ? (
          <div className="workspace-guide space-y-2" role="status">
            <h2 className="text-sm font-medium text-gray-900">Access request pending</h2>
            <p className="text-sm text-gray-800">You requested access to <strong className="font-medium">{getAccountLabel(currentUser.requested_tenant_id)}</strong>. Its administrator must approve your account before you can open the workspace.</p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4" aria-busy={Boolean(loading)}>
            {!currentUser && (
              <>
                <div>
                  <label htmlFor="signup-name" className={labelClass}>Full name</label>
                  <input id="signup-name" type="text" autoComplete="name" required disabled={Boolean(loading)} value={name} onChange={(e) => setName(e.target.value)} aria-describedby={errorDescription} className={inputClass} />
                </div>
                <div>
                  <label htmlFor="signup-email" className={labelClass}>Work email</label>
                  <input id="signup-email" type="email" autoComplete="email" required disabled={Boolean(loading)} value={email} onChange={(e) => setEmail(e.target.value)} aria-describedby={errorDescription} className={inputClass} />
                </div>
                <div>
                  <label htmlFor="signup-password" className={labelClass}>Password</label>
                  <input id="signup-password" type={showPassword ? 'text' : 'password'} autoComplete="new-password" required minLength={12} disabled={Boolean(loading)} value={password} onChange={(e) => setPassword(e.target.value)} aria-describedby={`signup-password-help${error ? ' signup-error' : ''}`} className={inputClass} />
                  <p id="signup-password-help" className="mt-1 text-sm text-gray-500">At least 12 characters; maximum 72 UTF-8 bytes. Spaces are preserved.</p>
                </div>
                <div>
                  <label htmlFor="signup-confirmation" className={labelClass}>Confirm password</label>
                  <input id="signup-confirmation" type={showPassword ? 'text' : 'password'} autoComplete="new-password" required disabled={Boolean(loading)} value={confirmation} onChange={(e) => setConfirmation(e.target.value)} aria-describedby={errorDescription} className={inputClass} />
                </div>
                <button type="button" onClick={() => setShowPassword(!showPassword)} disabled={Boolean(loading)} aria-pressed={showPassword} className="text-sm font-medium text-indigo-600 hover:underline">{showPassword ? 'Hide passwords' : 'Show passwords'}</button>
              </>
            )}
            {currentUser && <p className="text-sm text-gray-600">Your account has no organization access yet. Choose your company to send an approval request.</p>}
            <div>
              <label htmlFor="signup-organization" className={labelClass}>Requested organization</label>
              <select id="signup-organization" required disabled={Boolean(loading)} value={organization} onChange={(e) => setOrganization(e.target.value as RequestedTenant | '')} aria-describedby={errorDescription} className={`${inputClass} bg-white`}>
                <option value="">Choose your organization</option>
                <option value="bajaj">Bajaj Finserv</option>
                <option value="tata">Tata Capital</option>
                <option value="apparel">Apparel</option>
              </select>
            </div>
            <button type="submit" disabled={Boolean(loading)} className="w-full py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 text-white rounded-lg text-sm font-medium">
              {loading === 'signup' ? 'Creating account...' : loading === 'request' ? 'Sending request...' : currentUser ? 'Request company access' : 'Create account and request access'}
            </button>
          </form>
        )}

        {currentUser ? (
          <div className="flex flex-wrap gap-3 border-t border-gray-100 pt-4">
            <button type="button" onClick={handleRefresh} disabled={Boolean(loading)} className="flex-1 rounded-lg bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 px-4 py-2.5 text-sm font-medium text-white">{loading === 'refresh' ? 'Checking approval...' : 'Refresh approval status'}</button>
            <button type="button" onClick={logout} className="rounded-lg border border-gray-300 px-4 py-2.5 text-sm font-medium text-gray-600 hover:bg-gray-50">Sign out</button>
          </div>
        ) : (
          <p className="border-t border-gray-100 pt-4 text-center text-sm text-gray-500">Already have an account? <Link href="/login" className="font-medium text-indigo-600 hover:underline">Sign in</Link></p>
        )}
      </main>
    </div>
  );
}
