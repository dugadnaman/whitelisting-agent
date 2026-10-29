'use client';

import { useRef, useState } from 'react';
import { useApp } from '@/lib/context';
import type { Channel } from '@/lib/api';
import { destinationAccountLabel, destinationChannels, destinationLabel } from '@/lib/destination';

const CHANNEL_NAMES: Record<Channel, string> = { whatsapp: 'WhatsApp', rcs: 'RCS', sms: 'SMS' };

export default function DestinationSwitcher() {
  const { account, channel, accounts, currentUser, getAccountLabel, setDestination } = useApp();
  const dialog = useRef<HTMLDialogElement>(null);
  const [nextAccount, setNextAccount] = useState(account);
  const [nextChannel, setNextChannel] = useState<Channel>(channel);
  const [message, setMessage] = useState('');
  const label = destinationLabel(account, channel, getAccountLabel(account));

  const open = () => {
    setNextAccount(account);
    setNextChannel(channel);
    setMessage('');
    dialog.current?.showModal();
  };

  return (
    <section aria-label="Whitelisting destination" className="px-4 sm:px-6 py-3">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">{account === 'all' ? 'Viewing overview' : 'Whitelisting for'}</p>
          <p id="current-destination" aria-live="polite" className="text-sm sm:text-base font-semibold text-gray-900 break-words">{label}</p>
        </div>
        <button type="button" onClick={open} aria-haspopup="dialog" className="shrink-0 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-100 focus-visible:ring-2 focus-visible:ring-blue-500">Change</button>
      </div>
      <dialog ref={dialog} aria-labelledby="destination-dialog-title" onClick={(event) => { if (event.target === event.currentTarget) dialog.current?.close(); }} className="m-auto w-[calc(100%-2rem)] max-w-lg rounded-2xl border border-gray-200 bg-white p-0 text-gray-900 shadow-xl backdrop:bg-black/40">
        <form className="p-5 sm:p-6 space-y-5" onSubmit={(event) => {
          event.preventDefault();
          if (setDestination(nextAccount, nextChannel)) dialog.current?.close();
          else setMessage('Destination unchanged. Your current work has been kept.');
        }}>
          <div>
            <h2 id="destination-dialog-title" className="text-lg font-bold">Where are you whitelisting?</h2>
            <p className="mt-1 text-sm text-gray-500">Choose the account and channel together. Nothing is submitted by changing this selection.</p>
          </div>
          <div>
            <label htmlFor="destination-account" className="mb-1 block text-sm font-semibold">Account / sub-account</label>
            <select id="destination-account" required value={nextAccount} onChange={(event) => {
              const selected = event.target.value;
              setNextAccount(selected);
              const channels = destinationChannels(selected, accounts);
              if (!channels.includes(nextChannel)) setNextChannel(channels[0]);
              setMessage('');
            }} className="w-full rounded-lg border border-gray-300 bg-white p-2.5 text-sm">
              <option value="" disabled>Choose an account</option>
              {accounts.map((item) => <option key={item.id} value={item.id}>{destinationAccountLabel(item.id, item.name)}</option>)}
              {currentUser?.role === 'superadmin' && <option value="all">All accounts (overview only)</option>}
            </select>
          </div>
          {nextAccount !== 'all' && <div>
            <label htmlFor="destination-channel" className="mb-1 block text-sm font-semibold">Channel</label>
            <select id="destination-channel" value={nextChannel} onChange={(event) => { setNextChannel(event.target.value as Channel); setMessage(''); }} className="w-full rounded-lg border border-gray-300 bg-white p-2.5 text-sm" disabled={destinationChannels(nextAccount, accounts).length === 1}>
              {destinationChannels(nextAccount, accounts).map((item) => <option key={item} value={item}>{CHANNEL_NAMES[item]}</option>)}
            </select>
            {nextAccount === 'apparel' && <p className="mt-1 text-xs text-gray-500">Apparel supports RCS only.</p>}
            {nextAccount === 'tata' && <p className="mt-1 text-xs text-gray-500">Tata Capital uses VILPOWER SMS DLT only. WhatsApp and RCS remain on their separate sub-accounts.</p>}
          </div>}
          <div className="rounded-lg border border-blue-100 bg-blue-50 p-3 text-sm">
            <p className="font-semibold">{destinationLabel(nextAccount, nextChannel, getAccountLabel(nextAccount))}</p>
            <p className="mt-1 text-blue-900">{nextAccount === 'all' ? 'Overview only. Choose one account before whitelisting or connecting a session.' : `Used for ${nextAccount === 'tata' && nextChannel === 'sms' ? 'VILPOWER SMS DLT' : 'Karix'} template previews, whitelisting and connections in Settings. Existing submissions are never moved.`}</p>
          </div>
          {message && <p role="status" className="text-sm text-amber-800">{message}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => dialog.current?.close()} className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-semibold">Cancel</button>
            <button type="submit" disabled={!nextAccount || (nextAccount !== 'all' && !accounts.some((item) => item.id === nextAccount))} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50">Use this destination</button>
          </div>
        </form>
      </dialog>
    </section>
  );
}
