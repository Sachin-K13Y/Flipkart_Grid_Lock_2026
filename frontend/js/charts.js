// API_BASE is defined in config.js

let charts = { hourly: null, donut: null, trend: null, junctions: null };

const PEAK_HOURS = new Set([7, 8, 9, 17, 18, 19, 20]);
const PALETTE = ['#3b82f6', '#6366f1', '#f97316', '#f43f5e', '#f59e0b', '#10b981', '#06b6d4', '#a855f7', '#ec4899', '#84cc16'];

const GRID_COLOR = 'rgba(255,255,255,0.05)';
const TICK_COLOR = '#475569';

function destroyChart(k) { if (charts[k]) { charts[k].destroy(); charts[k] = null; } }

Chart.defaults.font.family = 'Inter, system-ui, sans-serif';

function renderHourlyChart(data) {
    const canvas = document.getElementById('hourly-chart');
    if (!canvas || !data?.hourly) return;
    destroyChart('hourly');

    const hours = Array.from({ length: 24 }, (_, i) => String(i));
    const counts = hours.map(h => data.hourly[h] || 0);

    const ctx = canvas.getContext('2d');
    const grad = ctx.createLinearGradient(0, 0, 0, 140);
    grad.addColorStop(0, 'rgba(59,130,246,0.9)');
    grad.addColorStop(1, 'rgba(99,102,241,0.6)');

    const peakGrad = ctx.createLinearGradient(0, 0, 0, 140);
    peakGrad.addColorStop(0, 'rgba(249,115,22,0.9)');
    peakGrad.addColorStop(1, 'rgba(244,63,94,0.7)');

    charts.hourly = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: hours,
            datasets: [{
                data: counts,
                backgroundColor: hours.map(h => PEAK_HOURS.has(+h) ? peakGrad : grad),
                borderRadius: 4, borderSkipped: false,
            }]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: {
                legend: { display: false }, tooltip: {
                    backgroundColor: 'rgba(13,17,23,0.95)',
                    titleColor: '#f1f5f9', bodyColor: '#94a3b8',
                    borderColor: 'rgba(255,255,255,0.1)', borderWidth: 1,
                    callbacks: { title: t => `Hour ${t[0].label}:00` }
                }
            },
            scales: {
                y: { beginAtZero: true, grid: { color: GRID_COLOR }, ticks: { color: TICK_COLOR, font: { size: 10 } } },
                x: { grid: { display: false }, ticks: { color: TICK_COLOR, font: { size: 9 }, maxRotation: 0 } }
            }
        }
    });
}

function renderViolationTypeChart(data) {
    const canvas = document.getElementById('violation-type-chart');
    if (!canvas || !data?.violation_types?.length) return;
    destroyChart('donut');

    const top = data.violation_types.slice(0, 6);
    const ctx = canvas.getContext('2d');
    charts.donut = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: top.map(v => v.violation_type),
            datasets: [{
                data: top.map(v => v.count),
                backgroundColor: PALETTE,
                borderWidth: 2, borderColor: '#0d1117',
                hoverOffset: 6
            }]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            cutout: '65%',
            plugins: {
                legend: {
                    position: 'bottom', labels: {
                        color: TICK_COLOR, padding: 10, font: { size: 10 },
                        generateLabels: chart => {
                            const data = chart.data;
                            const total = data.datasets[0].data.reduce((a, b) => a + b, 0);
                            return data.labels.map((l, i) => ({
                                text: `${l} (${Math.round(data.datasets[0].data[i] / total * 100)}%)`,
                                fillStyle: data.datasets[0].backgroundColor[i],
                                hidden: false, index: i
                            }));
                        }
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(13,17,23,0.95)', titleColor: '#f1f5f9', bodyColor: '#94a3b8',
                    borderColor: 'rgba(255,255,255,0.1)', borderWidth: 1
                }
            }
        }
    });
}

function renderWeeklyTrendChart(data) {
    const canvas = document.getElementById('weekly-chart');
    if (!canvas || !data?.weekly_trend?.length) return;
    destroyChart('trend');

    const ctx = canvas.getContext('2d');
    const grad = ctx.createLinearGradient(0, 0, 0, 150);
    grad.addColorStop(0, 'rgba(99,102,241,0.25)');
    grad.addColorStop(1, 'rgba(99,102,241,0)');

    charts.trend = new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.weekly_trend.map(w => `W${w.week}`),
            datasets: [{
                data: data.weekly_trend.map(w => w.count),
                borderColor: '#6366f1', backgroundColor: grad,
                borderWidth: 2, tension: 0.4, fill: true,
                pointRadius: 3, pointBackgroundColor: '#6366f1',
                pointHoverRadius: 5
            }]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: {
                legend: { display: false }, tooltip: {
                    backgroundColor: 'rgba(13,17,23,0.95)', titleColor: '#f1f5f9', bodyColor: '#94a3b8',
                    borderColor: 'rgba(255,255,255,0.1)', borderWidth: 1
                }
            },
            scales: {
                y: { beginAtZero: true, grid: { color: GRID_COLOR }, ticks: { color: TICK_COLOR, font: { size: 10 } } },
                x: { grid: { display: false }, ticks: { color: TICK_COLOR, font: { size: 9 } } }
            }
        }
    });
}

function renderTopJunctionsChart(data) {
    const canvas = document.getElementById('junctions-chart');
    if (!canvas || !data?.top_junctions?.length) return;
    destroyChart('junctions');

    const sorted = [...data.top_junctions].sort((a, b) => b.count - a.count).slice(0, 8);
    const ctx = canvas.getContext('2d');

    charts.junctions = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: sorted.map(j => j.junction_name.length > 22 ? j.junction_name.slice(0, 20) + '…' : j.junction_name),
            datasets: [{
                data: sorted.map(j => j.count),
                backgroundColor: sorted.map((_, i) => `hsl(${210 + i * 12},70%,${55 - i * 2}%)`),
                borderRadius: 4, borderSkipped: false,
            }]
        },
        options: {
            indexAxis: 'y',
            responsive: true, maintainAspectRatio: false,
            plugins: {
                legend: { display: false }, tooltip: {
                    backgroundColor: 'rgba(13,17,23,0.95)', titleColor: '#f1f5f9', bodyColor: '#94a3b8',
                    borderColor: 'rgba(255,255,255,0.1)', borderWidth: 1
                }
            },
            scales: {
                y: { grid: { display: false }, ticks: { color: TICK_COLOR, font: { size: 10 } } },
                x: { beginAtZero: true, grid: { color: GRID_COLOR }, ticks: { color: TICK_COLOR, font: { size: 10 } } }
            }
        }
    });
}

async function refreshAllCharts() {
    try {
        const r = await fetch(`${API_BASE}/api/time-stats`);
        if (!r.ok) return;
        const d = await r.json();
        renderHourlyChart(d);
        renderViolationTypeChart(d);
        renderWeeklyTrendChart(d);
        renderTopJunctionsChart(d);
    } catch (e) { console.warn('Charts error:', e); }
}
