// ==========================================================================
// Search Module - Client-side Full-Text Search with Fuse.js-like logic
// ==========================================================================

class SearchIndex {
    constructor() {
        this.indices = new Map();
        this.options = {
            threshold: 0.3,
            distance: 100,
            minMatchCharLength: 2,
            keys: []
        };
    }
    
    // Build search index for a dataset
    buildIndex(name, items, keys) {
        const index = items.map((item, idx) => ({
            id: idx,
            item,
            searchableText: this.extractSearchableText(item, keys)
        }));
        this.indices.set(name, { items: index, keys });
        return this;
    }
    
    // Extract searchable text from item based on keys
    extractSearchableText(item, keys) {
        const texts = [];
        keys.forEach(key => {
            const value = this.getNestedValue(item, key);
            if (value !== undefined && value !== null) {
                if (Array.isArray(value)) {
                    texts.push(...value.map(v => String(v)).filter(Boolean));
                } else {
                    texts.push(String(value));
                }
            }
        });
        return texts.join(' ').toLowerCase();
    }
    
    getNestedValue(obj, path) {
        return path.split('.').reduce((o, k) => (o || {})[k], obj);
    }
    
    // Simple fuzzy search
    search(name, query, limit = 50) {
        const index = this.indices.get(name);
        if (!index || !query.trim()) return index?.items.map(i => i.item) || [];
        
        const terms = query.toLowerCase().split(/\s+/).filter(t => t.length >= this.options.minMatchCharLength);
        if (terms.length === 0) return index.items.map(i => i.item);
        
        const results = index.items.map(entry => {
            let score = 0;
            const text = entry.searchableText;
            
            terms.forEach(term => {
                // Exact match bonus
                if (text.includes(term)) score += 10;
                
                // Word boundary match
                const wordRegex = new RegExp(`\\b${this.escapeRegex(term)}`, 'i');
                if (wordRegex.test(text)) score += 5;
                
                // Fuzzy match (simple prefix)
                if (text.split(' ').some(word => word.startsWith(term))) score += 2;
                
                // Substring match
                if (text.includes(term)) score += 1;
            });
            
            return { ...entry, score };
        })
        .filter(r => r.score > 0)
        .sort((a, b) => b.score - a.score)
        .slice(0, limit)
        .map(r => r.item);
        
        return results;
    }
    
    escapeRegex(str) {
        return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }
}

// Global Search Instance
const searchIndex = new SearchIndex();

// Initialize Search Indices
function initSearchIndices() {
    // Wait for data to be loaded
    if (window.AppState?.data && (window.AppState.data.companies?.length > 0 || window.AppState.data.papers?.length > 0)) {
        buildAllIndices();
    } else {
        // Retry after a short delay
        setTimeout(initSearchIndices, 200);
    }
}

function buildAllIndices() {
    const { companies, papers, benchmarks, innovations } = window.AppState.data;
    
    // Companies index
    searchIndex.buildIndex('companies', companies || [], [
        'name',
        'technologies',
        'keyPapers',
        'topics',
        'notes'
    ]);
    
    // Papers index
    searchIndex.buildIndex('papers', papers || [], [
        'title',
        'authors',
        'venue',
        'keyFindings',
        'topics'
    ]);
    
    // Benchmarks indices
    if (benchmarks) {
        ['tokenSaving', 'contextHandling', 'dataLeakPrevention', 'localAgents'].forEach(cat => {
            searchIndex.buildIndex(`benchmarks.${cat}`, benchmarks[cat] || [], [
                'method', 'category', 'solution', 'model', 'tool',
                'source', 'frameworks', 'technologies'
            ]);
        });
    }
    
    // Innovations index
    searchIndex.buildIndex('innovations', innovations || [], [
        'title', 'description', 'technicalApproach',
        'currentGap', 'relatedWork', 'implementationPath',
        'metrics', 'standoutPotential'
    ]);
    
    console.log('Search indices built');
}

// Search Function for UI
function performSearch(category, query) {
    const results = searchIndex.search(category, query);
    window.Navigation?.announceResultsCount(results.length, 'results');
    return results;
}

