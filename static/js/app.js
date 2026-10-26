/**
 * EmailCheck - Frontend Application Logic (v2.0)
 * Handles multi-stage verification API requests, live search,
 * status filtering (Valid, Invalid, Risky, Unknown), and RFC 4180 CSV export.
 */

document.addEventListener('DOMContentLoaded', () => {
  // DOM Elements
  const emailsInput = document.getElementById('emailsInput');
  const lineCountBadge = document.getElementById('lineCountBadge');
  const verifyBtn = document.getElementById('verifyBtn');
  const clearBtn = document.getElementById('clearBtn');
  const loadSampleBtn = document.getElementById('loadSampleBtn');
  const btnSpinner = document.getElementById('btnSpinner');
  const btnIcon = document.getElementById('btnIcon');
  const btnText = document.getElementById('btnText');
  const progressContainer = document.getElementById('progressContainer');
  const toastContainer = document.getElementById('toastContainer');

  const emptyState = document.getElementById('emptyState');
  const summarySection = document.getElementById('summarySection');
  const resultsSection = document.getElementById('resultsSection');
  const resultsTableBody = document.getElementById('resultsTableBody');
  const noMatchMessage = document.getElementById('noMatchMessage');
  const searchInput = document.getElementById('searchInput');
  const downloadCsvBtn = document.getElementById('downloadCsvBtn');

  // Summary counts
  const summaryTotal = document.getElementById('summaryTotal');
  const summaryDelivered = document.getElementById('summaryDelivered');
  const summaryBounce = document.getElementById('summaryBounce');
  const summaryRisky = document.getElementById('summaryRisky');
  const summaryUnknown = document.getElementById('summaryUnknown');
  const pctDelivered = document.getElementById('pctDelivered');
  const pctBounce = document.getElementById('pctBounce');
  const pctRisky = document.getElementById('pctRisky');
  const pctUnknown = document.getElementById('pctUnknown');

  // Tab counters
  const tabCountAll = document.getElementById('tabCountAll');
  const tabCountDelivered = document.getElementById('tabCountDelivered');
  const tabCountBounce = document.getElementById('tabCountBounce');
  const tabCountRisky = document.getElementById('tabCountRisky');
  const tabCountUnknown = document.getElementById('tabCountUnknown');
  const filterTabs = document.querySelectorAll('.tab-btn');

  // State
  let currentResults = [];
  let currentFilter = 'all';
  let currentSearch = '';
  const MAX_EMAILS = 100;

  // Real-time line counter
  function updateLineCounter() {
    const rawText = emailsInput.value;
    const lines = rawText.split('\n').map(l => l.trim()).filter(l => l.length > 0);
    const count = lines.length;
    lineCountBadge.textContent = `${count} / ${MAX_EMAILS} addresses`;
    
    if (count > MAX_EMAILS) {
      lineCountBadge.style.color = 'var(--color-red-accent)';
      lineCountBadge.style.borderColor = 'var(--color-red-border)';
    } else {
      lineCountBadge.style.color = '';
      lineCountBadge.style.borderColor = '';
    }
  }

  emailsInput.addEventListener('input', updateLineCounter);

  // Toast Notification Utility
  function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.setAttribute('role', 'alert');

    const iconSvg = type === 'error'
      ? `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`
      : type === 'success'
      ? `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>`
      : `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`;

    toast.innerHTML = `${iconSvg}<span>${escapeHtml(message)}</span>`;
    toastContainer.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(10px)';
      toast.style.transition = 'all 0.25s ease';
      setTimeout(() => toast.remove(), 250);
    }, 4500);
  }

  // HTML Escape Helper to prevent XSS
  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
  }

  // Load Diverse Sample Emails
  loadSampleBtn.addEventListener('click', () => {
    const samples = [
      'support@github.com',
      'contact@google.com',
      'test.user@mailinator.com',
      'service@nonexistent-fake-domain-xyz98741.invalid',
      'malformed..syntax@@domain',
      'alex@example.com',
      'support@github.com' // Duplicate to demonstrate memoization
    ];
    emailsInput.value = samples.join('\n');
    updateLineCounter();
    showToast('Loaded sample email list for testing.', 'info');
  });

  // Clear Form & Results
  clearBtn.addEventListener('click', () => {
    emailsInput.value = '';
    updateLineCounter();
    currentResults = [];
    currentFilter = 'all';
    currentSearch = '';
    searchInput.value = '';

    filterTabs.forEach(t => {
      t.classList.toggle('active', t.getAttribute('data-filter') === 'all');
      t.setAttribute('aria-selected', t.getAttribute('data-filter') === 'all');
    });

    emptyState.style.display = 'block';
    summarySection.style.display = 'none';
    resultsSection.style.display = 'none';
    resultsTableBody.innerHTML = '';
    showToast('Form and results cleared.', 'info');
  });

  // Verify Action
  verifyBtn.addEventListener('click', async (e) => {
    e.preventDefault();

    const rawText = emailsInput.value;
    const lines = rawText
      .split('\n')
      .map(line => line.trim())
      .filter(line => line.length > 0);

    if (lines.length === 0) {
      showToast('Please enter at least one email address to verify.', 'error');
      emailsInput.focus();
      return;
    }

    if (lines.length > MAX_EMAILS) {
      showToast(`Batch exceeds maximum limit of ${MAX_EMAILS} addresses. Please reduce list size.`, 'error');
      return;
    }

    setLoadingState(true);

    try {
      const response = await fetch('/api/verify', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          emails: lines,
          smtp_check: false
        })
      });

      const data = await response.json();

      if (!response.ok || !data.success) {
        throw new Error(data.error || `HTTP error ${response.status}`);
      }

      currentResults = data.results || [];
      renderSummary(data.summary);
      renderResults();
      showToast(`Successfully verified ${data.total} addresses via ${data.provider || 'pipeline'}.`, 'success');

      summarySection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    } catch (err) {
      console.error('Verification failed:', err);
      showToast(err.message || 'Verification failed. Please check network connection.', 'error');
    } finally {
      setLoadingState(false);
    }
  });

  function setLoadingState(isLoading) {
    verifyBtn.disabled = isLoading;
    clearBtn.disabled = isLoading;
    loadSampleBtn.disabled = isLoading;
    emailsInput.disabled = isLoading;

    if (isLoading) {
      btnSpinner.style.display = 'inline-block';
      btnIcon.style.display = 'none';
      btnText.textContent = 'Verifying...';
      progressContainer.style.display = 'block';
    } else {
      btnSpinner.style.display = 'none';
      btnIcon.style.display = 'inline-block';
      btnText.textContent = 'Verify Emails';
      progressContainer.style.display = 'none';
    }
  }

  // Render Summary Cards
  function renderSummary(summary) {
    if (!summary) return;

    emptyState.style.display = 'none';
    summarySection.style.display = 'grid';
    resultsSection.style.display = 'block';

    const total = summary.total || 0;
    const valid = summary.valid !== undefined ? summary.valid : (summary.likely_to_deliver || 0);
    const invalid = summary.invalid !== undefined ? summary.invalid : (summary.likely_to_bounce || 0);
    const risky = summary.risky || 0;
    const unknown = summary.unknown || 0;

    summaryTotal.textContent = total;
    summaryDelivered.textContent = valid;
    summaryBounce.textContent = invalid;
    if (summaryRisky) summaryRisky.textContent = risky;
    summaryUnknown.textContent = unknown;

    pctDelivered.textContent = total > 0 ? `${Math.round((valid / total) * 100)}% of total` : '0%';
    pctBounce.textContent = total > 0 ? `${Math.round((invalid / total) * 100)}% of total` : '0%';
    if (pctRisky) pctRisky.textContent = total > 0 ? `${Math.round((risky / total) * 100)}% of total` : '0%';
    pctUnknown.textContent = total > 0 ? `${Math.round((unknown / total) * 100)}% of total` : '0%';

    // Update tab counters
    tabCountAll.textContent = total;
    tabCountDelivered.textContent = valid;
    tabCountBounce.textContent = invalid;
    if (tabCountRisky) tabCountRisky.textContent = risky;
    tabCountUnknown.textContent = unknown;
  }

  // Render Results Table
  function renderResults() {
    resultsTableBody.innerHTML = '';

    const filtered = currentResults.filter(item => {
      const cls = (item.classification || '').toLowerCase();
      const cat = (item.status_category || '').toLowerCase();
      const filter = currentFilter.toLowerCase();

      let matchesFilter = false;
      if (filter === 'all') {
        matchesFilter = true;
      } else if (filter === 'valid' || filter === 'likely to be delivered') {
        matchesFilter = (cls === 'valid' || cls === 'likely to be delivered' || cat === 'valid');
      } else if (filter === 'invalid' || filter === 'likely to bounce') {
        matchesFilter = (cls === 'invalid' || cls === 'likely to bounce' || cat === 'invalid');
      } else if (filter === 'risky') {
        matchesFilter = (cls === 'risky' || cat === 'risky');
      } else if (filter === 'unknown') {
        matchesFilter = (cls === 'unknown' || cat === 'unknown');
      }

      const q = currentSearch.toLowerCase();
      const matchesSearch = !q ||
        (item.email && item.email.toLowerCase().includes(q)) ||
        (item.domain && item.domain.toLowerCase().includes(q));

      return matchesFilter && matchesSearch;
    });

    if (filtered.length === 0) {
      noMatchMessage.style.display = 'block';
    } else {
      noMatchMessage.style.display = 'none';
    }

    filtered.forEach((item, index) => {
      const row = document.createElement('tr');

      // Classification Badge
      let badgeClass = 'badge-unknown';
      let badgeIcon = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`;

      const cls = (item.classification || '').toLowerCase();
      const cat = (item.status_category || '').toLowerCase();

      if (cls === 'valid' || cls === 'likely to be delivered' || cat === 'valid') {
        badgeClass = 'badge-delivered';
        badgeIcon = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>`;
      } else if (cls === 'invalid' || cls === 'likely to bounce' || cat === 'invalid') {
        badgeClass = 'badge-bounce';
        badgeIcon = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`;
      } else if (cls === 'risky' || cat === 'risky') {
        badgeClass = 'badge-risky';
        badgeIcon = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`;
      }

      // Syntax Pill
      const syntaxPill = item.syntax_valid
        ? `<span class="indicator-pill pill-pass">✓ Valid</span>`
        : `<span class="indicator-pill pill-fail">✗ Malformed</span>`;

      // Domain/MX Pill
      let mxPill = `<span class="indicator-pill pill-untested">—</span>`;
      if (item.domain_status === 'nonexistent') {
        mxPill = `<span class="indicator-pill pill-fail" title="Domain does not exist in DNS">NXDOMAIN</span>`;
      } else if (item.mx_status === 'null_mx') {
        mxPill = `<span class="indicator-pill pill-fail" title="RFC 7505 Null MX (Does not accept email)">Null MX (0 .)</span>`;
      } else if (item.mx_status === 'mx_found') {
        mxPill = `<span class="indicator-pill pill-pass" title="${escapeHtml(item.mx_records ? item.mx_records.join(', ') : '')}">MX Found</span>`;
      } else if (item.mx_status === 'implicit_mx_found') {
        mxPill = `<span class="indicator-pill pill-pass" title="Implicit MX via A/AAAA record">Implicit MX</span>`;
      } else if (item.mx_status === 'no_records') {
        mxPill = `<span class="indicator-pill pill-fail" title="No MX or A records">No Mail Routing</span>`;
      } else if (item.mx_status === 'dns_timeout' || item.domain_status === 'dns_timeout') {
        mxPill = `<span class="indicator-pill pill-untested">DNS Timeout</span>`;
      } else if (item.domain_status === 'untested') {
        mxPill = `<span class="indicator-pill pill-untested">Untested</span>`;
      }

      // Disposable Pill
      let disposablePill = `<span class="indicator-pill pill-pass">Clean</span>`;
      if (item.is_disposable) {
        disposablePill = `<span class="indicator-pill pill-warning" title="Known temporary or disposable email domain">⚠ Disposable</span>`;
      } else if (!item.syntax_valid) {
        disposablePill = `<span class="indicator-pill pill-untested">—</span>`;
      }

      // Recipient / Provider Check Pill
      let recipientPill = `<span class="indicator-pill pill-untested">Unverified</span>`;
      const rec = (item.recipient_status || '').toLowerCase();
      if (rec === 'deliverable') {
        recipientPill = `<span class="indicator-pill pill-pass">✓ Deliverable</span>`;
      } else if (rec === 'undeliverable') {
        recipientPill = `<span class="indicator-pill pill-fail">✗ Undeliverable</span>`;
      } else if (rec === 'risky') {
        recipientPill = `<span class="indicator-pill pill-warning">⚠ Risky</span>`;
      } else if (rec === 'unknown') {
        recipientPill = `<span class="indicator-pill pill-untested">Inconclusive</span>`;
      } else if (rec === 'unavailable') {
        recipientPill = `<span class="indicator-pill pill-untested">No Provider</span>`;
      }

      row.innerHTML = `
        <td style="color: var(--text-muted); font-size: 0.75rem;">${index + 1}</td>
        <td class="email-cell">${escapeHtml(item.email)}</td>
        <td>${syntaxPill}</td>
        <td>${mxPill}</td>
        <td>${disposablePill}</td>
        <td>${recipientPill}</td>
        <td>
          <span class="status-badge ${badgeClass}">
            ${badgeIcon}
            ${escapeHtml(item.classification)}
          </span>
        </td>
        <td class="reason-cell">${escapeHtml(item.reason)}</td>
      `;

      resultsTableBody.appendChild(row);
    });
  }

  // Filter Tabs Event Listeners
  filterTabs.forEach(tab => {
    tab.addEventListener('click', () => {
      filterTabs.forEach(t => {
        t.classList.remove('active');
        t.setAttribute('aria-selected', 'false');
      });
      tab.classList.add('active');
      tab.setAttribute('aria-selected', 'true');

      currentFilter = tab.getAttribute('data-filter');
      renderResults();
    });
  });

  // Search Input Event Listener
  searchInput.addEventListener('input', (e) => {
    currentSearch = e.target.value.trim();
    renderResults();
  });

  // CSV Export Utility (RFC 4180 compliant)
  downloadCsvBtn.addEventListener('click', () => {
    if (!currentResults || currentResults.length === 0) {
      showToast('No results available to download.', 'error');
      return;
    }

    const headers = [
      'Email Address',
      'Classification',
      'Status Category',
      'Syntax Valid',
      'Domain Status',
      'MX Status',
      'Is Disposable',
      'Recipient Status',
      'Provider',
      'Reason'
    ];

    const escapeCsvValue = (val) => {
      if (val === null || val === undefined) return '""';
      const str = String(val).replace(/"/g, '""');
      return `"${str}"`;
    };

    const rows = currentResults.map(item => [
      escapeCsvValue(item.email),
      escapeCsvValue(item.classification),
      escapeCsvValue(item.status_category),
      escapeCsvValue(item.syntax_valid),
      escapeCsvValue(item.domain_status),
      escapeCsvValue(item.mx_status),
      escapeCsvValue(item.is_disposable),
      escapeCsvValue(item.recipient_status),
      escapeCsvValue(item.provider_info ? item.provider_info.provider : 'none'),
      escapeCsvValue(item.reason)
    ].join(','));

    const csvContent = [headers.join(','), ...rows].join('\r\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const downloadLink = document.createElement('a');

    const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    downloadLink.setAttribute('href', url);
    downloadLink.setAttribute('download', `emailcheck_results_${timestamp}.csv`);
    document.body.appendChild(downloadLink);
    downloadLink.click();
    document.body.removeChild(downloadLink);
    URL.revokeObjectURL(url);

    showToast('CSV export downloaded successfully.', 'success');
  });

  updateLineCounter();
});
