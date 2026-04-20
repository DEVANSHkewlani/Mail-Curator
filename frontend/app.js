/**
 * app.js — Shared state & utilities for The Curator Mail
 *
 * v3 Update: 
 *   - Multi-user authentication support (JWT)
 *   - Automatic redirection to login
 *   - Authorization headers for all API calls
 *   - Logout functionality
 */

// ─── Authentication Persistence ───────────────────────────────────────────────
const AUTH = {
  get token() { return localStorage.getItem('curator_token'); },
  set token(v) { if(v) localStorage.setItem('curator_token', v); else localStorage.removeItem('curator_token'); },
  get userEmail() { return localStorage.getItem('curator_user_email'); },
  set userEmail(v) { if(v) localStorage.setItem('curator_user_email', v); else localStorage.removeItem('curator_user_email'); },
  
  logout() {
    this.token = null;
    this.userEmail = null;
    window.location.href = '/login.html';
  }
};

// ─── Shared State ─────────────────────────────────────────────────────────────
const AppState = {
  get contacts() { try { return JSON.parse(localStorage.getItem('cm_contacts') || '[]'); } catch { return []; } },
  set contacts(v) { localStorage.setItem('cm_contacts', JSON.stringify(v)); },

  get skipped() { try { return JSON.parse(localStorage.getItem('cm_skipped') || '[]'); } catch { return []; } },
  set skipped(v) { localStorage.setItem('cm_skipped', JSON.stringify(v)); },

  get csvHeaders() { try { return JSON.parse(localStorage.getItem('cm_csvHeaders') || '[]'); } catch { return []; } },
  set csvHeaders(v) { localStorage.setItem('cm_csvHeaders', JSON.stringify(v)); },

  get columnMap() { try { return JSON.parse(localStorage.getItem('cm_columnMap') || '{"name":"","email":""}'); } catch { return { name: '', email: '' }; } },
  set columnMap(v) { localStorage.setItem('cm_columnMap', JSON.stringify(v)); },

  get attachments() { try { return JSON.parse(localStorage.getItem('cm_attachments') || '[]'); } catch { return []; } },
  set attachments(v) { localStorage.setItem('cm_attachments', JSON.stringify(v)); },

  get smtp() { try { return JSON.parse(localStorage.getItem('cm_smtp') || '{}'); } catch { return {}; } },
  set smtp(v) { localStorage.setItem('cm_smtp', JSON.stringify(v)); },

  get smtpTested() { return localStorage.getItem('cm_smtpTested') === 'true'; },
  set smtpTested(v) { localStorage.setItem('cm_smtpTested', String(v)); },

  get compose() {
    try {
      const d = JSON.parse(localStorage.getItem('cm_compose') || '{}');
      if (!d.fontFamily) d.fontFamily = "'Aptos', 'Calibri', 'Inter', sans-serif";
      if (!d.fontSize) d.fontSize = "4"; // Default to magic number 4 (16px)
      if (!d.textColor) d.textColor = "#1b1c19";
      if (!d.cc) d.cc = "";
      if (d.signatureEnabled === undefined) d.signatureEnabled = true;
      if (!d.signature) d.signature = `
<div style="margin-top: 32px; border-top: 1px solid #f0eee9; padding-top: 20px; font-family: 'Inter', 'Arial', sans-serif; color: #5b4039; line-height: 1.6;">
  <div style="font-weight: 700; font-size: 15px; color: #1b1c19; margin-bottom: 2px;">Your Name</div>
  <div style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #b02f00; font-weight: 600; margin-bottom: 12px;">Strategic Communications | The Curator</div>
  <div style="font-size: 12px; color: #907067;">
    A bespoke email suite for editorial excellence.<br>
    <a href="https://curatormail.io" style="color: #ff5722; text-decoration: none; font-weight: 500;">www.curatormail.io</a>
  </div>
</div>`;
      return d;
    } catch { return {}; }
  },
  set compose(v) { localStorage.setItem('cm_compose', JSON.stringify(v)); },

  get sendLog() { try { return JSON.parse(localStorage.getItem('cm_sendLog') || '[]'); } catch { return []; } },
  set sendLog(v) { localStorage.setItem('cm_sendLog', JSON.stringify(v)); },

  get sendResults() { try { return JSON.parse(localStorage.getItem('cm_sendResults') || 'null'); } catch { return null; } },
  set sendResults(v) { localStorage.setItem('cm_sendResults', JSON.stringify(v)); },

  get sentMessageIds() { try { return JSON.parse(localStorage.getItem('cm_sentMsgIds') || '{}'); } catch { return {}; } },
  set sentMessageIds(v) { localStorage.setItem('cm_sentMsgIds', JSON.stringify(v)); },
};

