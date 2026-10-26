import type { Channel } from './api';

const ACCOUNT_LABELS: Record<string, string> = {
  bajaj: 'Bajaj Finserv', apparel: 'Apparel', tata: 'Tata Capital',
  tcl_promo: 'Tata Capital · Promotional', tcl_trans: 'Tata Capital · Transactional',
  tchfl: 'Tata Capital · Housing Finance', wealth: 'Tata Capital · Wealth', moneyfy: 'Tata Capital · Moneyfy',
};
const CHANNEL_LABELS: Record<Channel, string> = { whatsapp: 'WhatsApp', rcs: 'RCS', sms: 'SMS' };

export function destinationAccountLabel(account: string, fallback?: string): string {
  return ACCOUNT_LABELS[account] || (account === 'all' ? 'All accounts' : fallback || account);
}

export function destinationLabel(account: string, channel: Channel, fallback?: string): string {
  const name = destinationAccountLabel(account, fallback);
  return account === 'all' ? `${name} · Overview` : `${name} · ${CHANNEL_LABELS[channel]}`;
}

export function destinationChannels(account: string): Channel[] {
  return account === 'apparel' ? ['rcs'] : ['whatsapp', 'rcs', 'sms'];
}
