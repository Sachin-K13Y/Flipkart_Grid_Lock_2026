// API_BASE is defined in config.js

function renderRecommendationCard(rec) {
    const tier = rec.priority_tier || 'Low';
    const tl = tier.toLowerCase();
    const color = { Critical: '#f43f5e', High: '#f97316', Medium: '#f59e0b', Low: '#10b981' }[tier] || '#10b981';
    const junctions = Array.isArray(rec.junctions_covered) ? rec.junctions_covered.slice(0, 2).join(', ') : '';
    const score = (rec.impact_score || 0).toFixed(1);
    const mockNote = rec.mock ? '<span class="rec-tag" style="color:#f59e0b;border-color:rgba(245,158,11,0.3)">⚠ demo</span>' : '';

    return `<div class="rec-card ${tl}">
      <div class="rec-header">
        <div class="rec-badges">
          <span class="badge badge-id">#${rec.cluster_id}</span>
          <span class="badge badge-${tl}">${tier}</span>
          ${mockNote}
        </div>
        <span class="rec-score" style="color:${color}">${score}</span>
      </div>
      <p class="rec-desc">${rec.description || 'No description available.'}</p>
      <div class="rec-meta">
        <span class="rec-tag">⏱ ${rec.patrol_time_window || rec.recommended_enforcement_time || 'N/A'}</span>
        <span class="rec-tag">🚔 ${rec.enforcement_action || 'N/A'}</span>
        <span class="rec-tag">📉 ${rec.estimated_congestion_reduction || 'N/A'}</span>
        ${junctions ? `<span class="rec-tag">📍 ${junctions}</span>` : ''}
      </div>
    </div>`;
}

async function loadRecommendations() {
    try {
        const r = await fetch(`${API_BASE}/api/recommendations`);
        if (!r.ok) return;
        const d = await r.json();
        const container = document.getElementById('recommendations-container');
        if (!container) return;
        if (!d.recommendations?.length) {
            container.innerHTML = '<div class="empty-state"><h3>No recommendations yet</h3></div>';
            return;
        }
        container.innerHTML = d.recommendations.map(rec => renderRecommendationCard(rec)).join('');
    } catch (e) { console.warn('Recommendations error:', e); }
}

async function askQuestion(q) {
    if (!q?.trim()) return;
    const responseDiv = document.getElementById('ai-response');
    const btn = document.getElementById('ask-btn');
    if (!responseDiv) return;

    responseDiv.classList.add('visible');
    responseDiv.innerHTML = '<span style="color:#475569">Analyzing data...</span>';
    if (btn) btn.disabled = true;

    try {
        const r = await fetch(`${API_BASE}/api/ask`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question: q })
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        const mockNote = d.mock ? '<div style="margin-top:8px;font-size:0.7rem;color:#f59e0b;opacity:.8">⚠ AI key not configured</div>' : '';
        responseDiv.innerHTML = `<div>${d.answer || 'No response.'}</div>${mockNote}`;
    } catch (e) {
        responseDiv.innerHTML = `<span style="color:#f43f5e">Error: ${e.message}</span>`;
    } finally {
        if (btn) btn.disabled = false;
    }
}

function initAiChat() {
    const btn = document.getElementById('ask-btn');
    const input = document.getElementById('ai-question');
    if (btn) btn.addEventListener('click', () => askQuestion(input?.value?.trim()));
    if (input) input.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); askQuestion(input.value.trim()); }
    });
}
