/**
 * Keyboard Shortcuts Manager
 * Shortcuts: / (search), Escape (overview), g+w (workflows), g+r (runs), ? (help)
 */

class KeyboardShortcutManager {
    constructor() {
        this.shortcuts = new Map();
        this.sequenceBuffer = [];
        this.sequenceTimeout = null;
        this.isEnabled = true;
        this.handleKeyDown = this.handleKeyDown.bind(this);
        this.init();
    }

    init() {
        document.addEventListener('keydown', this.handleKeyDown);
        this.registerDefaults();
    }

    registerDefaults() {
        // Search focus
        this.register('/', () => {
            const searchInput = document.getElementById('search-input');
            if (searchInput) {
                searchInput.focus();
                searchInput.select();
            }
        }, 'Focus search');

        // Escape - Return to overview
        this.register('Escape', () => {
            const modals = document.querySelectorAll('.modal[style*="display: flex"]');
            if (modals.length > 0) return; // Let modal handle escape

            const searchInput = document.getElementById('search-input');
            if (searchInput && searchInput.value) {
                searchInput.value = '';
                searchInput.dispatchEvent(new Event('input'));
                return;
            }

            if (typeof showOverview === 'function') {
                showOverview();
            }
        }, 'Return to overview or clear search');

        // Go to workflows (g + w)
        this.registerSequence(['g', 'w'], () => {
            if (typeof showAllWorkflows === 'function') {
                showAllWorkflows();
            }
        }, 'Go to workflows');

        // Go to runs (g + r)
        this.registerSequence(['g', 'r'], () => {
            if (typeof showAllRuns === 'function') {
                showAllRuns();
            }
        }, 'Go to runs');

        // Go to actions (g + a)
        this.registerSequence(['g', 'a'], () => {
            if (typeof showFilteredActions === 'function') {
                showFilteredActions('all-actions');
            }
        }, 'Go to actions');

        // Show shortcuts help (?)
        this.register('?', () => {
            this.showHelp();
        }, 'Show keyboard shortcuts');
    }

    register(keys, handler, description = '') {
        const keyArray = Array.isArray(keys) ? keys : [keys];
        keyArray.forEach(key => {
            this.shortcuts.set(key.toLowerCase(), {
                handler,
                description,
                key: key
            });
        });
    }

    registerSequence(sequence, handler, description = '') {
        const key = sequence.join('+');
        this.shortcuts.set(key, {
            handler,
            description,
            sequence,
            key: sequence.join(' then ')
        });
    }

    handleKeyDown(event) {
        if (!this.isEnabled) return;

        // Don't trigger shortcuts when typing in inputs
        const tagName = event.target.tagName.toLowerCase();
        const isInput = ['input', 'textarea', 'select'].includes(tagName);
        const allowedInInputs = ['Escape', '?', '/'];

        if (isInput && !allowedInInputs.includes(event.key)) {
            return;
        }

        // Build key combination
        let key = event.key;
        const modifiers = [];

        if (event.ctrlKey) modifiers.push('Control');
        if (event.altKey) modifiers.push('Alt');
        if (event.metaKey) modifiers.push('Meta');
        if (event.shiftKey && event.key.length > 1) modifiers.push('Shift');

        const fullKey = modifiers.length > 0
            ? `${modifiers.join('+')}+${key}`
            : key;

        // Check for direct match
        const shortcut = this.shortcuts.get(fullKey.toLowerCase());
        if (shortcut && !shortcut.sequence) {
            event.preventDefault();
            shortcut.handler(event);
            return;
        }

        // Handle sequences (like g + w)
        if (!modifiers.length && key.length === 1) {
            this.sequenceBuffer.push(key.toLowerCase());

            clearTimeout(this.sequenceTimeout);
            this.sequenceTimeout = setTimeout(() => {
                this.sequenceBuffer = [];
            }, 1000);

            const sequenceKey = this.sequenceBuffer.join('+');
            const sequenceShortcut = this.shortcuts.get(sequenceKey);

            if (sequenceShortcut) {
                event.preventDefault();
                this.sequenceBuffer = [];
                clearTimeout(this.sequenceTimeout);
                sequenceShortcut.handler(event);
            }
        }
    }

    showHelp() {
        const shortcuts = Array.from(this.shortcuts.values());

        let helpHTML = '<div class="shortcuts-help"><h2>Keyboard Shortcuts</h2>';
        helpHTML += '<div class="shortcuts-category"><h3>Navigation</h3><dl class="shortcuts-list">';

        shortcuts.forEach(item => {
            const keys = item.sequence
                ? item.sequence.map(k => `<kbd>${k}</kbd>`).join(' then ')
                : `<kbd>${item.key}</kbd>`;

            helpHTML += `
                <div class="shortcut-item">
                    <dt>${keys}</dt>
                    <dd>${item.description}</dd>
                </div>
            `;
        });

        helpHTML += '</dl></div></div>';

        if (window.A11y && window.A11y.AccessibleModal) {
            const modal = new window.A11y.AccessibleModal({
                title: 'Keyboard Shortcuts',
                content: helpHTML,
                confirmText: 'Got it'
            });
            modal.open();
        }
    }
}

if (typeof window !== 'undefined') {
    window.KeyboardShortcutManager = KeyboardShortcutManager;
}
