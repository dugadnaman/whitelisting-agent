'use client';

import Link from 'next/link';
import { useApp } from '@/lib/context';

export default function SignupPage() {
  const { currentUser } = useApp();
  const canProvision = currentUser?.role === 'admin' || currentUser?.role === 'superadmin';

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 p-6">
      <div className="w-full max-w-md rounded-2xl border bg-white p-8 shadow-lg space-y-5">
        <h1 className="text-xl font-bold text-gray-900">Join your company workspace</h1>
        <p className="text-sm text-gray-600">
          Accounts are provisioned by your organization administrator. Ask them to add you through
          Settings → Team Members and share your credentials securely, then sign in below.
          Public signup cannot grant access to company data.
        </p>
        <p className="text-sm text-gray-600">
          Setting up a new company? Your platform administrator must bootstrap the first company
          admin on the backend host. No default accounts or passwords are created automatically.
        </p>
        {canProvision && (
          <Link href="/settings" className="block rounded-lg bg-blue-600 p-3 text-center text-sm font-semibold text-white">
            Open team provisioning
          </Link>
        )}
        <Link href="/login" className="block text-center text-sm font-semibold text-blue-600">Sign in</Link>
      </div>
    </div>
  );
}
