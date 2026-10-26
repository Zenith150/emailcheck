/**
 * EmailCheck - Frontend Application Logic (v2.1)
 * Features:
 * - Intelligent multi-delimiter email parsing (newlines, commas, semicolons, spaces)
 * - Real-time duplicate detection & memoization feedback
 * - Division-by-zero safe percentage calculations
 * - Debounced search, multi-factor sorting & pagination
 * - Collapsible per-email diagnostics panel (syntax, MX, Null MX, disposable, provider, duration)
 * - Dedicated Domain Diagnostics inspection tool
 * - Lightweight client-side session history in localStorage
 * - RFC 4180 compliant CSV export
 */

document.addEventListener('DOMContentLoaded', () => {
  // Navigation Tabs
  const tabVerifyEmails = document.getElementById('tabVerifyEmails');
  const tabDomainDiag = document.getElementById('tabDomainDiag');
  const tabHistory = document.getElementById('tabHistory');
  const sectionVerifyEmails = document.getElementById('sectionVerifyEmails');
  const sectionDomainDiag = document.getElementById('sectionDomainDiag');
  const sectionHistory = document.getElementById('sectionHistory');
  const historyBadge = document.getElementById('historyBadge');

  // Batch Verification Elements
  const emailsInput = document.getElementById('emailsInput');
  const lineCountBadge = document.getElementById('lineCountBadge');
  const batchDuplicateHint = document.getElementById('batchDuplicateHint');
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
  const sortSelect = document.getElementById('sortSelect');
  const downloadCsvBtn = document.getElementById('downloadCsvBtn');

  // Summary counts & percentages
  const summaryTotal = document.getElementById('summaryTotal');
  const summaryUniqueMeta = document.getElementById('summaryUniqueMeta');
  const summaryDelivered = document.getElementById('summaryDelivered');
  const summaryBounce = document.getElementById('summaryBounce');
  const summaryRisky = document.getElementById('summaryRisky');
  const summaryUnknown = document.getElementById('summaryUnknown');
  const pctDelivered = document.getElementById('pctDelivered');
  const pctBounce = document.getElementById('pctBounce');
  const pctRisky = document.getElementById('pctRisky');
  const pctUnknown = document.getElementById('pctUnknown');

  // Filter Tab Counters
  const tabCountAll = document.getElementById('tabCountAll');
  const tabCountDelivered = document.getElementById('tabCountDelivered');
  const tabCountBounce = document.getElementById('tabCountBounce');
  const tabCountRisky = document.getElementById('tabCountRisky');
  const tabCountUnknown = document.getElementById('tabCountUnknown');
  const filterTabs = document.querySelectorAll('.tab-btn');

  // Pagination Elements
  const paginationBar = document.getElementById('paginationBar');
  const pageShowingStart = document.getElementById('pageShowingStart');
  const pageShowingEnd = document.getElementById('pageShowingEnd');
  const pageShowingTotal = document.getElementById('pageShowingTotal');
  const pageSizeSelect = document.getElementById('pageSizeSelect');
  const prevPageBtn = document.getElementById('prevPageBtn');
  const nextPageBtn = document.getElementById('nextPageBtn');
  const pageIndicator = document.getElementById('pageIndicator');

  // Domain Diagnostics Elements
  const domainForm = document.getElementById('domainForm');
  const domainInput = document.getElementById('domainInput');
  const domainInspectBtn = document.getElementById('domainInspectBtn');
  const domainSpinner = document.getElementById('domainSpinner');
  const domainBtnIcon = document.getElementById('domainBtnIcon');
  const domainBtnText = document.getElementById('domainBtnText');
  const domainResultCard = document.getElementById('domainResultCard');
  const sampleTags = document.querySelectorAll('.sample-tag');

  // History Elements
  const historyList = document.getElementById('historyList');
  const historyEmptyState = document.getElementById('historyEmptyState');
  const clearHistoryBtn = document.getElementById('clearHistoryBtn');

  // State
  let currentResults = [];
  let currentFilter = 'all';
  let currentSearch = '';
  let currentSort = 'original';
  let currentPage = 1;
  let pageSize = 25;
  const expandedRowIndexes = new Set();
  const MAX_EMAILS = 100;
  const HISTORY_KEY = 'emailcheck_history_v1';
  let searchDebounceTimer = null;

  // ==========================================================================
  // Helper: Escape HTML to prevent XSS and artifact leaks
  // ==========================================================================
  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
  }

  // ==========================================================================
  // Toast Notification Utility
  // ==========================================================================
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

  // ==========================================================================
  // Parser: Multi-Delimiter Input Parser with Duplicate Counting
  // ==========================================================================
  function parseEmailInput(rawText) {
    if (!rawText || typeof rawText !== 'string') return [];
    // Split by newlines, commas, semicolons, and spaces
    const tokens = rawText.split(/[\r\n,;\s]+/);
    const emails = [];
    for (let token of tokens) {
      token = token.trim();
      if (token.length > 0) {
        emails.push(token);
      }
    }
    return emails;
  }

  function updateInputCounter() {
    const emails = parseEmailInput(emailsInput.value);
    const count = emails.length;
    const uniqueCount = new Set(emails.map(e => e.toLowerCase())).size;
    const dupCount = count - uniqueCount;

    lineCountBadge.textContent = `${count} / ${MAX_EMAILS} addresses`;

    if (count > MAX_EMAILS) {
      lineCountBadge.style.color = 'var(--color-red-accent)';
      lineCountBadge.style.borderColor = 'var(--color-red-border)';
    } else {
      lineCountBadge.style.color = '';
      lineCountBadge.style.borderColor = '';
    }

    if (count > 0 && dupCount > 0) {
      batchDuplicateHint.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"/>
          <line x1="12" y1="16" x2="12" y2="12"/>
          <line x1="12" y1="8" x2="12.01" y2="8"/>
        </svg>
        ${count} addresses parsed (${uniqueCount} unique, ${dupCount} duplicate${dupCount !== 1 ? 's' : ''} memoized).
      `;
    } else {
      batchDuplicateHint.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"/>
          <line x1="12" y1="16" x2="12" y2="12"/>
          <line x1="12" y1="8" x2="12.01" y2="8"/>
        </svg>
        Delimiters supported: newlines, commas, semicolons, or spaces. Duplicates are automatically memoized.
      `;
    }
  }

  emailsInput.addEventListener('input', updateInputCounter);

  // ==========================================================================
  // Sample Email Loader
  // ==========================================================================
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
    updateInputCounter();
    showToast('Loaded diverse sample email list for testing.', 'info');
  });

  // ==========================================================================
  // Clear Action
  // ==========================================================================
  clearBtn.addEventListener('click', () => {
    emailsInput.value = '';
    updateInputCounter();
    currentResults = [];
    currentFilter = 'all';
    currentSearch = '';
    currentSort = 'original';
    currentPage = 1;
    expandedRowIndexes.clear();
    searchInput.value = '';
    sortSelect.value = 'original';

    filterTabs.forEach(t => {
      const isAll = t.getAttribute('data-filter') === 'all';
      t.classList.toggle('active', isAll);
      t.setAttribute('aria-selected', isAll ? 'true' : 'false');
    });

    emptyState.style.display = 'block';
    summarySection.style.display = 'none';
    resultsSection.style.display = 'none';
    resultsTableBody.innerHTML = '';
    showToast('Form and results cleared.', 'info');
  });

  // ==========================================================================
  // Batch Verify API Submission
  // ==========================================================================
  verifyBtn.addEventListener('click', async (e) => {
    e.preventDefault();

    const emails = parseEmailInput(emailsInput.value);

    if (emails.length === 0) {
      showToast('Please enter at least one email address to verify.', 'error');
      emailsInput.focus();
      return;
    }

    if (emails.length > MAX_EMAILS) {
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
          emails: emails,
          smtp_check: false
        })
      });

      const data = await response.json();

      if (!response.ok || !data.success) {
        throw new Error(data.error || `HTTP error ${response.status}`);
      }

      currentResults = data.results || [];
      currentPage = 1;
      expandedRowIndexes.clear();

      renderSummary(data.summary, currentResults);
      renderResults();
      saveToHistory(data);

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

  // ==========================================================================
  // Render Summary Cards (Division-by-zero protected)
  // ==========================================================================
  function renderSummary(summary, results = []) {
    if (!summary) return;

    emptyState.style.display = 'none';
    summarySection.style.display = 'grid';
    resultsSection.style.display = 'block';

    const total = Number(summary.total) || 0;
    const valid = summary.valid !== undefined ? Number(summary.valid) : Number(summary.likely_to_deliver || 0);
    const invalid = summary.invalid !== undefined ? Number(summary.invalid) : Number(summary.likely_to_bounce || 0);
    const risky = Number(summary.risky) || 0;
    const unknown = Number(summary.unknown) || 0;

    summaryTotal.textContent = total;
    summaryDelivered.textContent = valid;
    summaryBounce.textContent = invalid;
    if (summaryRisky) summaryRisky.textContent = risky;
    summaryUnknown.textContent = unknown;

    // Division by zero safeguards
    pctDelivered.textContent = total > 0 ? `${((valid / total) * 100).toFixed(1)}% of total` : '0% of total';
    pctBounce.textContent = total > 0 ? `${((invalid / total) * 100).toFixed(1)}% of total` : '0% of total';
    if (pctRisky) pctRisky.textContent = total > 0 ? `${((risky / total) * 100).toFixed(1)}% of total` : '0% of total';
    pctUnknown.textContent = total > 0 ? `${((unknown / total) * 100).toFixed(1)}% of total` : '0% of total';

    // Unique count
    const uniqueCount = new Set(results.map(r => (r.email || '').toLowerCase())).size;
    if (summaryUniqueMeta) {
      summaryUniqueMeta.textContent = `${uniqueCount} unique address${uniqueCount !== 1 ? 'es' : ''}`;
    }

    // Tab counters
    tabCountAll.textContent = total;
    tabCountDelivered.textContent = valid;
    tabCountBounce.textContent = invalid;
    if (tabCountRisky) tabCountRisky.textContent = risky;
    tabCountUnknown.textContent = unknown;
  }

  // ==========================================================================
  // Filter, Search, Sort & Pagination Logic
  // ==========================================================================
  function getFilteredAndSortedResults() {
    // 1. Filter
    let filtered = currentResults.filter(item => {
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
        (item.domain && item.domain.toLowerCase().includes(q)) ||
        (item.reason && item.reason.toLowerCase().includes(q));

      return matchesFilter && matchesSearch;
    });

    // 2. Sort
    if (currentSort === 'email-asc') {
      filtered.sort((a, b) => (a.email || '').localeCompare(b.email || ''));
    } else if (currentSort === 'email-desc') {
      filtered.sort((a, b) => (b.email || '').localeCompare(a.email || ''));
    } else if (currentSort === 'class-valid') {
      const order = { 'valid': 1, 'risky': 2, 'unknown': 3, 'invalid': 4 };
      filtered.sort((a, b) => (order[(a.status_category || '').toLowerCase()] || 99) - (order[(b.status_category || '').toLowerCase()] || 99));
    } else if (currentSort === 'class-invalid') {
      const order = { 'invalid': 1, 'risky': 2, 'unknown': 3, 'valid': 4 };
      filtered.sort((a, b) => (order[(a.status_category || '').toLowerCase()] || 99) - (order[(b.status_category || '').toLowerCase()] || 99));
    }

    return filtered;
  }

  // ==========================================================================
  // Render Results Table & Collapsible Diagnostics Panels
  // ==========================================================================
  function renderResults() {
    resultsTableBody.innerHTML = '';
    const items = getFilteredAndSortedResults();
    const totalCount = items.length;

    if (totalCount === 0) {
      noMatchMessage.style.display = 'block';
      paginationBar.style.display = 'none';
      return;
    }

    noMatchMessage.style.display = 'none';

    // Pagination calculations
    const totalPages = Math.ceil(totalCount / pageSize) || 1;
    if (currentPage > totalPages) currentPage = totalPages;
    if (currentPage < 1) currentPage = 1;

    const startIndex = (currentPage - 1) * pageSize;
    const endIndex = Math.min(startIndex + pageSize, totalCount);
    const pageItems = items.slice(startIndex, endIndex);

    // Update pagination UI
    if (totalCount > pageSize) {
      paginationBar.style.display = 'flex';
      pageShowingStart.textContent = startIndex + 1;
      pageShowingEnd.textContent = endIndex;
      pageShowingTotal.textContent = totalCount;
      pageIndicator.textContent = `Page ${currentPage} / ${totalPages}`;
      prevPageBtn.disabled = (currentPage === 1);
      nextPageBtn.disabled = (currentPage === totalPages);
    } else {
      paginationBar.style.display = 'none';
    }

    pageItems.forEach((item, pageIdx) => {
      const globalIndex = startIndex + pageIdx;
      const isExpanded = expandedRowIndexes.has(item.email);

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
        mxPill = `<span class="indicator-pill pill-fail" title="Domain does not exist in DNS (NXDOMAIN)">NXDOMAIN</span>`;
      } else if (item.is_null_mx || item.mx_status === 'null_mx') {
        mxPill = `<span class="indicator-pill pill-fail" title="RFC 7505 Null MX: Explicitly rejects email">Null MX (0 .)</span>`;
      } else if (item.mx_status === 'mx_found') {
        mxPill = `<span class="indicator-pill pill-pass" title="${escapeHtml(item.mx_records ? item.mx_records.join(', ') : '')}">MX Found</span>`;
      } else if (item.mx_status === 'implicit_mx_found') {
        mxPill = `<span class="indicator-pill pill-pass" title="Implicit MX via A/AAAA record">Implicit MX</span>`;
      } else if (item.mx_status === 'no_records') {
        mxPill = `<span class="indicator-pill pill-fail" title="No MX or A records found">No Routing</span>`;
      } else if (item.mx_status === 'dns_timeout' || item.domain_status === 'dns_timeout') {
        mxPill = `<span class="indicator-pill pill-untested">DNS Timeout</span>`;
      } else if (item.domain_status === 'untested') {
        mxPill = `<span class="indicator-pill pill-untested">Untested</span>`;
      }

      // Disposable Pill
      let disposablePill = `<span class="indicator-pill pill-pass">Clean</span>`;
      if (item.is_disposable) {
        disposablePill = `<span class="indicator-pill pill-warning" title="Known temporary or disposable email service">⚠ Disposable</span>`;
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
      } else if (rec === 'untested') {
        recipientPill = `<span class="indicator-pill pill-untested">Skipped</span>`;
      }

      // Main Table Row
      const row = document.createElement('tr');
      row.className = `result-row ${isExpanded ? 'row-expanded' : ''}`;
      row.innerHTML = `
        <td style="color: var(--text-muted); font-size: 0.75rem;">${globalIndex + 1}</td>
        <td class="email-cell"><strong>${escapeHtml(item.email)}</strong></td>
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
        <td style="text-align: center;">
          <button type="button" class="btn-details-toggle" data-email="${escapeHtml(item.email)}" aria-expanded="${isExpanded}">
            ${isExpanded ? '▲ Hide' : '▼ Details'}
          </button>
        </td>
      `;

      resultsTableBody.appendChild(row);

      // Collapsible Diagnostics Row
      if (isExpanded) {
        const detailsRow = document.createElement('tr');
        detailsRow.className = 'details-row';

        const mxRecordsList = (item.mx_records && item.mx_records.length > 0)
          ? item.mx_records.map(r => `<code>${escapeHtml(r)}</code>`).join('<br/>')
          : '<span class="text-muted">None discovered</span>';

        const nullMxText = item.is_null_mx
          ? '<span style="color: var(--color-red-accent); font-weight:700;">RFC 7505 Null MX (Rejects Email)</span>'
          : '<span style="color: #166534;">Clean (No Null MX record)</span>';

        const durationText = item.duration_ms !== undefined ? `${item.duration_ms} ms` : 'N/A';
        const providerName = (item.provider_info && item.provider_info.provider) ? item.provider_info.provider : 'Local Engine';

        detailsRow.innerHTML = `
          <td colspan="9" style="padding: 0;">
            <div class="email-details-panel">
              <div class="details-grid">
                <div class="detail-item">
                  <span class="detail-label">Normalized Address</span>
                  <span class="detail-value"><code>${escapeHtml(item.normalized_email || item.email)}</code></span>
                </div>
                <div class="detail-item">
                  <span class="detail-label">Domain Status</span>
                  <span class="detail-value">${escapeHtml(item.domain_status || 'untested')}</span>
                </div>
                <div class="detail-item">
                  <span class="detail-label">Discovered Mail Servers (MX)</span>
                  <span class="detail-value">${mxRecordsList}</span>
                </div>
                <div class="detail-item">
                  <span class="detail-label">RFC 7505 Null MX</span>
                  <span class="detail-value">${nullMxText}</span>
                </div>
                <div class="detail-item">
                  <span class="detail-label">Disposable Email Domain</span>
                  <span class="detail-value">${item.is_disposable ? '⚠ Yes (Temporary domain)' : '✓ Clean (Not disposable)'}</span>
                </div>
                <div class="detail-item">
                  <span class="detail-label">Provider Recipient Check</span>
                  <span class="detail-value">${escapeHtml(item.recipient_status || 'Unverified')} (${escapeHtml(providerName)})</span>
                </div>
                <div class="detail-item">
                  <span class="detail-label">Verification Time</span>
                  <span class="detail-value">${durationText}</span>
                </div>
                <div class="detail-item">
                  <span class="detail-label">Final Classification</span>
                  <span class="detail-value"><strong>${escapeHtml(item.classification)}</strong></span>
                </div>
              </div>
              <div class="detail-full-reason">
                <strong>Diagnostic Explanation:</strong> ${escapeHtml(item.reason)}
              </div>
            </div>
          </td>
        `;
        resultsTableBody.appendChild(detailsRow);
      }
    });

    // Attach Toggle Listeners
    document.querySelectorAll('.btn-details-toggle').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const email = btn.getAttribute('data-email');
        if (expandedRowIndexes.has(email)) {
          expandedRowIndexes.delete(email);
        } else {
          expandedRowIndexes.add(email);
        }
        renderResults();
      });
    });
  }

  // ==========================================================================
  // Filter Tabs Event Listeners
  // ==========================================================================
  filterTabs.forEach(tab => {
    tab.addEventListener('click', () => {
      filterTabs.forEach(t => {
        t.classList.remove('active');
        t.setAttribute('aria-selected', 'false');
      });
      tab.classList.add('active');
      tab.setAttribute('aria-selected', 'true');

      currentFilter = tab.getAttribute('data-filter');
      currentPage = 1;
      renderResults();
    });
  });

  // ==========================================================================
  // Search Input (Debounced)
  // ==========================================================================
  searchInput.addEventListener('input', (e) => {
    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = setTimeout(() => {
      currentSearch = e.target.value.trim();
      currentPage = 1;
      renderResults();
    }, 200);
  });

  // ==========================================================================
  // Sort Selector
  // ==========================================================================
  sortSelect.addEventListener('change', (e) => {
    currentSort = e.target.value;
    renderResults();
  });

  // ==========================================================================
  // Pagination Controls
  // ==========================================================================
  pageSizeSelect.addEventListener('change', (e) => {
    pageSize = parseInt(e.target.value, 10) || 25;
    currentPage = 1;
    renderResults();
  });

  prevPageBtn.addEventListener('click', () => {
    if (currentPage > 1) {
      currentPage--;
      renderResults();
    }
  });

  nextPageBtn.addEventListener('click', () => {
    const totalCount = getFilteredAndSortedResults().length;
    const totalPages = Math.ceil(totalCount / pageSize) || 1;
    if (currentPage < totalPages) {
      currentPage++;
      renderResults();
    }
  });

  // ==========================================================================
  // RFC 4180 CSV Export
  // ==========================================================================
  downloadCsvBtn.addEventListener('click', () => {
    if (!currentResults || currentResults.length === 0) {
      showToast('No results available to download.', 'error');
      return;
    }
    exportResultsToCsv(currentResults, 'emailcheck_results');
  });

  function exportResultsToCsv(results, filePrefix) {
    const headers = [
      'Email Address',
      'Normalized Email',
      'Classification',
      'Status Category',
      'Syntax Valid',
      'Domain Status',
      'MX Status',
      'Discovered Mail Servers',
      'Is Null MX',
      'Is Disposable',
      'Recipient Status',
      'Provider',
      'Verification Duration (ms)',
      'Verified At',
      'Diagnostic Explanation'
    ];

    const escapeCsvValue = (val) => {
      if (val === null || val === undefined) return '""';
      const str = String(val).replace(/"/g, '""');
      return `"${str}"`;
    };

    const rows = results.map(item => [
      escapeCsvValue(item.email),
      escapeCsvValue(item.normalized_email || item.email),
      escapeCsvValue(item.classification),
      escapeCsvValue(item.status_category),
      escapeCsvValue(item.syntax_valid),
      escapeCsvValue(item.domain_status),
      escapeCsvValue(item.mx_status),
      escapeCsvValue(item.mx_records ? item.mx_records.join('; ') : ''),
      escapeCsvValue(item.is_null_mx ? 'true' : 'false'),
      escapeCsvValue(item.is_disposable ? 'true' : 'false'),
      escapeCsvValue(item.recipient_status),
      escapeCsvValue(item.provider_info ? item.provider_info.provider : 'Local Engine'),
      escapeCsvValue(item.duration_ms !== undefined ? item.duration_ms : ''),
      escapeCsvValue(item.checked_at || new Date().toISOString()),
      escapeCsvValue(item.reason)
    ].join(','));

    const csvContent = [headers.join(','), ...rows].join('\r\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const downloadLink = document.createElement('a');

    const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    downloadLink.setAttribute('href', url);
    downloadLink.setAttribute('download', `${filePrefix}_${timestamp}.csv`);
    document.body.appendChild(downloadLink);
    downloadLink.click();
    document.body.removeChild(downloadLink);
    URL.revokeObjectURL(url);

    showToast('CSV export downloaded successfully.', 'success');
  }

  // ==========================================================================
  // Domain Diagnostics Tool
  // ==========================================================================
  domainForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const rawDomain = (domainInput.value || '').trim();

    if (!rawDomain) {
      showToast('Please enter a domain name to inspect.', 'error');
      domainInput.focus();
      return;
    }

    domainInspectBtn.disabled = true;
    domainSpinner.style.display = 'inline-block';
    domainBtnIcon.style.display = 'none';
    domainBtnText.textContent = 'Inspecting...';

    try {
      const response = await fetch('/api/domain', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ domain: rawDomain })
      });

      const data = await response.json();

      if (!response.ok || !data.success) {
        throw new Error(data.error || `Domain diagnostics failed (${response.status})`);
      }

      renderDomainDiagnostics(data);
      showToast(`Domain inspection complete for ${data.domain}.`, 'success');

    } catch (err) {
      console.error('Domain inspection failed:', err);
      showToast(err.message || 'Failed to inspect domain.', 'error');
    } finally {
      domainInspectBtn.disabled = false;
      domainSpinner.style.display = 'none';
      domainBtnIcon.style.display = 'inline-block';
      domainBtnText.textContent = 'Inspect Domain';
    }
  });

  sampleTags.forEach(btn => {
    btn.addEventListener('click', () => {
      const sampleDomain = btn.getAttribute('data-domain');
      domainInput.value = sampleDomain;
      domainInspectBtn.click();
    });
  });

  function renderDomainDiagnostics(data) {
    domainResultCard.style.display = 'block';

    const isReady = data.can_receive_email;
    const isReject = data.is_null_mx || data.domain_status === 'nonexistent' || data.mx_status === 'no_records';
    const bannerClass = isReady ? 'verdict-ready' : (isReject ? 'verdict-reject' : 'verdict-inconclusive');

    const mxRecordsHtml = (data.mx_records && data.mx_records.length > 0)
      ? `<ul class="domain-records-list">${data.mx_records.map(r => `<li>${escapeHtml(r)}</li>`).join('')}</ul>`
      : '<p class="text-muted" style="margin-top:0.4rem; font-size:0.8125rem;">No MX or A/AAAA mail routing records published.</p>';

    domainResultCard.innerHTML = `
      <div class="domain-verdict-banner ${bannerClass}">
        <div>
          <span style="font-size:0.75rem; text-transform:uppercase; letter-spacing:0.04em; font-weight:700;">Mail Receptivity Verdict</span>
          <h3 style="font-size:1.05rem; font-weight:800; margin:0.15rem 0;">${escapeHtml(data.verdict)}</h3>
        </div>
        <span class="indicator-pill ${isReady ? 'pill-pass' : 'pill-fail'}">Confidence: ${escapeHtml(data.confidence)}</span>
      </div>

      <div class="details-grid">
        <div class="detail-item">
          <span class="detail-label">Domain Inspected</span>
          <span class="detail-value"><code>${escapeHtml(data.domain)}</code></span>
        </div>
        <div class="detail-item">
          <span class="detail-label">DNS Resolution</span>
          <span class="detail-value">${escapeHtml(data.domain_status)}</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">MX Status</span>
          <span class="detail-value">${escapeHtml(data.mx_status)}</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">RFC 7505 Null MX</span>
          <span class="detail-value">${data.is_null_mx ? '<strong style="color:var(--color-red-accent);">Detected (Rejects all mail)</strong>' : 'Clean (Not published)'}</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Disposable Service</span>
          <span class="detail-value">${data.is_disposable ? '<strong style="color:var(--color-amber-accent);">⚠ Yes (Temporary domain)</strong>' : 'Clean (Legitimate domain)'}</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Query Duration</span>
          <span class="detail-value">${data.duration_ms || 0} ms</span>
        </div>
      </div>

      <div class="domain-records-box">
        <strong style="font-size:0.8125rem; color:var(--text-primary);">Configured Mail Exchangers:</strong>
        ${mxRecordsHtml}
      </div>

      <div class="domain-disclaimer-notice">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0;">
          <circle cx="12" cy="12" r="10"/>
          <line x1="12" y1="16" x2="12" y2="12"/>
          <line x1="12" y1="8" x2="12.01" y2="8"/>
        </svg>
        <span>${escapeHtml(data.disclaimer)}</span>
      </div>
    `;
  }

  // ==========================================================================
  // Verification History (Browser Local Storage)
  // ==========================================================================
  function loadHistory() {
    try {
      const stored = localStorage.getItem(HISTORY_KEY);
      return stored ? JSON.parse(stored) : [];
    } catch (e) {
      console.warn('Could not read from localStorage:', e);
      return [];
    }
  }

  function saveToHistory(verificationData) {
    try {
      const history = loadHistory();
      const session = {
        id: 'session_' + Date.now(),
        timestamp: new Date().toISOString(),
        total: verificationData.total,
        summary: verificationData.summary,
        provider: verificationData.provider || 'local',
        results: verificationData.results || []
      };

      // Keep up to 10 recent sessions
      history.unshift(session);
      if (history.length > 10) history.pop();

      localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
      updateHistoryUI();
    } catch (e) {
      console.warn('Could not save session to localStorage:', e);
    }
  }

  function updateHistoryUI() {
    const history = loadHistory();
    historyList.innerHTML = '';

    if (history.length === 0) {
      historyEmptyState.style.display = 'block';
      clearHistoryBtn.disabled = true;
      historyBadge.style.display = 'none';
      return;
    }

    historyEmptyState.style.display = 'none';
    clearHistoryBtn.disabled = false;
    historyBadge.textContent = history.length;
    historyBadge.style.display = 'inline-block';

    history.forEach(session => {
      const dateStr = new Date(session.timestamp).toLocaleString();
      const summary = session.summary || {};
      const valid = summary.valid || 0;
      const invalid = summary.invalid || 0;
      const risky = summary.risky || 0;
      const unknown = summary.unknown || 0;

      const card = document.createElement('div');
      card.className = 'session-card';
      card.innerHTML = `
        <div class="session-info">
          <div class="session-title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
              <line x1="16" y1="2" x2="16" y2="6"/>
              <line x1="8" y1="2" x2="8" y2="6"/>
              <line x1="3" y1="10" x2="21" y2="10"/>
            </svg>
            ${dateStr} (${session.total} addresses)
          </div>
          <div class="session-pills">
            <span class="session-pill" style="background:#ecfdf5; color:#065f46;">${valid} Valid</span>
            <span class="session-pill" style="background:#fef2f2; color:#991b1b;">${invalid} Invalid</span>
            <span class="session-pill" style="background:#fffbeb; color:#92400e;">${risky} Risky</span>
            <span class="session-pill" style="background:#f1f5f9; color:#475569;">${unknown} Unknown</span>
          </div>
        </div>
        <div class="session-actions">
          <button type="button" class="btn btn-outline btn-xs btn-reopen" data-session-id="${session.id}">
            Reopen Results
          </button>
          <button type="button" class="btn btn-outline btn-xs btn-export-history" data-session-id="${session.id}">
            Export CSV
          </button>
        </div>
      `;

      historyList.appendChild(card);
    });

    // Reopen action
    document.querySelectorAll('.btn-reopen').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.getAttribute('data-session-id');
        const session = loadHistory().find(s => s.id === id);
        if (session) {
          currentResults = session.results || [];
          currentPage = 1;
          expandedRowIndexes.clear();
          renderSummary(session.summary, currentResults);
          renderResults();

          // Switch back to batch verification tab
          tabVerifyEmails.click();
          summarySection.scrollIntoView({ behavior: 'smooth' });
          showToast(`Reopened session from ${new Date(session.timestamp).toLocaleTimeString()}.`, 'info');
        }
      });
    });

    // Export history action
    document.querySelectorAll('.btn-export-history').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.getAttribute('data-session-id');
        const session = loadHistory().find(s => s.id === id);
        if (session && session.results) {
          exportResultsToCsv(session.results, `emailcheck_history_${session.id}`);
        }
      });
    });
  }

  clearHistoryBtn.addEventListener('click', () => {
    localStorage.removeItem(HISTORY_KEY);
    updateHistoryUI();
    showToast('Verification history cleared.', 'info');
  });

  // ==========================================================================
  // Main Navigation Tabs Switching
  // ==========================================================================
  function switchMainTab(activeTabBtn, activeSection) {
    [tabVerifyEmails, tabDomainDiag, tabHistory].forEach(btn => {
      btn.classList.remove('active');
      btn.setAttribute('aria-selected', 'false');
    });
    [sectionVerifyEmails, sectionDomainDiag, sectionHistory].forEach(sec => {
      sec.style.display = 'none';
    });

    activeTabBtn.classList.add('active');
    activeTabBtn.setAttribute('aria-selected', 'true');
    activeSection.style.display = 'block';
  }

  tabVerifyEmails.addEventListener('click', () => switchMainTab(tabVerifyEmails, sectionVerifyEmails));
  tabDomainDiag.addEventListener('click', () => switchMainTab(tabDomainDiag, sectionDomainDiag));
  tabHistory.addEventListener('click', () => {
    switchMainTab(tabHistory, sectionHistory);
    updateHistoryUI();
  });

  // Initialize
  updateInputCounter();
  updateHistoryUI();
});
