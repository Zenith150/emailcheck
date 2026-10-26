/**
 * EmailCheck - Frontend Application Logic (v2.3)
 * Inspired by MailCheck SaaS Architecture & Aesthetics
 *
 * Features:
 * - Theme Switcher (Dark / Light Mode) with system preference detection & localStorage
 * - Live API Health Indicator
 * - Multi-stage animated pipeline progress bar
 * - Intelligent multi-delimiter email parsing (newlines, commas, semicolons, spaces)
 * - Real-time duplicate detection & memoization feedback
 * - Division-by-zero safe summary metrics (Total, Likely to Deliver, Likely to Bounce, Unknown)
 * - Debounced search, multi-factor sorting & pagination
 * - Inspection Modal with multi-stage diagnostics and raw JSON payload viewer
 * - Collapsible per-email diagnostics panel for inline audit
 * - Dedicated Domain Diagnostics inspection tool
 * - Lightweight client-side session history in localStorage
 * - RFC 4180 compliant CSV export retaining complete diagnostic explanation
 */

document.addEventListener('DOMContentLoaded', () => {
  // Theme Toggle Elements
  const themeToggleBtn = document.getElementById('themeToggleBtn');
  const THEME_KEY = 'emailcheck_theme';

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
  const progressText = document.getElementById('progressText');
  const toastContainer = document.getElementById('toastContainer');
  const apiStatusText = document.getElementById('apiStatusText');

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

  // Inspection Modal Elements
  const inspectModal = document.getElementById('inspectModal');
  const modalEmailTitle = document.getElementById('modalEmailTitle');
  const inspectModalBody = document.getElementById('inspectModalBody');
  const modalStatusBadge = document.getElementById('modalStatusBadge');
  const closeInspectModalBtn = document.getElementById('closeInspectModalBtn');
  const modalDismissBtn = document.getElementById('modalDismissBtn');

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
  let progressAnimationInterval = null;

  // ==========================================================================
  // Theme Switcher (Dark / Light Mode)
  // ==========================================================================
  function initTheme() {
    const savedTheme = localStorage.getItem(THEME_KEY);
    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    const initialTheme = savedTheme || (prefersDark ? 'dark' : 'light');
    applyTheme(initialTheme);
  }

  function applyTheme(theme) {
    if (theme === 'dark') {
      document.body.classList.remove('theme-light');
      document.body.classList.add('theme-dark');
      document.documentElement.classList.add('dark');
      localStorage.setItem(THEME_KEY, 'dark');
    } else {
      document.body.classList.remove('theme-dark');
      document.body.classList.add('theme-light');
      document.documentElement.classList.remove('dark');
      localStorage.setItem(THEME_KEY, 'light');
    }
  }

  if (themeToggleBtn) {
    themeToggleBtn.addEventListener('click', () => {
      const isDark = document.body.classList.contains('theme-dark');
      applyTheme(isDark ? 'light' : 'dark');
      showToast(`Switched to ${isDark ? 'light' : 'dark'} mode.`, 'info');
    });
  }

  initTheme();

  // ==========================================================================
  // Helper: Escape HTML to prevent XSS
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
    if (!toastContainer) return;
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
  // Multi-Delimiter Input Parser with Duplicate Counting
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
      lineCountBadge.style.color = 'var(--bounce-accent)';
      lineCountBadge.style.borderColor = 'var(--bounce-border)';
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
  // Sample Email Loader (Diverse Test Cases: Bounce, Unknown, Memoization)
  // ==========================================================================
  loadSampleBtn.addEventListener('click', () => {
    const samples = [
      'support@github.com',
      'contact@google.com',
      'test.user@mailinator.com',
      'service@example.org',
      'bad..syntax@@domain',
      'user@nonexistent-domain-xyz987654321.org',
      'support@github.com' // Duplicate to demonstrate memoization
    ];
    emailsInput.value = samples.join('\n');
    updateInputCounter();
    showToast('Loaded diverse sample addresses demonstrating bounce, unknown, and memoization.', 'info');
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
    showToast('Verification input and results cleared.', 'info');
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

    const smtpToggle = document.getElementById('smtpProbeToggle');
    const performSmtp = smtpToggle ? smtpToggle.checked : false;

    setLoadingState(true);

    try {
      const response = await fetch('/api/verify', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          emails: emails,
          check_smtp: performSmtp,
          smtp_check: performSmtp
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

      showToast(`Successfully verified ${data.total} addresses via ${data.provider || 'local engine'}.`, 'success');
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

      // Cycle animated progress stages
      const stages = [
        'Stage 1/3: Validating syntax via RFC specs...',
        'Stage 2/3: Querying DNS MX & routing records...',
        'Stage 3/3: Evaluating mailbox existence & classifications...'
      ];
      let currentStageIdx = 0;
      progressText.textContent = stages[0];

      clearInterval(progressAnimationInterval);
      progressAnimationInterval = setInterval(() => {
        currentStageIdx = (currentStageIdx + 1) % stages.length;
        progressText.textContent = stages[currentStageIdx];
      }, 700);

    } else {
      clearInterval(progressAnimationInterval);
      btnSpinner.style.display = 'none';
      btnIcon.style.display = 'inline-block';
      btnText.textContent = 'Verify Emails';
      progressContainer.style.display = 'none';
    }
  }

  // ==========================================================================
  // Render Summary Cards (Division-by-Zero Protected)
  // ==========================================================================
  function renderSummary(summary, results = []) {
    if (!summary) return;

    emptyState.style.display = 'none';
    summarySection.style.display = 'grid';
    resultsSection.style.display = 'block';

    const total = Number(summary.total) || 0;
    const valid = summary.likely_to_deliver !== undefined ? Number(summary.likely_to_deliver) : Number(summary.valid || 0);
    const invalid = summary.likely_to_bounce !== undefined ? Number(summary.likely_to_bounce) : Number(summary.invalid || 0);
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
      } else if (filter === 'valid' || filter === 'likely to be delivered' || filter === 'likely to deliver') {
        matchesFilter = (cls === 'valid' || cls === 'likely to be delivered' || cat === 'valid' || cat === 'likely_to_deliver');
      } else if (filter === 'invalid' || filter === 'likely to bounce') {
        matchesFilter = (cls === 'invalid' || cls === 'likely to bounce' || cat === 'invalid' || cat === 'likely_to_bounce');
      } else if (filter === 'risky') {
        matchesFilter = (cls === 'risky' || cat === 'risky');
      } else if (filter === 'unknown') {
        matchesFilter = (cls === 'unknown' || cat === 'unknown');
      }

      const q = currentSearch.toLowerCase();
      const matchesSearch = !q ||
        (item.email && item.email.toLowerCase().includes(q)) ||
        (item.domain && item.domain.toLowerCase().includes(q)) ||
        (item.reason && item.reason.toLowerCase().includes(q)) ||
        (item.short_reason && item.short_reason.toLowerCase().includes(q));

      return matchesFilter && matchesSearch;
    });

    // 2. Sort
    if (currentSort === 'email-asc') {
      filtered.sort((a, b) => (a.email || '').localeCompare(b.email || ''));
    } else if (currentSort === 'email-desc') {
      filtered.sort((a, b) => (b.email || '').localeCompare(a.email || ''));
    } else if (currentSort === 'class-valid') {
      const order = { 'valid': 1, 'likely to be delivered': 1, 'risky': 2, 'unknown': 3, 'invalid': 4, 'likely to bounce': 4 };
      filtered.sort((a, b) => (order[(a.status_category || '').toLowerCase()] || order[(a.classification || '').toLowerCase()] || 99) - (order[(b.status_category || '').toLowerCase()] || order[(b.classification || '').toLowerCase()] || 99));
    } else if (currentSort === 'class-invalid') {
      const order = { 'invalid': 1, 'likely to bounce': 1, 'risky': 2, 'unknown': 3, 'valid': 4, 'likely to be delivered': 4 };
      filtered.sort((a, b) => (order[(a.status_category || '').toLowerCase()] || order[(a.classification || '').toLowerCase()] || 99) - (order[(b.status_category || '').toLowerCase()] || order[(b.classification || '').toLowerCase()] || 99));
    }

    return filtered;
  }

  // ==========================================================================
  // Render Results Table & Diagnostics
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

      // Classification Badge & Icon
      let badgeClass = 'badge-unknown';
      let badgeIcon = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`;

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
        ? `<span class="indicator-pill pill-pass" title="RFC format validated">PASS (RFC Valid)</span>`
        : `<span class="indicator-pill pill-fail" title="RFC syntax malformed">FAIL (Invalid)</span>`;

      // Domain/MX Pill
      let mxPill = `<span class="indicator-pill pill-untested">—</span>`;
      if (item.domain_status === 'nonexistent') {
        mxPill = `<span class="indicator-pill pill-fail" title="Domain does not exist in DNS (NXDOMAIN)">FAIL (NXDOMAIN)</span>`;
      } else if (item.is_null_mx || item.mx_status === 'null_mx') {
        mxPill = `<span class="indicator-pill pill-fail" title="RFC 7505 Null MX: Explicitly rejects email">Null MX (0 .)</span>`;
      } else if (item.mx_status === 'mx_found') {
        const mxPrimary = item.primary_mx || (item.mx_records && item.mx_records[0] ? item.mx_records[0].split(' ')[0] : 'MX Active');
        mxPill = `<span class="indicator-pill pill-pass" title="${escapeHtml(item.mx_records ? item.mx_records.join(', ') : '')}">PASS (${escapeHtml(mxPrimary)})</span>`;
      } else if (item.mx_status === 'implicit_mx_found') {
        mxPill = `<span class="indicator-pill pill-pass" title="Implicit MX via A/AAAA record">Implicit MX</span>`;
      } else if (item.mx_status === 'no_records') {
        mxPill = `<span class="indicator-pill pill-fail" title="No MX or A records found">FAIL (No Route)</span>`;
      } else if (item.mx_status === 'dns_timeout' || item.domain_status === 'dns_timeout') {
        mxPill = `<span class="indicator-pill pill-untested" title="DNS lookup timed out">UNKNOWN (Timeout)</span>`;
      }

      // Disposable Pill
      let disposablePill = `<span class="indicator-pill pill-pass">Clean</span>`;
      if (item.is_disposable) {
        disposablePill = `<span class="indicator-pill pill-warning" title="Known temporary or disposable email service">⚠ Disposable</span>`;
      } else if (!item.syntax_valid) {
        disposablePill = `<span class="indicator-pill pill-untested">—</span>`;
      }

      // SMTP Probe Pill
      let smtpPill = `<span class="indicator-pill pill-disabled">— Disabled</span>`;
      const smtpProbe = item.smtp_probe || {};
      const smtpSt = (smtpProbe.smtp_status || item.smtp_status || 'disabled').toLowerCase();
      const smtpCode = smtpProbe.smtp_response_code;
      const smtpExp = smtpProbe.smtp_explanation || '';

      if (smtpSt === 'accepted' || smtpSt === 'mailbox_accepted') {
        smtpPill = `<span class="indicator-pill pill-accepted" title="${escapeHtml(smtpExp)}">✓ Accepted (${smtpCode || 250})</span>`;
      } else if (smtpSt === 'rejected' || smtpSt === 'mailbox_rejected') {
        smtpPill = `<span class="indicator-pill pill-rejected" title="${escapeHtml(smtpExp)}">✗ Rejected (${smtpCode || 550})</span>`;
      } else if (smtpSt === 'inconclusive') {
        smtpPill = `<span class="indicator-pill pill-inconclusive" title="${escapeHtml(smtpExp)}">⚠ Inconclusive${smtpCode ? ' (' + smtpCode + ')' : ''}</span>`;
      } else if (smtpSt === 'unavailable') {
        smtpPill = `<span class="indicator-pill pill-unavailable" title="${escapeHtml(smtpExp)}">⊘ Unavailable</span>`;
      } else if (smtpSt === 'disabled') {
        smtpPill = `<span class="indicator-pill pill-disabled" title="${escapeHtml(smtpExp)}">— Disabled</span>`;
      } else if (smtpSt === 'skipped') {
        smtpPill = `<span class="indicator-pill pill-disabled" title="${escapeHtml(smtpExp)}">— Skipped</span>`;
      }

      // Shortened explanation for the main table per requirements
      let displayReason = item.short_reason;
      if (!displayReason) {
        if ((cls === 'unknown' || cat === 'unknown') && (item.mx_status === 'mx_found' || item.mx_status === 'implicit_mx_found') && !item.is_disposable) {
          displayReason = 'MX records found; mailbox status could not be confirmed.';
        } else {
          displayReason = item.reason;
        }
      }

      // Tooltip explaining why the result is Unknown
      let unknownTooltip = '';
      if (cls === 'unknown' || cat === 'unknown') {
        if ((item.mx_status === 'mx_found' || item.mx_status === 'implicit_mx_found') && !item.is_disposable) {
          unknownTooltip = 'Why Unknown: Domain mail routing (MX) is valid, but specific recipient mailbox existence could not be confirmed without direct outbound SMTP access (port 25 is restricted on Render) or a verification provider API key.';
        } else if (item.is_disposable) {
          unknownTooltip = 'Why Unknown: Domain belongs to a known temporary/disposable email service (e.g., mailinator.com). Deliverability is Unknown as disposable inboxes are short-lived or public.';
        } else if (item.domain_status === 'dns_timeout' || item.mx_status === 'dns_timeout') {
          unknownTooltip = 'Why Unknown: DNS lookup timed out or failed. Domain deliverability could not be evaluated.';
        } else {
          unknownTooltip = `Why Unknown: ${item.reason}`;
        }
        if (smtpProbe && smtpProbe.smtp_explanation && !unknownTooltip.includes(smtpProbe.smtp_explanation)) {
          unknownTooltip += ` (SMTP: ${smtpProbe.smtp_explanation})`;
        }
      }

      // Main Table Row
      const row = document.createElement('tr');
      row.className = `result-row ${isExpanded ? 'row-expanded' : ''}`;
      row.innerHTML = `
        <td style="color: var(--text-muted); font-size: 0.75rem;">${globalIndex + 1}</td>
        <td>
          <span class="status-badge ${badgeClass}" ${unknownTooltip ? `title="${escapeHtml(unknownTooltip)}"` : ''}>
            ${badgeIcon}
            ${escapeHtml(item.classification)}
          </span>
        </td>
        <td class="email-cell"><strong>${escapeHtml(item.email)}</strong></td>
        <td>${syntaxPill}</td>
        <td>${mxPill}</td>
        <td>${disposablePill}</td>
        <td>${smtpPill}</td>
        <td class="reason-cell" ${unknownTooltip ? `title="${escapeHtml(unknownTooltip)}"` : ''}>
          ${escapeHtml(displayReason)}
          ${unknownTooltip ? `<span class="tooltip-unknown-icon" title="${escapeHtml(unknownTooltip)}" style="cursor:help; margin-left:0.35rem; color:var(--text-muted); font-size:0.8rem;" aria-label="${escapeHtml(unknownTooltip)}">ⓘ</span>` : ''}
        </td>
        <td style="text-align: center; white-space: nowrap;">
          <button type="button" class="btn-inspect" data-index="${globalIndex}" title="Inspect full multi-stage diagnostics and raw JSON payload">
            Inspect
          </button>
          <button type="button" class="btn-details-toggle" data-email="${escapeHtml(item.email)}" aria-expanded="${isExpanded}" title="Toggle inline diagnostics panel">
            ${isExpanded ? '▲' : '▼'}
          </button>
        </td>
      `;

      resultsTableBody.appendChild(row);

      // Collapsible Inline Diagnostics Row
      if (isExpanded) {
        const detailsRow = document.createElement('tr');
        detailsRow.className = 'details-row';

        const mxRecordsList = (item.mx_records && item.mx_records.length > 0)
          ? item.mx_records.map(r => `<code>${escapeHtml(r)}</code>`).join('<br/>')
          : '<span class="text-muted">None discovered</span>';

        const nullMxText = item.is_null_mx
          ? '<span style="color: var(--bounce-accent); font-weight:700;">RFC 7505 Null MX (Rejects Email)</span>'
          : '<span style="color: var(--delivered-dark);">Clean (No Null MX record)</span>';

        const durationText = item.duration_ms !== undefined ? `${item.duration_ms} ms` : 'N/A';
        const providerName = (item.provider_info && item.provider_info.provider) ? item.provider_info.provider : 'Local Engine';
        const providerReason = (item.provider_info && item.provider_info.reason) ? item.provider_info.reason : '';

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
                  <span class="detail-label">Configured Mail Servers (MX)</span>
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
                  <span class="detail-label">SMTP Probe Handshake</span>
                  <span class="detail-value">
                    <strong>${escapeHtml(smtpSt.toUpperCase())}</strong>
                    ${smtpCode ? ' (Code ' + escapeHtml(smtpCode) + ')' : ''}
                    ${smtpProbe.smtp_server ? ' via <code>' + escapeHtml(smtpProbe.smtp_server) + '</code>' : ''}
                  </span>
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
                <strong>Complete Diagnostic Explanation:</strong> ${escapeHtml(item.reason)}
                ${smtpExp ? `<br/><strong style="margin-top:0.35rem; display:inline-block;">SMTP Probe Handshake Details:</strong> ${escapeHtml(smtpExp)}` : ''}
                ${providerReason ? `<br/><strong style="margin-top:0.35rem; display:inline-block;">Provider Verification Details:</strong> ${escapeHtml(providerReason)}` : ''}
              </div>
            </div>
          </td>
        `;
        resultsTableBody.appendChild(detailsRow);
      }
    });

    // Attach Toggle Listeners for Inline Details
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

    // Attach Modal "Inspect" Listeners
    document.querySelectorAll('.btn-inspect').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const idx = parseInt(btn.getAttribute('data-index'), 10);
        const item = items[idx];
        if (item) {
          openInspectModal(item);
        }
      });
    });
  }

  // ==========================================================================
  // Inspection Modal (Inspired by MailCheck "Inspect" Dialog)
  // ==========================================================================
  function openInspectModal(item) {
    if (!inspectModal) return;

    modalEmailTitle.textContent = item.email;
    modalStatusBadge.textContent = item.classification;
    modalStatusBadge.className = `status-badge ${
      item.classification.toLowerCase().includes('deliver') ? 'badge-delivered' :
      item.classification.toLowerCase().includes('bounce') ? 'badge-bounce' : 'badge-unknown'
    }`;

    const parts = (item.email || '').split('@');
    const localPart = parts[0] || '';
    const domainPart = parts[1] || '';

    const probe = item.smtp_probe || {};
    const smtpSt = (probe.smtp_status || item.smtp_status || 'disabled').toUpperCase();
    const smtpExp = probe.smtp_explanation || item.reason || '';

    const mxListHtml = (item.mx_records && item.mx_records.length > 0)
      ? item.mx_records.map(r => `<div class="mx-pill-item">${escapeHtml(r)}</div>`).join('')
      : '<span class="text-muted" style="font-size:0.75rem;">None published</span>';

    inspectModalBody.innerHTML = `
      <!-- Primary Classification Evidence -->
      <div class="modal-stage-card">
        <div class="stage-card-title">
          <span>Primary Classification Evidence</span>
          <span class="status-badge ${modalStatusBadge.className}">${escapeHtml(item.classification)}</span>
        </div>
        <p style="font-size:0.8125rem; color:var(--text-secondary); line-height:1.5;">
          ${escapeHtml(item.reason)}
        </p>
      </div>

      <!-- Stage 1: RFC Format & Syntax -->
      <div class="modal-stage-card">
        <div class="stage-card-title">
          <span>Stage 1: RFC Format &amp; Syntax</span>
          <span class="indicator-pill ${item.syntax_valid ? 'pill-pass' : 'pill-fail'}">
            ${item.syntax_valid ? 'PASS (RFC Valid)' : 'FAIL (Invalid)'}
          </span>
        </div>
        <div class="modal-meta-row">
          <span class="modal-meta-label">Local Part:</span>
          <span class="modal-meta-val"><code>${escapeHtml(localPart)}</code></span>
        </div>
        <div class="modal-meta-row">
          <span class="modal-meta-label">Domain Part:</span>
          <span class="modal-meta-val"><code>${escapeHtml(domainPart)}</code></span>
        </div>
        <div class="modal-meta-row">
          <span class="modal-meta-label">Disposable Check:</span>
          <span class="modal-meta-val">${item.is_disposable ? '⚠ Disposable Service' : '✓ Clean (Legitimate Domain)'}</span>
        </div>
      </div>

      <!-- Stage 2: DNS MX Mail Routing -->
      <div class="modal-stage-card">
        <div class="stage-card-title">
          <span>Stage 2: DNS MX Mail Routing</span>
          <span class="indicator-pill ${item.mx_status === 'mx_found' ? 'pill-pass' : (item.mx_status === 'implicit_mx_found' ? 'pill-pass' : 'pill-fail')}">
            ${escapeHtml(item.mx_status || 'untested')}
          </span>
        </div>
        <div class="modal-meta-row">
          <span class="modal-meta-label">RFC 7505 Null MX:</span>
          <span class="modal-meta-val">${item.is_null_mx ? '<strong style="color:var(--bounce-accent);">Detected (Rejects all mail)</strong>' : 'Clean'}</span>
        </div>
        <div style="margin-top:0.45rem;">
          <span class="modal-meta-label" style="font-size:0.75rem; font-weight:700; text-transform:uppercase;">Configured Mail Exchanges (Priority Sorted):</span>
          <div class="mx-pill-list">
            ${mxListHtml}
          </div>
        </div>
      </div>

      <!-- Stage 3: SMTP Mailbox Probe -->
      <div class="modal-stage-card">
        <div class="stage-card-title">
          <span>Stage 3: SMTP Mailbox Probe</span>
          <span class="indicator-pill ${probe.smtp_status === 'accepted' ? 'pill-accepted' : (probe.smtp_status === 'rejected' ? 'pill-rejected' : 'pill-disabled')}">
            ${escapeHtml(smtpSt)}
          </span>
        </div>
        <div class="modal-meta-row">
          <span class="modal-meta-label">Attempted:</span>
          <span class="modal-meta-val">${probe.smtp_attempted ? 'Yes' : 'No (Skipped/Disabled)'}</span>
        </div>
        <div class="modal-meta-row">
          <span class="modal-meta-label">Response Code:</span>
          <span class="modal-meta-val">${probe.smtp_response_code ? escapeHtml(probe.smtp_response_code) : 'None'}</span>
        </div>
        <div class="modal-meta-row">
          <span class="modal-meta-label">Probed Mail Server:</span>
          <span class="modal-meta-val"><code>${probe.smtp_server ? escapeHtml(probe.smtp_server) : 'None'}</code></span>
        </div>
        ${smtpExp ? `
          <div style="margin-top:0.45rem; font-size:0.75rem; color:var(--text-muted);">
            <strong>Explanation:</strong> ${escapeHtml(smtpExp)}
          </div>
        ` : ''}
      </div>

      <!-- Understanding SMTP Timeouts & Provider Protections -->
      <div class="modal-callout-note">
        <strong>Understanding SMTP Timeouts &amp; Provider Protections:</strong>
        <p style="margin-top:0.25rem;">
          An SMTP timeout is never treated as proof that a mailbox is invalid. Cloud hosting environments (like Render) restrict outbound TCP port 25 to prevent spam abuse. When port 25 is blocked or inconclusive, EmailCheck honestly classifies uncertain addresses as <strong>Unknown</strong>.
        </p>
      </div>

      <!-- Raw JSON Payload Viewer -->
      <div>
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.35rem;">
          <span style="font-size:0.6875rem; font-weight:700; text-transform:uppercase; letter-spacing:0.04em; color:var(--text-muted);">Raw Diagnostic Payload JSON:</span>
          <button type="button" id="copyJsonBtn" class="btn btn-outline btn-xs" style="padding:0.15rem 0.5rem; font-size:0.6875rem;">Copy JSON</button>
        </div>
        <pre class="raw-json-box"><code>${escapeHtml(JSON.stringify(item, null, 2))}</code></pre>
      </div>
    `;

    // Attach Copy JSON action
    const copyJsonBtn = document.getElementById('copyJsonBtn');
    if (copyJsonBtn) {
      copyJsonBtn.addEventListener('click', () => {
        navigator.clipboard.writeText(JSON.stringify(item, null, 2)).then(() => {
          copyJsonBtn.textContent = 'Copied!';
          setTimeout(() => copyJsonBtn.textContent = 'Copy JSON', 2000);
          showToast('Diagnostic payload JSON copied to clipboard.', 'info');
        }).catch(() => {
          showToast('Failed to copy JSON.', 'error');
        });
      });
    }

    inspectModal.style.display = 'flex';
    document.body.style.overflow = 'hidden';
  }

  function closeInspectModal() {
    if (!inspectModal) return;
    inspectModal.style.display = 'none';
    document.body.style.overflow = '';
  }

  if (closeInspectModalBtn) closeInspectModalBtn.addEventListener('click', closeInspectModal);
  if (modalDismissBtn) modalDismissBtn.addEventListener('click', closeInspectModal);

  // Close modal when clicking outside modal card
  if (inspectModal) {
    inspectModal.addEventListener('click', (e) => {
      if (e.target === inspectModal) {
        closeInspectModal();
      }
    });
  }

  // Close modal on Escape key
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && inspectModal && inspectModal.style.display === 'flex') {
      closeInspectModal();
    }
  });

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
  // RFC 4180 CSV Export (Retaining Complete Diagnostic Explanation)
  // ==========================================================================
  downloadCsvBtn.addEventListener('click', () => {
    if (!currentResults || currentResults.length === 0) {
      showToast('No results available to download.', 'error');
      return;
    }
    exportResultsToCsv(currentResults, 'emailcheck_export');
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
      'SMTP Status',
      'SMTP Attempted',
      'SMTP Response Code',
      'SMTP Server',
      'SMTP Duration (ms)',
      'SMTP Explanation',
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

    const rows = results.map(item => {
      const probe = item.smtp_probe || {};
      return [
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
        escapeCsvValue(probe.smtp_status || item.smtp_status || 'disabled'),
        escapeCsvValue(probe.smtp_attempted ? 'true' : 'false'),
        escapeCsvValue(probe.smtp_response_code !== null && probe.smtp_response_code !== undefined ? probe.smtp_response_code : ''),
        escapeCsvValue(probe.smtp_server || ''),
        escapeCsvValue(probe.smtp_duration_ms !== undefined ? probe.smtp_duration_ms : ''),
        escapeCsvValue(probe.smtp_explanation || ''),
        escapeCsvValue(item.recipient_status),
        escapeCsvValue(item.provider_info ? item.provider_info.provider : 'Local Engine'),
        escapeCsvValue(item.duration_ms !== undefined ? item.duration_ms : ''),
        escapeCsvValue(item.checked_at || new Date().toISOString()),
        escapeCsvValue(item.reason) // Retains complete diagnostic explanation
      ].join(',');
    });

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
      ? `<ul class="domain-records-list" style="margin-top:0.4rem; padding-left:1.25rem;">${data.mx_records.map(r => `<li><code>${escapeHtml(r)}</code></li>`).join('')}</ul>`
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
          <span class="detail-value">${data.is_null_mx ? '<strong style="color:var(--bounce-accent);">Detected (Rejects all mail)</strong>' : 'Clean (Not published)'}</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Disposable Service</span>
          <span class="detail-value">${data.is_disposable ? '<strong style="color:var(--unknown-amber-accent);">⚠ Yes (Temporary domain)</strong>' : 'Clean (Legitimate domain)'}</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Query Duration</span>
          <span class="detail-value">${data.duration_ms || 0} ms</span>
        </div>
      </div>

      <div class="domain-records-box" style="margin-top:0.85rem; padding-top:0.65rem; border-top:1px solid var(--border-color);">
        <strong style="font-size:0.8125rem; color:var(--text-primary);">Configured Mail Exchangers:</strong>
        ${mxRecordsHtml}
      </div>

      <div class="domain-disclaimer-notice" style="margin-top:0.85rem; font-size:0.75rem; color:var(--text-muted); display:flex; gap:0.4rem; align-items:center;">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0;">
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
      const valid = summary.likely_to_deliver !== undefined ? summary.likely_to_deliver : (summary.valid || 0);
      const invalid = summary.likely_to_bounce !== undefined ? summary.likely_to_bounce : (summary.invalid || 0);
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
            <span class="session-pill" style="background:var(--delivered-bg); color:var(--delivered-dark); border:1px solid var(--delivered-border);">${valid} Likely to Deliver</span>
            <span class="session-pill" style="background:var(--bounce-bg); color:var(--bounce-dark); border:1px solid var(--bounce-border);">${invalid} Likely to Bounce</span>
            <span class="session-pill" style="background:var(--unknown-bg); color:var(--unknown-text); border:1px solid var(--unknown-border);">${unknown} Unknown</span>
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

  // ==========================================================================
  // Live API Health Check Probe
  // ==========================================================================
  async function checkApiHealth() {
    try {
      const resp = await fetch('/health');
      if (resp.ok) {
        const data = await resp.json();
        if (apiStatusText) {
          apiStatusText.textContent = data.status === 'healthy' ? 'Online' : 'Degraded';
        }
      }
    } catch {
      if (apiStatusText) apiStatusText.textContent = 'Offline';
    }
  }

  // Initialize
  updateInputCounter();
  updateHistoryUI();
  checkApiHealth();
});
