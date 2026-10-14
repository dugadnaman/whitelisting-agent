/**
 * Self-Hosted WhatsApp-Web Gateway for SLA Dispatcher & Team Alerts.
 * 
 * Powered by @whiskeysockets/baileys (pure Node.js WebSocket, no heavy headless browser).
 * 
 * Endpoints:
 * - GET  /health          Healthcheck
 * - GET  /status          Connection state & active account
 * - GET  /qr              Raw QR code data & base64 PNG data URL
 * - GET  /qr.html         Interactive QR code scan page for easy mobile scanning
 * - GET  /groups          List all WhatsApp groups available for the connected number
 * - POST /send-message    Send text message to a group or phone number
 */

const express = require('express');
const { makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion } = require('@whiskeysockets/baileys');
const pino = require('pino');
const qrcode = require('qrcode');
const qrcodeTerminal = require('qrcode-terminal');
const path = require('path');
const fs = require('fs');

const PORT = parseInt(process.env.WHATSAPP_GATEWAY_PORT || process.env.PORT || '5005', 10);
const SESSION_DIR = process.env.WHATSAPP_SESSION_DIR || path.join(__dirname, 'session_auth');

if (!fs.existsSync(SESSION_DIR)) {
  fs.mkdirSync(SESSION_DIR, { recursive: true });
}
const PID_FILE = path.join(SESSION_DIR, 'gateway.pid');
try {
  if (fs.existsSync(PID_FILE)) {
    const existingPid = parseInt(fs.readFileSync(PID_FILE, 'utf-8').trim(), 10);
    if (existingPid && existingPid !== process.pid) {
      try {
        process.kill(existingPid, 0);
        console.log(`[WhatsApp Gateway] Terminating duplicate instance (PID ${existingPid})...`);
        process.kill(existingPid, 'SIGTERM');
      } catch (e) {}
    }
  }
  fs.writeFileSync(PID_FILE, String(process.pid));
} catch (e) {}

process.on('exit', () => {
  try { if (fs.existsSync(PID_FILE)) fs.unlinkSync(PID_FILE); } catch (e) {}
});

const app = express();
app.use(express.json());

// Enable CORS
app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.header('Access-Control-Allow-Headers', 'Content-Type, Authorization');
  if (req.method === 'OPTIONS') return res.sendStatus(200);
  next();
});

// Gateway state
let sock = null;
let currentStatus = 'INITIALIZING'; // 'INITIALIZING' | 'SCAN_QR' | 'CONNECTING' | 'CONNECTED' | 'DISCONNECTED'
let rawQr = null;
let base64QrImage = null;
let connectedUser = null;
let cachedGroups = [];
let reconnectAttempts = 0;

const logger = pino({ level: process.env.LOG_LEVEL || 'warn' });

async function restoreSessionFromDatabase() {
  const backendUrl = process.env.BACKEND_INTERNAL_URL || 'http://127.0.0.1:8000';
  try {
    const res = await fetch(`${backendUrl}/api/whatsapp-gateway/session/restore`);
    if (res.ok) {
      const data = await res.json();
      if (data.session && typeof data.session === 'object') {
        const keys = Object.keys(data.session);
        if (keys.length > 0) {
          console.log(`[WhatsApp Gateway] Restoring ${keys.length} session auth keys from database...`);
          for (const k of keys) {
            const filePath = path.join(SESSION_DIR, k);
            fs.writeFileSync(filePath, data.session[k], 'utf-8');
          }
          console.log('[WhatsApp Gateway] Successfully restored Baileys session from persistent database!');
        }
      }
    }
  } catch (err) {
    console.log('[WhatsApp Gateway] Database session restore notice (will proceed with local disk):', err.message);
  }
}

