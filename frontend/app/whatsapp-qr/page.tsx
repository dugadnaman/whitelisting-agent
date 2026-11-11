'use client';

import { useState, useEffect } from 'react';
import { fetchWhatsAppGatewayStatus, fetchWhatsAppGatewayQr } from '@/lib/api';

type GatewayStatus = {
  ok: boolean;
  status: string;
  connected: boolean;
  user?: { id: string; name: string };
  has_qr?: boolean;
  error?: string;
};

type QrData = {
  ok: boolean;
  status: string;
  raw_qr?: string;
  qr_image?: string;
  message?: string;
  error?: string;
};

export default function WhatsAppQrPage() {
  const [status, setStatus] = useState<GatewayStatus | null>(null);
  const [qr, setQr] = useState<QrData | null>(null);
  const [loading, setLoading] = useState(true);

  const checkConnection = async () => {
    try {
      const s = await fetchWhatsAppGatewayStatus();
      setStatus(s);
      if (!s.connected) {
        const q = await fetchWhatsAppGatewayQr();
        setQr(q);
      }
    } catch {
      setStatus({ ok: false, status: 'OFFLINE', connected: false });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    checkConnection();
    const interval = setInterval(checkConnection, 4000);
    return () => clearInterval(interval);
  }, []);

  return (
    <main className="workspace-page min-h-screen bg-gray-50 px-4 py-8 sm:px-6 sm:py-12">
      <div className="mx-auto w-full max-w-2xl space-y-6">
        <header className="space-y-2">
          <p className="workspace-eyebrow">Work management · SLA alerts</p>
          <h1 className="workspace-heading">Connect WhatsApp gateway</h1>
          <p className="workspace-description">Link the phone used by the SLA gateway. This connection is separate from your Karix campaign credentials.</p>
        </header>

        <section className="workspace-panel rounded-xl border border-gray-200 bg-white p-5 sm:p-8 space-y-6" aria-label="Gateway connection">
          {loading ? (
            <p role="status" className="py-12 text-center text-sm text-gray-600">Checking the WhatsApp gateway…</p>
          ) : status?.connected ? (
            <div className="space-y-4">
              <span className="inline-flex rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-1 text-sm font-medium text-emerald-800" role="status">WhatsApp linked</span>
              <h2 className="text-lg font-medium text-gray-900">Your gateway is connected</h2>
              <p className="text-sm text-gray-600 break-words">Connected as <strong className="font-medium text-gray-900">{status.user?.name || status.user?.id || 'a WhatsApp user'}</strong>.</p>
              <p className="text-sm text-gray-600">Return to Work Management to manage SLA work and alert settings.</p>
              <a href="/work-management" className="workspace-button-primary inline-flex">Go to work management</a>
            </div>
          ) : (
            <div className="space-y-6">
              <div className="workspace-guide space-y-3">
                <h2 className="text-sm font-medium text-gray-900">Link your phone</h2>
                <ol className="list-decimal pl-5 space-y-2 text-sm leading-relaxed text-gray-600">
                  <li>Open WhatsApp on the phone you want to link.</li>
                  <li>Open <strong className="font-medium">Settings / Menu (⋮)</strong>, then <strong className="font-medium">Linked Devices</strong>.</li>
                  <li>Tap <strong className="font-medium">Link a Device</strong> and scan the QR code below.</li>
                </ol>
              </div>

              {(status?.error || qr?.error || !status?.ok || qr?.ok === false) && (
                <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800 break-words">
                  <p className="font-medium">Gateway connection unavailable</p>
                  <p className="mt-1">{status?.error || qr?.error || 'The gateway could not provide a connection. Check that the gateway is running, then refresh its status.'}</p>
                </div>
              )}

              <div className="mx-auto flex aspect-square w-full max-w-64 items-center justify-center rounded-xl border border-gray-200 bg-white p-3">
                {status?.ok && qr?.ok && qr.qr_image ? (
                  <img src={qr.qr_image} alt="WhatsApp pairing QR code. Scan from Linked Devices on your phone." className="w-full h-full object-contain" />
                ) : (
                  <p role="status" className="p-4 text-center text-sm leading-relaxed text-gray-600">
                    {!status?.ok || qr?.ok === false ? 'QR code unavailable until the gateway responds.' : qr?.message || 'Waiting for the gateway to provide a pairing QR code…'}
                  </p>
                )}
              </div>
              <p className="text-sm text-gray-500 text-center">Keep this page open. The connection is checked every 4 seconds.</p>
            </div>
          )}

          {!loading && (
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-gray-200 pt-4">
              <p className="text-sm text-gray-600 break-words">Gateway status: <strong className="font-medium text-gray-900">{status?.status || 'Unknown'}</strong></p>
              <button type="button" onClick={checkConnection} className="workspace-button">Refresh status</button>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
