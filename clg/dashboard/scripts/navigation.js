// ==========================================================================
// Navigation Module - Keyboard Navigation, Focus Management
// ==========================================================================

// Keyboard Navigation for Tab Panels
function initTabKeyboardNavigation() {
    const tabPanels = document.querySelectorAll('.tab-panel');
    
    tabPanels.forEach(panel => {
        panel.addEventListener('keydown', (e) => {
            // Tab key within panel - let browser handle naturally
            // But ensure focus stays within modal when open
            const modal = document.getElementById('detail-modal');
            if (!modal.hidden && e.key === 'Tab') {
                trapFocus(e, modal);
            }
        });
    });
}

// Focus Trap for Modal
function trapFocus(e, container) {
    const focusableElements = container.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    
    const firstElement = focusableElements[0];
    const lastElement = focusableElements[focusableElements.length - 1];
    
    if (e.shiftKey && document.activeElement === firstElement) {
        e.preventDefault();
        lastElement.focus();
    } else if (!e.shiftKey && document.activeElement === lastElement) {
        e.preventDefault();
        firstElement.focus();
    }
}

// Restore Focus After Modal Close
let lastFocusedElement = null;

function saveFocus() {
    lastFocusedElement = document.activeElement;
}

function restoreFocus() {
    if (lastFocusedElement && typeof lastFocusedElement.focus === 'function') {
        lastFocusedElement.focus();
    }
}

// Enhanced Keyboard Navigation for Data Tables
function enhanceTableKeyboardNavigation() {
    document.querySelectorAll('.data-table').forEach(table => {
        // Make rows focusable
        const rows = table.querySelectorAll('tbody tr');
        rows.forEach((row, index) => {
            row.setAttribute('tabindex', '0');
            row.setAttribute('role', 'row');
            
            // Add row number for screen readers
            const firstCell = row.querySelector('td');
            if (firstCell && !firstCell.querySelector('.sr-only')) {
                const srLabel = document.createElement('span');
                srLabel.className = 'sr-only';
                srLabel.textContent = `Row ${index + 1}`;
                firstCell.insertBefore(srLabel, firstCell.firstChild);
            }
        });
        
        // Add keyboard instructions
        const caption = table.querySelector('caption');
        if (caption && !caption.querySelector('.kbd-hint')) {
            const hint = document.createElement('span');
            hint.className = 'sr-only kbd-hint';
            hint.textContent = 'Use arrow keys to navigate rows. Press Enter for details.';
            caption.appendChild(hint);
        }
    });
}

// Skip Link Enhancement
function enhanceSkipLink() {
    const skipLink = document.querySelector('.skip-link');
    if (skipLink) {
        skipLink.addEventListener('click', (e) => {
            const target = document.getElementById('main-content');
            if (target) {
                e.preventDefault();
                target.setAttribute('tabindex', '-1');
                target.focus({ preventScroll: true });
                target.removeAttribute('tabindex');
                history.pushState(null, '', '#main-content');
            }
        });
    }
}

// ARIA Live Regions for Dynamic Content
function announceToScreenReader(message, priority = 'polite') {
    const liveRegion = document.getElementById('aria-live') || createLiveRegion();
    liveRegion.setAttribute('aria-live', priority);
    liveRegion.textContent = '';
    // Force reflow
    liveRegion.offsetHeight;
    liveRegion.textContent = message;
}

function createLiveRegion() {
    const region = document.createElement('div');
    region.id = 'aria-live';
    region.className = 'sr-only';
    region.setAttribute('aria-live', 'polite');
    region.setAttribute('aria-atomic', 'true');
    document.body.appendChild(region);
    return region;
}

// Navigation State Announcements
function announceTabChange(tabName) {
    const names = {
        'overview': 'Overview',
        'token-saving': 'Token Saving',
        'context-handling': 'Context Handling',
        'data-leak-prevention': 'Data Leak Prevention',
        'local-agents': 'Local Specialist Agents',
        'innovations': 'Innovation Opportunities',
        'companies': 'Companies and Projects',
        'papers': 'Research Papers',
        'benchmarks': 'Benchmarks'
    };
    announceToScreenReader(`${names[tabName] || tabName} tab selected`);
}

function announceFilterChange(filterName, value) {
    if (value) {
        announceToScreenReader(`${filterName} filter set to ${value}`);
    } else {
        announceToScreenReader(`${filterName} filter cleared`);
    }
}

function announceResultsCount(count, type = 'results') {
    if (count === 0) {
        announceToScreenReader(`No ${type} found`, 'assertive');
    } else if (count === 1) {
        announceToScreenReader(`1 ${type} found`);
    } else {
        announceToScreenReader(`${count} ${type} found`);
    }
}

// Initialize Navigation Enhancements
function initNavigationEnhancements() {
    initTabKeyboardNavigation();
    enhanceTableKeyboardNavigation();
    enhanceSkipLink();
    
    // Listen for tab changes to announce
    const observer = new MutationObserver((mutations) => {
        mutations.forEach(mutation => {
            if (mutation.type === 'attributes' && mutation.attributeName === 'hidden') {
                const panel = mutation.target;
                if (panel.classList.contains('tab-panel') && panel.hidden === false) {
                    announceTabChange(panel.id);
                }
            }
        });
    });
    
    document.querySelectorAll('.tab-panel').forEach(panel => {
        observer.observe(panel, { attributes: true, attributeFilter: ['hidden'] });
    });
}

// Export for use in main.js
window.Navigation = {
    trapFocus,
    saveFocus,
    restoreFocus,
    announceToScreenReader,
    announceTabChange,
    announceFilterChange,
    announceResultsCount,
    initNavigationEnhancements
};

// Auto-initialize
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initNavigationEnhancements);
} else {
    initNavigationEnhancements();
}