async function connectToWhatsApp() {
  currentStatus = 'CONNECTING';
  const { state, saveCreds } = await useMultiFileAuthState(SESSION_DIR);
  const { version, isLatest } = await fetchLatestBaileysVersion().catch(() => ({ version: [2, 3000, 1015901307], isLatest: false }));

  console.log(`[WhatsApp Gateway] Starting Baileys WA Socket (version: ${version.join('.')}, isLatest: ${isLatest})...`);

  sock = makeWASocket({
    version,
    auth: state,
    logger,
    printQRInTerminal: false, // handled custom below
    browser: ['Karix SLA Dispatcher', 'Chrome', '1.0.0'],
    syncFullHistory: false,
    generateHighQualityLinkPreview: false,
  });

  sock.ev.on('creds.update', async () => {
    await saveCreds();
    try {
      const backendUrl = process.env.BACKEND_INTERNAL_URL || 'http://127.0.0.1:8000';
      const credsPath = path.join(SESSION_DIR, 'creds.json');
      if (fs.existsSync(credsPath)) {
        const content = fs.readFileSync(credsPath, 'utf-8');
        fetch(`${backendUrl}/api/whatsapp-gateway/session/backup`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ key: 'creds.json', value: content }),
        }).catch(() => {});
      }
    } catch (e) {}
  });

  sock.ev.on('connection.update', async (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      currentStatus = 'SCAN_QR';
      rawQr = qr;
      try {
        base64QrImage = await qrcode.toDataURL(qr, { margin: 2, scale: 8 });
      } catch (err) {
        console.error('[WhatsApp Gateway] Error generating QR image:', err);
      }
      console.log('\n========================================================');
      console.log('📱 SCAN THIS WHATSAPP QR CODE (OR OPEN http://localhost:' + PORT + '/qr.html):');
      qrcodeTerminal.generate(qr, { small: true });
      console.log('========================================================\n');
    }

    if (connection === 'close') {
      const statusCode = lastDisconnect?.error?.output?.statusCode;
      const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
      currentStatus = 'DISCONNECTED';
      rawQr = null;
      base64QrImage = null;
      connectedUser = null;
      console.log(`[WhatsApp Gateway] Connection closed (code ${statusCode}). Reconnect: ${shouldReconnect}`);

      if (statusCode === DisconnectReason.loggedOut) {
        console.log('[WhatsApp Gateway] Logged out from WhatsApp. Resetting session...');
        try {
          fs.rmSync(SESSION_DIR, { recursive: true, force: true });
          fs.mkdirSync(SESSION_DIR, { recursive: true });
        } catch (e) {
          console.error('[WhatsApp Gateway] Failed to clear session dir:', e);
        }
        setTimeout(connectToWhatsApp, 2000);
      } else if (statusCode === 440) {
        reconnectAttempts++;
        const delay = Math.min(60000, Math.max(10000, reconnectAttempts * 5000));
        console.log(`[WhatsApp Gateway] Session replaced by another client (code 440). Waiting ${delay / 1000}s before reconnect...`);
        setTimeout(connectToWhatsApp, delay);
      } else if (shouldReconnect) {
        reconnectAttempts++;
        const delay = Math.min(30000, reconnectAttempts * 2000);
        console.log(`[WhatsApp Gateway] Reconnecting in ${delay / 1000}s (attempt ${reconnectAttempts})...`);
        setTimeout(connectToWhatsApp, delay);
      }
    } else if (connection === 'open') {
      currentStatus = 'CONNECTED';
      reconnectAttempts = 0;
      rawQr = null;
      base64QrImage = null;
      connectedUser = sock.user ? {
        id: sock.user.id,
        name: sock.user.name || 'WhatsApp Operator',
      } : null;

      console.log(`\n✅ [WhatsApp Gateway] Connected successfully to WhatsApp as ${connectedUser?.name || connectedUser?.id || 'Connected User'}!\n`);

      // Refresh groups list
      setTimeout(refreshGroups, 3000);
      // Persist session files to database so it survives container recreation
      try {
        const backendUrl = process.env.BACKEND_INTERNAL_URL || 'http://127.0.0.1:8000';
        const files = fs.readdirSync(SESSION_DIR);
        for (const file of files) {
          if (file.endsWith('.json')) {
            const content = fs.readFileSync(path.join(SESSION_DIR, file), 'utf-8');
            fetch(`${backendUrl}/api/whatsapp-gateway/session/backup`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ key: file, value: content }),
            }).catch(() => {});
          }
        }
        console.log('[WhatsApp Gateway] Persisted session files to database backup.');
      } catch (e) {}

    }
  });

  sock.ev.on('groups.update', () => {
    refreshGroups();
  });
}

