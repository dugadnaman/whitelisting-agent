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
    <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-xl max-w-md w-full border border-gray-200 overflow-hidden text-center p-6 sm:p-8 space-y-6">
        <div className="flex items-center justify-center gap-2">
          <span className="text-3xl">📱</span>
          <h1 className="text-xl font-bold text-gray-900">WhatsApp SLA Gateway</h1>
        </div>

        {loading ? (
          <div className="py-12 text-sm text-gray-500 animate-pulse">
            Connecting to WhatsApp Gateway...
          </div>
        ) : status?.connected ? (
          <div className="space-y-4 py-6">
            <div className="w-16 h-16 rounded-full bg-emerald-100 text-emerald-600 flex items-center justify-center text-3xl mx-auto shadow-inner">
              ✓
            </div>
            <div>
              <span className="inline-block px-3 py-1 rounded-full text-xs font-bold bg-emerald-50 text-emerald-700 border border-emerald-200 mb-2">
                Connected &amp; Active
              </span>
              <h2 className="text-lg font-bold text-gray-900">WhatsApp Linked Successfully</h2>
              <p className="text-xs text-gray-500 mt-1">
                Connected as: <strong className="text-gray-800">{status.user?.name || status.user?.id || 'Connected User'}</strong>
              </p>
            </div>
            <p className="text-xs text-emerald-700 bg-emerald-50/60 p-3 rounded-xl border border-emerald-100">
              Your SLA alerts will dispatch autonomously to <strong>Internal_TCL&lt;&gt;Att</strong> at 10:00 AM, 1:00 PM, and 4:00 PM IST.
            </p>
            <a
              href="/work-management"
              className="inline-block px-5 py-2.5 bg-gray-900 hover:bg-black text-white text-xs font-bold rounded-xl transition shadow"
            >
              Go to Work Management &rarr;
            </a>
          </div>
        ) : (
          <div className="space-y-5">
            <div className="text-left bg-gray-50 p-3.5 rounded-xl border border-gray-200 text-xs text-gray-600 space-y-1.5">
              <span className="font-bold text-gray-900 block mb-1">How to Link:</span>
              <ol className="list-decimal pl-4 space-y-1">
                <li>Open <strong>WhatsApp</strong> on your phone</li>
                <li>Tap <strong>Settings / Menu (⋮)</strong> &rarr; <strong>Linked Devices</strong></li>
                <li>Tap <strong>Link a Device</strong></li>
                <li>Scan the QR code below:</li>
              </ol>
            </div>

            <div className="w-64 h-64 mx-auto bg-gray-50 border border-gray-200 rounded-2xl flex items-center justify-center p-3 shadow-inner">
              {qr?.qr_image ? (
                <img src={qr.qr_image} alt="Scan QR Code" className="w-full h-full object-contain rounded-xl" />
              ) : (
                <div className="text-xs text-gray-400 p-4">
                  {status?.status === 'OFFLINE' ? (
                    <div className="space-y-1">
                      <p className="font-bold text-amber-700">Gateway Offline</p>
                      <p className="text-[11px] text-gray-500">The gateway container is starting up...</p>
                    </div>
                  ) : (
                    'Generating pairing QR code...'
                  )}
                </div>
              )}
            </div>

            <div className="text-[11px] text-gray-400">
              Auto-refreshing every 4 seconds • Status: <strong>{status?.status || 'INITIALIZING'}</strong>
            </div>

            <button
              type="button"
              onClick={checkConnection}
              className="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs font-semibold rounded-lg transition"
            >
              🔄 Refresh Status
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