// ─── API Config ───────────────────────────────────────────────────────────────
const API_BASE = (typeof window !== 'undefined' && window.location.origin !== 'null')
  ? window.location.origin
  : 'http://localhost:8000';

function _authHeaders(headers = {}) {
  const token = AUTH.token;
  if (token) headers['Authorization'] = `Bearer ${token}`;
  return headers;
}

/**
 * Handle 401 Unauthorised globally.
 */
async function _checkRes(res) {
  if (res.status === 401) {
    // Token expired or invalid
    AUTH.logout();
    throw new Error('Session expired. Please log in again.');
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

async function apiPost(path, body = {}) {
  const res = await fetch(API_BASE + path, {
    method: 'POST',
    headers: _authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(body),
  });
  return _checkRes(res);
}

async function apiGet(path) {
  const res = await fetch(API_BASE + path, {
    headers: _authHeaders()
  });
  return _checkRes(res);
}

async function apiDelete(path) {
  const res = await fetch(API_BASE + path, { 
    method: 'DELETE',
    headers: _authHeaders()
  });
  if (res.status === 401) AUTH.logout();
  if (!res.ok) console.warn('DELETE failed:', path);
}

async function apiUploadFile(file) {
  const fd = new FormData();
  fd.append('file', file);
  const res = await fetch(API_BASE + '/attachments/upload', { 
    method: 'POST', 
    headers: _authHeaders(),
    body: fd 
  });
  return _checkRes(res);
}

async function apiDeleteFile(name) {
  return apiDelete('/attachments/' + encodeURIComponent(name));
}

// ─── Navigation ───────────────────────────────────────────────────────────────
const PAGES = {
  compose: 'compose.html',
  contacts: 'contacts.html',
  attachments: 'attachments.html',
  send: 'send.html',
};

function navigate(page) {
  const target = PAGES[page];
  if (!target) return;
  window.location.href = target;
}

// ─── Client-side Protection ──────────────────────────────────────────────────
(function checkAuth() {
  const path = window.location.pathname;
  const isAuthPage = path === '/login' || path === '/login.html' || path === '/signup' || path === '/signup.html';
  const isStatic = path.includes('sw.js') || path.includes('manifest.json') || path.includes('/attachments/');
  
  if (!AUTH.token && !isAuthPage && !isStatic) {
    window.location.href = '/login.html';
  }
})();

// ─── Toast & UI ───────────────────────────────────────────────────────────────
function showToast(msg, type = 'info') {
  let t = document.getElementById('cm-toast');
  if (!t) {
    t = document.createElement('div');
    t.id = 'cm-toast';
    t.style.cssText = `
      position:fixed; top:20px; right:20px; z-index:9999;
      padding:12px 20px; border-radius:4px; font-size:13px; font-weight:500;
      font-family:'Outfit',sans-serif; color:#fff; max-width:320px;
      transform:translateY(-8px); opacity:0;
      transition:all 0.25s ease; pointer-events:none;
      box-shadow: 0 4px 20px rgba(0,0,0,0.15);
    `;
    document.body.appendChild(t);
  }
  const colors = { info: '#1b1c19', success: '#1a5c2e', error: '#ba1a1a', warning: '#7a4f00' };
  t.style.background = colors[type] || colors.info;
  t.textContent = msg;
  t.style.opacity = '1';
  t.style.transform = 'translateY(0)';
  t.style.pointerEvents = 'auto';
  clearTimeout(t._timer);
  t._timer = setTimeout(() => {
    t.style.opacity = '0';
    t.style.transform = 'translateY(-8px)';
    t.style.pointerEvents = 'none';
  }, 3500);
}

function updateStatusBar() {
  const n = AppState.contacts.length;
  const a = AppState.attachments.length;
  const smtp = AppState.smtp;
  const tested = AppState.smtpTested;
  const el = id => document.getElementById(id);

  if (el('sb-contacts')) el('sb-contacts').textContent = `${n} contact${n !== 1 ? 's' : ''}`;
  if (el('sb-attachments')) el('sb-attachments').textContent = `${a} attachment${a !== 1 ? 's' : ''}`;
  if (el('sb-smtp')) {
    el('sb-smtp').textContent = tested ? `SMTP: ${smtp.host || ''}` : 'SMTP: not configured';
    el('sb-smtp').style.color = tested ? '#1a5c2e' : '#5b4039';
  }
  if (el('footer-contacts')) el('footer-contacts').textContent = `${n} contacts`;
  if (el('footer-attachments')) el('footer-attachments').textContent = `${a} attachments`;
  if (el('footer-smtp')) {
    el('footer-smtp').textContent = tested ? 'SMTP: connected' : 'SMTP: not configured';
    el('footer-smtp').style.color = tested ? '#1a5c2e' : '#907067';
  }
}

function getFontSizePx(magic) {
  const m = String(magic);
  return { '1': '10', '2': '12', '3': '14', '4': '16', '5': '18', '6': '24' }[m] || m;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function fillPlaceholders(text, contact, map, includeSignature = false) {
  if (!text) return '';
  let body = text;
  if (contact) {
    const nameKey = map?.name || 'name';
    const emailKey = map?.email || 'email';
    body = text
      .replace(/\$name/g, contact[nameKey] || contact.name || '')
      .replace(/\$company/g, contact.company || contact.Company || '')
      .replace(/\$role/g, contact.role || contact.Role || '')
      .replace(/\$city/g, contact.city || contact.City || '')
      .replace(/\$email/g, contact[emailKey] || contact.email || '');
  }
  if (includeSignature) {
    const c = AppState.compose;
    if (c.signatureEnabled !== false && c.signature) {
      body += c.signature;
    }
  }
  return body;
}

function debounce(func, timeout = 1000) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => { func.apply(this, args); }, timeout);
  };
}