async function refreshGroups() {
  if (!sock || currentStatus !== 'CONNECTED') return [];
  try {
    const groups = await sock.groupFetchAllParticipating();
    cachedGroups = Object.values(groups).map((g) => ({
      id: g.id,
      name: g.subject,
      creation: g.creation,
      owner: g.owner,
      participants_count: g.participants?.length || 0,
    }));
    console.log(`[WhatsApp Gateway] Cached ${cachedGroups.length} participating WhatsApp groups.`);
    return cachedGroups;
  } catch (err) {
    console.error('[WhatsApp Gateway] Error fetching participating groups:', err.message);
    return cachedGroups;
  }
}

// ---------------------------------------------------------------------------
// HTTP API Endpoints
// ---------------------------------------------------------------------------

app.get('/health', (req, res) => {
  res.json({ ok: true, status: 'healthy', uptime: process.uptime() });
});

app.get('/status', (req, res) => {
  res.json({
    ok: true,
    status: currentStatus,
    connected: currentStatus === 'CONNECTED',
    user: connectedUser,
    has_qr: Boolean(rawQr),
    groups_count: cachedGroups.length,
    session_dir: SESSION_DIR,
  });
});

app.get('/qr', (req, res) => {
  if (currentStatus === 'CONNECTED') {
    return res.json({
      ok: true,
      status: 'CONNECTED',
      message: 'WhatsApp is already linked and ready.',
      user: connectedUser,
    });
  }
  if (!rawQr) {
    return res.json({
      ok: false,
      status: currentStatus,
      message: 'QR code is not ready yet. Please wait a moment...',
    });
  }
  res.json({
    ok: true,
    status: 'SCAN_QR',
    raw_qr: rawQr,
    qr_image: base64QrImage,
  });
});

app.get('/qr.html', (req, res) => {
  res.setHeader('Content-Type', 'text/html; charset=utf-8');
  if (currentStatus === 'CONNECTED') {
    return res.send(`
      <!DOCTYPE html>
      <html>
      <head>
        <title>WhatsApp Gateway - Connected</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
          body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; background: #f0fdf4; color: #166534; }
          .card { background: white; padding: 2rem; border-radius: 1rem; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); text-align: center; max-width: 400px; }
          .badge { display: inline-block; background: #dcfce7; color: #15803d; padding: 0.25rem 0.75rem; border-radius: 9999px; font-weight: 700; font-size: 0.875rem; margin-bottom: 1rem; }
        </style>
      </head>
      <body>
        <div class="card">
          <div class="badge">✓ Linked &amp; Active</div>
          <h2>WhatsApp Connected!</h2>
          <p>The self-hosted gateway is actively connected${connectedUser?.name ? ` as <strong>${connectedUser.name}</strong>` : ''}.</p>
          <p style="font-size: 0.85rem; color: #6b7280;">SLA alerts can now be dispatched to your WhatsApp groups free of cost.</p>
        </div>
      </body>
      </html>
    `);
  }

  res.send(`
    <!DOCTYPE html>
    <html>
    <head>
      <title>Link WhatsApp Gateway</title>
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <meta http-equiv="refresh" content="5">
      <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; background: #f8fafc; color: #1e293b; }
        .card { background: white; padding: 2rem; border-radius: 1.25rem; box-shadow: 0 10px 15px -3px rgb(0 0 0 / 0.1); text-align: center; max-width: 440px; margin: 1rem; border: 1px border #e2e8f0; }
        h2 { margin-top: 0; color: #0f172a; font-size: 1.25rem; }
        ol { text-align: left; font-size: 0.875rem; color: #475569; padding-left: 1.25rem; line-height: 1.6; }
        .qr-box { margin: 1.5rem auto; width: 260px; height: 260px; display: flex; align-items: center; justify-content: center; background: #f1f5f9; border-radius: 0.75rem; border: 1px solid #cbd5e1; }
        .qr-box img { width: 100%; height: 100%; border-radius: 0.75rem; }
        .status { font-size: 0.75rem; color: #64748b; margin-top: 1rem; }
      </style>
    </head>
    <body>
      <div class="card">
        <h2>Link WhatsApp for SLA Alerts</h2>
        <ol>
          <li>Open <strong>WhatsApp</strong> on your phone</li>
          <li>Tap <strong>Settings</strong> or <strong>Menu (⋮)</strong> &rarr; <strong>Linked Devices</strong></li>
          <li>Tap <strong>Link a Device</strong></li>
          <li>Point your phone camera at this QR code:</li>
        </ol>
        <div class="qr-box">
          ${base64QrImage ? `<img src="${base64QrImage}" alt="Scan QR Code" />` : '<div style="color: #64748b; font-size: 0.85rem;">Generating QR code...</div>'}
        </div>
        <div class="status">Status: <strong>${currentStatus}</strong> • Auto-refreshes every 5s</div>
      </div>
    </body>
    </html>
  `);
});

