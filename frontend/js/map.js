// API_BASE is defined in config.js

let map = null;
let heatLayer = null;
let clusterGroup = null;
let heatVisible = true;
let clustersVisible = true;

function getPriorityColor(tier) {
    return { Critical: '#f43f5e', High: '#f97316', Medium: '#f59e0b', Low: '#10b981' }[tier] || '#3b82f6';
}

function initMap() {
    map = L.map('map', { zoomControl: false, attributionControl: false }).setView([12.9716, 77.5946], 12);

    // Dark Carto tile
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        maxZoom: 19,
        subdomains: 'abcd'
    }).addTo(map);

    L.control.zoom({ position: 'bottomright' }).addTo(map);
    L.control.attribution({ position: 'bottomleft', prefix: '© CartoDB' }).addTo(map);

    clusterGroup = L.layerGroup().addTo(map);
}

async function loadHeatmap() {
    try {
        const r = await fetch(`${API_BASE}/api/heatmap-data`);
        if (!r.ok) return;
        const d = await r.json();
        if (heatLayer) map.removeLayer(heatLayer);
        if (d.points && d.points.length > 0) {
            heatLayer = L.heatLayer(d.points, {
                radius: 22, blur: 18, maxZoom: 16,
                gradient: { 0.1: '#1e3a5f', 0.35: '#1d4ed8', 0.6: '#7c3aed', 0.8: '#db2777', 1: '#f43f5e' }
            }).addTo(map);
            if (!heatVisible) map.removeLayer(heatLayer);
        }
    } catch (e) { console.warn('Heatmap error:', e); }
}

async function loadClusters() {
    try {
        const r = await fetch(`${API_BASE}/api/hotspots`);
        if (!r.ok) return;
        const geo = await r.json();
        clusterGroup.clearLayers();
        if (!geo.features || !geo.features.length) return;

        const bounds = [];
        geo.features.forEach(f => {
            const p = f.properties;
            const [lon, lat] = f.geometry.coordinates;
            const color = getPriorityColor(p.priority_tier);
            const r = Math.min(28, Math.max(7, 7 + Math.sqrt(p.violation_count) * 0.8));

            const circle = L.circleMarker([lat, lon], {
                radius: r, fillColor: color, color: color,
                weight: 1.5, opacity: 0.9, fillOpacity: 0.55
            });

            const score = (p.impact_score || 0).toFixed(1);
            const vc = (p.violation_count || 0).toLocaleString();
            circle.bindPopup(`
                <div style="font-family:Inter,sans-serif;min-width:210px">
                  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
                    <span style="font-weight:700;font-size:0.9rem">Cluster #${p.cluster_id}</span>
                    <span style="background:${color}28;color:${color};padding:2px 9px;border-radius:99px;font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em">${p.priority_tier}</span>
                  </div>
                  <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:10px">
                    <div style="background:rgba(255,255,255,0.05);border-radius:6px;padding:7px 9px">
                      <div style="font-size:0.65rem;color:#64748b;text-transform:uppercase;letter-spacing:.05em">Violations</div>
                      <div style="font-size:1.1rem;font-weight:700;color:${color}">${vc}</div>
                    </div>
                    <div style="background:rgba(255,255,255,0.05);border-radius:6px;padding:7px 9px">
                      <div style="font-size:0.65rem;color:#64748b;text-transform:uppercase;letter-spacing:.05em">Impact</div>
                      <div style="font-size:1.1rem;font-weight:700;color:${color}">${score}</div>
                    </div>
                  </div>
                  <div style="font-size:0.75rem;color:#94a3b8;margin-bottom:4px">📋 ${p.dominant_violation_type || 'N/A'}</div>
                  <div style="font-size:0.75rem;color:#3b82f6">⏱ ${p.recommended_enforcement_time || 'N/A'}</div>
                </div>`, { maxWidth: 260 }
            );

            clusterGroup.addLayer(circle);
            bounds.push([lat, lon]);
        });

        if (bounds.length) map.fitBounds(bounds, { padding: [40, 40] });
        if (!clustersVisible) map.removeLayer(clusterGroup);
    } catch (e) { console.warn('Clusters error:', e); }
}

async function refreshMap() {
    await Promise.all([loadHeatmap(), loadClusters()]);
}

function toggleHeatmap(v) {
    heatVisible = v;
    if (heatLayer) { v ? map.addLayer(heatLayer) : map.removeLayer(heatLayer); }
    document.getElementById('heatmap-toggle-btn').classList.toggle('active', v);
}

function toggleClusters(v) {
    clustersVisible = v;
    v ? map.addLayer(clusterGroup) : map.removeLayer(clusterGroup);
    document.getElementById('clusters-toggle-btn').classList.toggle('active', v);
}