function formatBytes(bytes) {
  const value = Number(bytes) || 0;
  if (value === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const idx = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  const amount = value / Math.pow(1024, idx);
  return `${amount >= 10 || idx === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[idx]}`;
}

function parseCSVLine(line) {
  const cells = [];
  let cell = '';
  let quoted = false;

  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    const next = line[i + 1];

    if (ch === '"' && quoted && next === '"') {
      cell += '"';
      i++;
    } else if (ch === '"') {
      quoted = !quoted;
    } else if (ch === ',' && !quoted) {
      cells.push(cell.trim());
      cell = '';
    } else {
      cell += ch;
    }
  }

  cells.push(cell.trim());
  return cells;
}

function parseCSVText(text) {
  const clean = String(text || '').replace(/^\uFEFF/, '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  const lines = clean.split('\n').filter(line => line.trim().length > 0);
  if (lines.length < 2) return null;

  const headers = parseCSVLine(lines[0]).map(h => h.trim()).filter(Boolean);
  if (!headers.length) return null;

  const lowerHeaders = headers.map(h => h.toLowerCase().replace(/\s+/g, ''));
  const findHeader = candidates => {
    for (const candidate of candidates) {
      const idx = lowerHeaders.indexOf(candidate);
      if (idx !== -1) return headers[idx];
    }
    return '';
  };

  const map = {
    name: findHeader(['name', 'fullname', 'contactname', 'firstname']),
    email: findHeader(['email', 'emailaddress', 'mail']),
    company: findHeader(['company', 'organization', 'organisation']),
    role: findHeader(['role', 'title', 'jobtitle', 'position']),
    city: findHeader(['city', 'location']),
  };
  if (!map.email) map.email = headers[0];

  const contacts = [];
  const skipped = [];
  const emailRe = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  lines.slice(1).forEach((line, index) => {
    const values = parseCSVLine(line);
    const row = {};
    headers.forEach((header, i) => {
      row[header] = values[i] || '';
    });

    const email = String(row[map.email] || '').trim();
    if (!email || !emailRe.test(email)) {
      skipped.push({ row, reason: 'Invalid email', line: index + 2 });
      return;
    }
    row[map.email] = email;
    contacts.push(row);
  });

  return { headers, contacts, skipped, map };
}

// ─── Active nav highlight ─────────────────────────────────────────────────────
function highlightNav(page) {
  document.querySelectorAll('[data-nav]').forEach(el => {
    const isActive = el.dataset.nav === page;
    el.classList.toggle('nav-active', isActive);
    el.classList.toggle('nav-inactive', !isActive);
  });
}

// ─── PWA Service Worker ───────────────────────────────────────────────────────
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(err => {
      console.warn('SW registration failed:', err);
    });
  });
}