app.get('/groups', async (req, res) => {
  if (currentStatus !== 'CONNECTED') {
    return res.status(503).json({
      ok: false,
      error: 'WhatsApp gateway is not connected yet. Please scan QR code first.',
      status: currentStatus,
    });
  }
  const groups = await refreshGroups();
  res.json({ ok: true, count: groups.length, groups });
});

app.post('/send-message', async (req, res) => {
  if (currentStatus !== 'CONNECTED' || !sock) {
    return res.status(503).json({
      ok: false,
      delivered: false,
      error: 'WhatsApp gateway is not connected. Scan QR code to authenticate.',
      status: currentStatus,
    });
  }

  const { group, group_id, phone, message } = req.body || {};

  if (!message || !message.trim()) {
    return res.status(400).json({ ok: false, error: 'Field "message" is required and cannot be empty.' });
  }

  try {
    let targetJid = null;
    let resolvedName = null;

    // 1. Direct Group JID (e.g. 12036302...@g.us)
    if (group_id && typeof group_id === 'string' && group_id.includes('@g.us')) {
      targetJid = group_id.trim();
      const found = cachedGroups.find((g) => g.id === targetJid);
      resolvedName = found?.name || targetJid;
    }
    // 2. Group Name search
    else if (group && typeof group === 'string') {
      const q = group.trim().toLowerCase();
      if (!cachedGroups.length) await refreshGroups();
      const match = cachedGroups.find((g) => (g.name || '').toLowerCase() === q)
        || cachedGroups.find((g) => (g.name || '').toLowerCase().includes(q));
      if (match) {
        targetJid = match.id;
        resolvedName = match.name;
      } else {
        return res.status(404).json({
          ok: false,
          delivered: false,
          error: `Group matching "${group}" was not found among participating groups.`,
          available_groups: cachedGroups.map((g) => g.name),
        });
      }
    }
    // 3. Direct Phone Number (e.g. +919876543210 -> 919876543210@s.whatsapp.net)
    else if (phone && typeof phone === 'string') {
      const cleanPhone = phone.replace(/[^0-9]/g, '');
      if (cleanPhone.length >= 10) {
        targetJid = `${cleanPhone}@s.whatsapp.net`;
        resolvedName = phone;
      }
    }

    if (!targetJid) {
      return res.status(400).json({
        ok: false,
        error: 'Provide "group" (name), "group_id" (@g.us JID), or "phone".',
      });
    }

    const sent = await sock.sendMessage(targetJid, { text: message });
    console.log(`[WhatsApp Gateway] Sent message to ${resolvedName || targetJid} (${sent.key.id})`);

    return res.json({
      ok: true,
      delivered: true,
      simulated: false,
      channel: 'WhatsApp',
      recipient: targetJid,
      recipient_name: resolvedName,
      message_id: sent.key.id,
      timestamp: Date.now(),
    });
  } catch (err) {
    console.error('[WhatsApp Gateway] Failed to send message:', err);
    return res.status(500).json({
      ok: false,
      delivered: false,
      error: err.message || String(err),
    });
  }
});

// Start Express server and initiate Baileys
app.listen(PORT, '0.0.0.0', async () => {
  console.log(`[WhatsApp Gateway] HTTP API listening on port ${PORT}`);
  console.log(`[WhatsApp Gateway] Scan QR webview at: http://localhost:${PORT}/qr.html`);
  await restoreSessionFromDatabase();
  connectToWhatsApp().catch((err) => {
    console.error('[WhatsApp Gateway] Fatal error during WhatsApp startup:', err);
  });
});
