// API_BASE is defined in config.js

function showLoading(msg = 'Processing...') {
    document.querySelector('.loading-overlay')?.classList.add('visible');
    const t = document.querySelector('.loading-text');
    if (t) t.textContent = msg;
}

function hideLoading() {
    document.querySelector('.loading-overlay')?.classList.remove('visible');
}

function showToast(msg, type = 'info') {
    const c = document.querySelector('.toast-container');
    if (!c) return;
    const t = document.createElement('div');
    t.className = `toast ${type}`;
    t.textContent = msg;
    c.appendChild(t);
    setTimeout(() => {
        t.style.transition = 'opacity .3s, transform .3s';
        t.style.opacity = '0'; t.style.transform = 'translateX(110%)';
        setTimeout(() => t.remove(), 300);
    }, 3500);
}

async function loadDashboardStats() {
    try {
        const r = await fetch(`${API_BASE}/api/dashboard`);
        if (!r.ok) return;
        const d = await r.json();
        const el = id => document.getElementById(id);
        if (el('stat-total')) el('stat-total').textContent = (d.total_violations || 0).toLocaleString();
        if (el('stat-clusters')) el('stat-clusters').textContent = (d.active_clusters || 0).toLocaleString();
        if (el('stat-critical')) el('stat-critical').textContent = (d.critical_zones || 0).toLocaleString();
        if (el('stat-resolution')) el('stat-resolution').textContent = `${d.avg_resolution_minutes || 0} min`;
        if (el('last-updated') && d.last_updated) {
            el('last-updated').textContent = 'Updated ' + new Date(d.last_updated).toLocaleTimeString();
        }
    } catch (e) { console.warn('Stats error:', e); }
}

async function handleFileUpload(file) {
    if (!file) return;
    showLoading('Uploading & analyzing 298k records...');
    const fd = new FormData();
    fd.append('file', file);
    try {
        const r = await fetch(`${API_BASE}/api/upload`, { method: 'POST', body: fd });
        const d = await r.json();
        if (!r.ok) { showToast(d.detail || 'Upload failed', 'error'); return; }
        showToast(`✓ ${(d.records_processed || 0).toLocaleString()} records · ${d.clusters_found || 0} clusters`, 'success');
        await Promise.all([loadDashboardStats(), refreshMap(), refreshAllCharts(), loadRecommendations()]);
    } catch (e) {
        showToast(`Upload error: ${e.message}`, 'error');
    } finally { hideLoading(); }
}