// Debounced Search Input Handler
function createSearchHandler(category, filterKey, renderFn) {
    let debounceTimer;
    return function(e) {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            const value = e.target.value;
            if (window.AppState?.filters?.[category]) {
                window.AppState.filters[category][filterKey] = value;
                // Trigger custom event for components to listen
                window.dispatchEvent(new CustomEvent('search-update', {
                    detail: { category, query: value }
                }));
                if (renderFn) renderFn();
            }
        }, 300);
    };
}

// Global Search (searches across all indices)
function globalSearch(query) {
    const allResults = [];
    const categories = ['companies', 'papers', 'benchmarks.tokenSaving', 'benchmarks.contextHandling', 'benchmarks.dataLeakPrevention', 'benchmarks.localAgents', 'innovations'];
    
    categories.forEach(cat => {
        const results = searchIndex.search(cat, query, 10);
        if (results.length > 0) {
            allResults.push({ category: cat, results });
        }
    });
    
    return allResults;
}

// Search UI Component (can be added to header)
function createGlobalSearchUI() {
    const searchContainer = document.createElement('div');
    searchContainer.className = 'global-search';
    searchContainer.innerHTML = `
        <label for="global-search" class="sr-only">Search all research</label>
        <input type="search" id="global-search" placeholder="Search companies, papers, benchmarks..." aria-label="Search all research" autocomplete="off">
        <div id="global-search-results" class="search-results" hidden></div>
    `;
    
    const input = searchContainer.querySelector('#global-search');
    const resultsContainer = searchContainer.querySelector('#global-search-results');
    
    let debounceTimer;
    input.addEventListener('input', (e) => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            const query = e.target.value.trim();
            if (query.length < 2) {
                resultsContainer.hidden = true;
                return;
            }
            
            const allResults = globalSearch(query);
            renderGlobalSearchResults(resultsContainer, allResults, query);
            resultsContainer.hidden = false;
        }, 200);
    });
    
    // Close on outside click
    document.addEventListener('click', (e) => {
        if (!searchContainer.contains(e.target)) {
            resultsContainer.hidden = true;
        }
    });
    
    return searchContainer;
}

function renderGlobalSearchResults(container, allResults, query) {
    if (allResults.length === 0) {
        container.innerHTML = '<div class="search-no-results">No results found</div>';
        return;
    }
    
    container.innerHTML = allResults.map(({ category, results }) => `
        <div class="search-category">
            <h5>${formatCategoryName(category)}</h5>
            <ul>
                ${results.slice(0, 5).map(item => `
                    <li class="search-result-item" data-detail='${escapeHTML(JSON.stringify(item))}'>
                        ${getResultTitle(item, category)}
                    </li>
                `).join('')}
            </ul>
        </div>
    `).join('');
    
    // Add click handlers
    container.querySelectorAll('.search-result-item').forEach(item => {
        item.addEventListener('click', () => {
            const showModal = window.showDetailModal || window.AppState?.showDetailModal;
            if (showModal) showModal(item.dataset.detail);
            container.hidden = true;
            input.value = '';
        });
    });
}

function formatCategoryName(cat) {
    const names = {
        'companies': 'Companies',
        'papers': 'Papers',
        'benchmarks.tokenSaving': 'Token Saving',
        'benchmarks.contextHandling': 'Context Handling',
        'benchmarks.dataLeakPrevention': 'Data Leak Prevention',
        'benchmarks.localAgents': 'Local Agents',
        'innovations': 'Innovations'
    };
    return names[cat] || cat;
}

function getResultTitle(item, category) {
    return item.title || item.name || item.method || item.model || item.tool || item.solution || 'Untitled';
}

function escapeHTML(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// Export
window.Search = {
    index: searchIndex,
    init: initSearchIndices,
    search: performSearch,
    globalSearch,
    createUI: createGlobalSearchUI,
    createHandler: createSearchHandler
};

// Initialize when data is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSearchIndices);
} else {
    initSearchIndices();
}