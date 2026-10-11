// ==========================================================================
// Charts Module - Interactive Chart.js with Resilient Native HTML/SVG Fallback
// Guarantees 100% Visual Functionality Offline and Online
// ==========================================================================

const colorPalettes = {
    primary: [
        'rgba(99, 102, 241, 0.85)',
        'rgba(6, 182, 212, 0.85)',
        'rgba(16, 185, 129, 0.85)',
        'rgba(245, 158, 11, 0.85)',
        'rgba(244, 63, 94, 0.85)'
    ],
    primaryBorder: [
        '#6366f1',
        '#06b6d4',
        '#10b981',
        '#f59e0b',
        '#f43f5e'
    ]
};

const chartInstances = {};

function destroyChart(canvasId) {
    if (chartInstances[canvasId]) {
        try {
            chartInstances[canvasId].destroy();
        } catch {}
        delete chartInstances[canvasId];
    }
}

// Render Native SVG/HTML Bar Chart Fallback (Guaranteed to work offline)
function renderNativeTokenSavingChart(container) {
    if (!container) return;
    const items = [
        { name: 'Baseline (HF PyTorch)', val: '1.0x', pct: 2, color: '#64748b' },
        { name: '+ PagedAttention', val: '14.0x', pct: 20, color: '#6366f1' },
        { name: '+ INT8 KV Cache', val: '22.0x', pct: 32, color: '#818cf8' },
        { name: '+ FlashAttention-3', val: '32.0x', pct: 48, color: '#06b6d4' },
        { name: '+ Speculative Decoding', val: '50.0x', pct: 72, color: '#a855f7' },
        { name: '+ LLMLingua-2 Compression', val: '72.0x', pct: 100, color: '#10b981' }
    ];
    
    container.innerHTML = `
        <div class="svg-bar-chart" aria-label="Token saving throughput comparison">
            ${items.map(i => `
                <div class="bar-row">
                    <span class="bar-label" title="${i.name}">${i.name}</span>
                    <div class="bar-track">
                        <div class="bar-fill" style="width: ${i.pct}%; background: ${i.color};"></div>
                    </div>
                    <span class="bar-val">${i.val}</span>
                </div>
            `).join('')}
        </div>
    `;
}

function renderNativeRAGChart(container) {
    if (!container) return;
    const items = [
        { name: 'Simple Factual QA', val: '92%', pct: 92, color: '#10b981' },
        { name: 'Multi-Hop Reasoning', val: '86%', pct: 86, color: '#06b6d4' },
        { name: 'Thematic Cross-Doc Synthesis', val: '82%', pct: 82, color: '#6366f1' },
        { name: 'Temporal Entity Resolution', val: '88%', pct: 88, color: '#f59e0b' }
    ];
    
    container.innerHTML = `
        <div class="svg-bar-chart" aria-label="RAG method quality comparison">
            ${items.map(i => `
                <div class="bar-row">
                    <span class="bar-label" title="${i.name}">${i.name}</span>
                    <div class="bar-track">
                        <div class="bar-fill emerald" style="width: ${i.pct}%; background: ${i.color};"></div>
                    </div>
                    <span class="bar-val">${i.val}</span>
                </div>
            `).join('')}
        </div>
    `;
}

// Chart.js Implementations (When Library is available)
function renderChartJSTokenSaving() {
    const canvas = document.getElementById('token-saving-chart');
    if (!canvas) return;
    destroyChart('token-saving-chart');
    
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    
    const methods = [
        { label: 'Baseline', mem: 1, speed: 1 },
        { label: 'PagedAttn', mem: 4, speed: 14 },
        { label: 'INT8 KV', mem: 8, speed: 22 },
        { label: 'FlashAttn-3', mem: 8, speed: 32 },
        { label: 'Speculative', mem: 8, speed: 50 },
        { label: 'LLMLingua-2', mem: 16, speed: 72 }
    ];
    
    chartInstances['token-saving-chart'] = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: methods.map(m => m.label),
            datasets: [
                {
                    label: 'Memory Reduction (x)',
                    data: methods.map(m => m.mem),
                    backgroundColor: 'rgba(99, 102, 241, 0.75)',
                    borderColor: '#6366f1',
                    borderWidth: 1,
                    borderRadius: 6
                },
                {
                    label: 'Throughput Multiplier (x)',
                    data: methods.map(m => m.speed),
                    backgroundColor: 'rgba(6, 182, 212, 0.75)',
                    borderColor: '#06b6d4',
                    borderWidth: 1,
                    borderRadius: 6
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: '#94a3b8', font: { family: 'Inter' } } }
            },
            scales: {
                x: { ticks: { color: '#94a3b8', font: { family: 'Inter', size: 11 } }, grid: { display: false } },
                y: { ticks: { color: '#94a3b8', font: { family: 'Inter', size: 11 } }, grid: { color: 'rgba(255,255,255,0.06)' } }
            }
        }
    });
}

function renderChartJSRAG() {
    const canvas = document.getElementById('rag-comparison-chart');
    if (!canvas) return;
    destroyChart('rag-comparison-chart');
    
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    
    chartInstances['rag-comparison-chart'] = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: ['Simple QA', 'Multi-Hop', 'Cross-Doc Synthesis', 'Temporal Resol.'],
            datasets: [
                {
                    label: 'Dense Vector Only',
                    data: [72, 44, 32, 40],
                    backgroundColor: 'rgba(100, 116, 139, 0.7)',
                    borderRadius: 6
                },
                {
                    label: 'Hybrid + Graph RAG',
                    data: [92, 86, 82, 88],
                    backgroundColor: 'rgba(16, 185, 129, 0.8)',
                    borderRadius: 6
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: '#94a3b8', font: { family: 'Inter' } } }
            },
            scales: {
                x: { ticks: { color: '#94a3b8', font: { family: 'Inter', size: 11 } }, grid: { display: false } },
                y: { max: 100, ticks: { color: '#94a3b8', font: { family: 'Inter', size: 11 }, callback: v => v + '%' }, grid: { color: 'rgba(255,255,255,0.06)' } }
            }
        }
    });
}

// Master Render Function
function renderCharts() {
    const containerToken = document.getElementById('token-saving-container');
    const containerRAG = document.getElementById('rag-comparison-container');
    
    if (typeof Chart !== 'undefined') {
        // Render via Chart.js
        renderChartJSTokenSaving();
        renderChartJSRAG();
    } else {
        // Instant resilient native fallback
        renderNativeTokenSavingChart(containerToken);
        renderNativeRAGChart(containerRAG);
    }
}

function updateChartsForTheme() {
    renderCharts();
}

// Global Export
window.Charts = {
    renderCharts,
    updateChartsForTheme,
    destroyChart
};

// Auto-trigger if benchmarks tab is active
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        setTimeout(renderCharts, 100);
    });
} else {
    setTimeout(renderCharts, 100);
}