function switchTab(name) {
    document.querySelectorAll('.s-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.toggle('active', p.id === `tab-${name}`));
}

function toggleTheme() {
    const dark = !document.body.classList.contains('light-mode');
    document.body.classList.toggle('light-mode', dark);
    const btn = document.getElementById('theme-btn');
    if (btn) btn.textContent = dark ? '☀️' : '🌙';
    localStorage.setItem('parkiq-theme', dark ? 'light' : 'dark');
}

// ── Wake-up banner (shown while Render free-tier cold-starts) ──────────────
function showWakeUpBanner() {
    if (document.getElementById('wakeup-banner')) return;
    const banner = document.createElement('div');
    banner.id = 'wakeup-banner';
    banner.innerHTML = `
        <span>⏳ Backend is waking up on Render free tier — this takes ~30 seconds. Retrying automatically…</span>
        <div id="wakeup-dots" style="display:inline-block;margin-left:6px">
            <span class="dot">.</span><span class="dot">.</span><span class="dot">.</span>
        </div>`;
    Object.assign(banner.style, {
        position: 'fixed', top: '0', left: '0', right: '0', zIndex: '9999',
        background: 'linear-gradient(90deg,#f97316,#f43f5e)',
        color: '#fff', textAlign: 'center', padding: '10px 16px',
        fontSize: '0.82rem', fontWeight: '600', letterSpacing: '0.01em',
        boxShadow: '0 2px 12px rgba(249,115,22,0.4)'
    });
    document.body.prepend(banner);

    // Animate dots
    let i = 0;
    const dots = banner.querySelectorAll('.dot');
    setInterval(() => {
        dots.forEach((d, j) => { d.style.opacity = j === i % 3 ? '1' : '0.2'; });
        i++;
    }, 400);
}

function hideWakeUpBanner() {
    document.getElementById('wakeup-banner')?.remove();
}

// ── Fetch with timeout + auto-retry until backend is alive ─────────────────
let _backendAlive = false;
let _retryTimer = null;

async function waitForBackend() {
    if (_backendAlive) return true;
    try {
        const controller = new AbortController();
        const tid = setTimeout(() => controller.abort(), 8000);
        const r = await fetch(`${API_BASE}/`, { signal: controller.signal });
        clearTimeout(tid);
        if (r.ok) { _backendAlive = true; return true; }
    } catch (_) {}
    return false;
}

async function loadAllData() {
    const alive = await waitForBackend();
    if (!alive) {
        showWakeUpBanner();
        hideLoading();  // Un-block the UI — show the skeleton dashboard
        _retryTimer = setTimeout(async () => {
            const retry = await waitForBackend();
            if (retry) {
                hideWakeUpBanner();
                showToast('✅ Backend is live! Loading data…', 'success');
                showLoading('Loading dashboard data...');
                try {
                    await Promise.all([loadDashboardStats(), refreshAllCharts(), loadRecommendations()]);
                    setTimeout(() => { if (typeof refreshMap === 'function') refreshMap(); }, 200);
                } finally { hideLoading(); }
            } else {
                // Try again after another 10s
                _retryTimer = setTimeout(loadAllData, 10000);
            }
        }, 10000);
        return;
    }

    hideWakeUpBanner();
    try {
        await Promise.all([loadDashboardStats(), refreshAllCharts(), loadRecommendations()]);
        setTimeout(() => { if (typeof refreshMap === 'function') refreshMap(); }, 200);
    } finally { hideLoading(); }
}

document.addEventListener('DOMContentLoaded', async () => {
    // Restore theme
    if (localStorage.getItem('parkiq-theme') === 'light') {
        document.body.classList.add('light-mode');
        const btn = document.getElementById('theme-btn');
        if (btn) btn.textContent = '☀️';
    }

    // File input
    const fi = document.getElementById('csv-file-input');
    if (fi) fi.addEventListener('change', e => {
        if (e.target.files?.[0]) { handleFileUpload(e.target.files[0]); e.target.value = ''; }
    });

    // Upload btn
    const ub = document.querySelector('.upload-btn');
    if (ub && fi) ub.addEventListener('click', () => fi.click());

    // Theme
    document.getElementById('theme-btn')?.addEventListener('click', toggleTheme);

    // Sidebar tabs
    document.querySelectorAll('.s-tab').forEach(t => {
        t.addEventListener('click', () => switchTab(t.dataset.tab));
    });

    // Map layer toggles
    document.getElementById('heatmap-toggle-btn')?.addEventListener('click', function () {
        toggleHeatmap(!this.classList.contains('active'));
    });
    document.getElementById('clusters-toggle-btn')?.addEventListener('click', function () {
        toggleClusters(!this.classList.contains('active'));
    });

    // Drag & drop
    const mp = document.querySelector('.map-panel');
    if (mp) {
        mp.addEventListener('dragover', e => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; });
        mp.addEventListener('drop', e => {
            e.preventDefault();
            const f = e.dataTransfer.files[0];
            if (f?.name.endsWith('.csv')) handleFileUpload(f);
            else if (f) showToast('Please drop a CSV file', 'error');
        });
    }

    // Init AI chat
    if (typeof initAiChat === 'function') initAiChat();

    // Init map
    if (typeof initMap === 'function') initMap();

    // Load data — with cold-start awareness
    showLoading('Connecting to backend...');
    await loadAllData();
});
