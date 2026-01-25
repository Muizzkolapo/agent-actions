// ============================================
// PROMPT RENDERER - Vanilla JS
// Rich markdown rendering for prompt content
// ============================================

const PromptRenderer = (function() {
    'use strict';

    // ============================================
    // TOKENIZER - Parse markdown into tokens
    // ============================================
    function tokenize(content) {
        if (!content) return [];

        const lines = content.split('\n');
        const tokens = [];
        let i = 0;

        while (i < lines.length) {
            const line = lines[i];
            const trimmed = line.trim();

            // Empty line = spacer
            if (!trimmed) {
                if (tokens.length > 0 && tokens[tokens.length - 1].type !== 'spacer') {
                    tokens.push({ type: 'spacer' });
                }
                i++;
                continue;
            }

            // H1: # Header
            if (/^# /.test(trimmed)) {
                tokens.push({ type: 'h1', content: trimmed.slice(2) });
                i++;
                continue;
            }

            // H2: ## Header
            if (/^## /.test(trimmed)) {
                tokens.push({ type: 'h2', content: trimmed.slice(3) });
                i++;
                continue;
            }

            // H3: ### Header
            if (/^### /.test(trimmed)) {
                tokens.push({ type: 'h3', content: trimmed.slice(4) });
                i++;
                continue;
            }

            // Code block: ```lang
            if (/^```/.test(trimmed)) {
                const lang = trimmed.slice(3).trim();
                const codeLines = [];
                i++;
                while (i < lines.length && !lines[i].trim().startsWith('```')) {
                    codeLines.push(lines[i]);
                    i++;
                }
                tokens.push({ type: 'codeblock', lang: lang, content: codeLines.join('\n') });
                i++;
                continue;
            }

            // Unordered list: - item or * item
            if (/^[-*] /.test(trimmed)) {
                const listItems = [];
                while (i < lines.length && /^[-*] /.test(lines[i].trim())) {
                    listItems.push(lines[i].trim().slice(2));
                    i++;
                }
                tokens.push({ type: 'ul', items: listItems });
                continue;
            }

            // Ordered list: 1. item
            if (/^\d+\. /.test(trimmed)) {
                const listItems = [];
                while (i < lines.length && /^\d+\. /.test(lines[i].trim())) {
                    listItems.push(lines[i].trim().replace(/^\d+\. /, ''));
                    i++;
                }
                tokens.push({ type: 'ol', items: listItems });
                continue;
            }

            // Blockquote: > text
            if (/^> /.test(trimmed)) {
                const quoteLines = [];
                while (i < lines.length && /^> /.test(lines[i].trim())) {
                    quoteLines.push(lines[i].trim().slice(2));
                    i++;
                }
                tokens.push({ type: 'blockquote', content: quoteLines.join('\n') });
                continue;
            }

            // Horizontal rule: --- or ***
            if (/^(---|\*\*\*)$/.test(trimmed)) {
                tokens.push({ type: 'hr' });
                i++;
                continue;
            }

            // Paragraph: collect consecutive non-special lines
            const paraLines = [];
            while (i < lines.length && lines[i].trim() &&
                   !/^(#{1,3} |```|[-*] |\d+\. |> |---|\*\*\*)/.test(lines[i].trim())) {
                paraLines.push(lines[i].trim());
                i++;
            }
            if (paraLines.length > 0) {
                tokens.push({ type: 'paragraph', content: paraLines.join(' ') });
            }
        }

        return tokens;
    }

    // ============================================
    // INLINE PARSER - Variables & formatting
    // ============================================
    function parseInline(text) {
        if (!text) return '';

        let result = escapeHtml(text);

        // Template variables: {{ variable }}
        result = result.replace(/\{\{\s*([^}]+)\s*\}\}/g, (_, varName) => {
            return `<span class="pr-variable">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                    <polyline points="4,7 4,4 20,4 20,7"/>
                    <line x1="9" y1="20" x2="15" y2="20"/>
                    <line x1="12" y1="4" x2="12" y2="20"/>
                </svg>
                ${escapeHtml(varName.trim())}
            </span>`;
        });

        // Single brace variables: {variable}
        result = result.replace(/\{([a-zA-Z_][a-zA-Z0-9_.]*)\}/g, (_, varName) => {
            return `<span class="pr-variable-alt">${escapeHtml(varName)}</span>`;
        });

        // Bold + Italic: ***text*** or ___text___
        result = result.replace(/(\*\*\*|___)(.+?)\1/g, '<strong><em>$2</em></strong>');

        // Bold: **text** or __text__
        result = result.replace(/(\*\*|__)(.+?)\1/g, '<strong class="pr-bold">$2</strong>');

        // Italic: *text* or _text_
        result = result.replace(/(\*|_)(.+?)\1/g, '<em>$2</em>');

        // Inline code: `code`
        result = result.replace(/`([^`]+)`/g, '<code class="pr-inline-code">$1</code>');

        // Check marks
        result = result.replace(/(✅|✓)/g, '<span class="pr-check">✓</span>');

        // X marks
        result = result.replace(/(❌|✗)/g, '<span class="pr-x">✗</span>');

        return result;
    }

    // ============================================
    // PATTERN DETECTION - Semantic sections
    // ============================================
    function detectPattern(text) {
        if (!text) return null;
        const lower = text.toLowerCase();
        const clean = text.replace(/[*_:#]/g, '').trim().toLowerCase();

        if (/^(critical|important|warning|caution|danger)/i.test(clean)) {
            return 'critical';
        }
        if (/^(note|tip|info|hint)/i.test(clean)) {
            return 'info';
        }
        if (/what you (can|should|must) do/i.test(lower) || /^(allowed|permitted|do this)/i.test(clean)) {
            return 'can-do';
        }
        if (/what you (cannot|can't|should not|must not) do/i.test(lower) || /^(not allowed|forbidden|don't|avoid)/i.test(clean)) {
            return 'cannot-do';
        }
        if (/example/i.test(lower)) {
            return 'example';
        }
        if (/output|result|response/i.test(lower)) {
            return 'output';
        }
        if (/input|task|context/i.test(lower)) {
            return 'input';
        }
        if (/constraint|restriction|rule|requirement/i.test(lower)) {
            return 'constraint';
        }
        return null;
    }

    // ============================================
    // VARIABLE EXTRACTION
    // ============================================
    function extractVariables(content) {
        if (!content) return [];

        const vars = new Set();

        // Match {{ variable }}
        const matches1 = content.matchAll(/\{\{\s*([^}]+)\s*\}\}/g);
        for (const m of matches1) vars.add(m[1].trim());

        // Match {variable}
        const matches2 = content.matchAll(/\{([a-zA-Z_][a-zA-Z0-9_.]*)\}/g);
        for (const m of matches2) vars.add(m[1]);

        return Array.from(vars).map(v => ({
            name: v,
            type: inferType(v)
        }));
    }

    function inferType(varName) {
        const lower = varName.toLowerCase();
        if (lower.includes('content') || lower.includes('text') || lower.includes('doc')) return 'text';
        if (lower.includes('code')) return 'code';
        if (lower.includes('list') || lower.includes('array') || lower.includes('items')) return 'array';
        if (lower.includes('count') || lower.includes('number') || lower.includes('num') || lower.includes('length')) return 'number';
        if (lower.includes('flag') || lower.includes('is_') || lower.includes('has_') || lower.includes('should')) return 'boolean';
        return 'string';
    }

    // ============================================
    // ICONS
    // ============================================
    function getSectionIcon(pattern) {
        const icons = {
            critical: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/>
                <line x1="12" y1="8" x2="12" y2="12"/>
                <line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>`,
            constraint: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/>
                <line x1="12" y1="8" x2="12" y2="12"/>
                <line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>`,
            example: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="16,18 22,12 16,6"/>
                <polyline points="8,6 2,12 8,18"/>
            </svg>`,
            output: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                <polyline points="7,10 12,15 17,10"/>
                <line x1="12" y1="15" x2="12" y2="3"/>
            </svg>`,
            input: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
                <polyline points="22,4 12,14.01 9,11.01"/>
            </svg>`,
            info: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/>
                <line x1="12" y1="16" x2="12" y2="12"/>
                <line x1="12" y1="8" x2="12.01" y2="8"/>
            </svg>`,
            'can-do': `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="20,6 9,17 4,12"/>
            </svg>`,
            'cannot-do': `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/>
                <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>`,
            default: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/>
            </svg>`
        };
        return icons[pattern] || icons.default;
    }

    function getListIcon(item, listPattern) {
        if (/^(✅|✓)/.test(item) || listPattern === 'can-do') {
            return `<svg class="pr-list-icon pr-can" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <polyline points="20,6 9,17 4,12"/>
            </svg>`;
        }
        if (/^(❌|✗)/.test(item) || listPattern === 'cannot-do') {
            return `<svg class="pr-list-icon pr-cannot" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <line x1="18" y1="6" x2="6" y2="18"/>
                <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>`;
        }
        return '<span class="pr-list-bullet">•</span>';
    }

    // ============================================
    // TOKEN RENDERER
    // ============================================
    function renderToken(token, index, allTokens) {
        const prevToken = index > 0 ? allTokens[index - 1] : null;
        const pattern = token.content ? detectPattern(token.content) : null;

        switch (token.type) {
            case 'spacer':
                return '<div class="pr-spacer"></div>';

            case 'h1':
                return `<h1 class="pr-h1">${parseInline(token.content)}</h1>`;

            case 'h2':
                return `
                    <div class="pr-section ${pattern || ''}">
                        <div class="pr-section-header">
                            <div class="pr-section-icon ${pattern || ''}">${getSectionIcon(pattern)}</div>
                            <h2>${parseInline(token.content)}</h2>
                        </div>
                    </div>`;

            case 'h3':
                return `<h3 class="pr-h3 ${pattern || ''}">${parseInline(token.content)}</h3>`;

            case 'paragraph':
                // Critical alert box
                if (pattern === 'critical') {
                    const cleanContent = token.content.replace(/^\**(critical|important|warning)[:\s]*/i, '');
                    return `
                        <div class="pr-alert pr-alert-critical">
                            <div class="pr-alert-header">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                                    <line x1="12" y1="9" x2="12" y2="13"/>
                                    <line x1="12" y1="17" x2="12.01" y2="17"/>
                                </svg>
                                <span>Critical</span>
                            </div>
                            <p>${parseInline(cleanContent)}</p>
                        </div>`;
                }

                // Info box
                if (pattern === 'info') {
                    const cleanContent = token.content.replace(/^\**(note|tip|info|hint)[:\s]*/i, '');
                    return `
                        <div class="pr-alert pr-alert-info">
                            <div class="pr-alert-header">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <circle cx="12" cy="12" r="10"/>
                                    <line x1="12" y1="16" x2="12" y2="12"/>
                                    <line x1="12" y1="8" x2="12.01" y2="8"/>
                                </svg>
                                <span>Note</span>
                            </div>
                            <p>${parseInline(cleanContent)}</p>
                        </div>`;
                }

                return `<p class="pr-paragraph">${parseInline(token.content)}</p>`;

            case 'codeblock':
                return `
                    <div class="pr-codeblock-wrapper">
                        ${token.lang ? `<div class="pr-codeblock-lang">${escapeHtml(token.lang)}</div>` : ''}
                        <pre class="pr-codeblock"><code>${escapeHtml(token.content)}</code></pre>
                    </div>`;

            case 'ul':
                const listPattern = prevToken?.content ? detectPattern(prevToken.content) : null;
                return `
                    <ul class="pr-ul ${listPattern || ''}">
                        ${token.items.map(item => `
                            <li>
                                ${getListIcon(item, listPattern)}
                                <span>${parseInline(item)}</span>
                            </li>
                        `).join('')}
                    </ul>`;

            case 'ol':
                return `
                    <ol class="pr-ol">
                        ${token.items.map((item, i) => `
                            <li>
                                <span class="pr-ol-number">${i + 1}</span>
                                <span>${parseInline(item)}</span>
                            </li>
                        `).join('')}
                    </ol>`;

            case 'blockquote':
                return `<blockquote class="pr-blockquote">${parseInline(token.content)}</blockquote>`;

            case 'hr':
                return '<hr class="pr-hr">';

            default:
                return '';
        }
    }

    // ============================================
    // UTILITY
    // ============================================
    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // ============================================
    // PUBLIC API
    // ============================================

    /**
     * Render prompt content with rich formatting
     * @param {string} content - Raw prompt content
     * @param {Object} options - Render options
     * @returns {string} HTML string
     */
    function render(content, options = {}) {
        const tokens = tokenize(content);
        const html = tokens.map((token, i) => renderToken(token, i, tokens)).join('');
        return `<div class="pr-content">${html}</div>`;
    }

    /**
     * Render variables table
     * @param {string} content - Raw prompt content
     * @returns {string} HTML string
     */
    function renderVariables(content) {
        const variables = extractVariables(content);

        if (variables.length === 0) {
            return `<div class="pr-empty">No template variables detected in this prompt</div>`;
        }

        return `
            <p class="pr-variables-intro">
                This prompt uses <strong>${variables.length}</strong> template variable${variables.length !== 1 ? 's' : ''}.
            </p>
            <div class="pr-variables-table">
                <div class="pr-variables-header">
                    <span>Variable Name</span>
                    <span>Inferred Type</span>
                </div>
                ${variables.map(v => `
                    <div class="pr-variable-row">
                        <code class="pr-variable-name">{{ ${escapeHtml(v.name)} }}</code>
                        <span class="pr-variable-type">${v.type}</span>
                    </div>
                `).join('')}
            </div>`;
    }

    /**
     * Render raw content in a styled pre block
     * @param {string} content - Raw prompt content
     * @returns {string} HTML string
     */
    function renderRaw(content) {
        return `<pre class="pr-raw">${escapeHtml(content || 'No content')}</pre>`;
    }

    /**
     * Create full prompt view with tabs
     * @param {string} content - Raw prompt content
     * @param {Object} meta - Prompt metadata
     * @returns {string} HTML string
     */
    function createView(content, meta = {}) {
        const variables = extractVariables(content);
        const charCount = content ? content.length : 0;

        return `
            <div class="pr-view">
                <!-- Meta bar -->
                <div class="pr-meta-bar">
                    <div class="pr-meta-item">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                            <polyline points="14,2 14,8 20,8"/>
                        </svg>
                        <span class="pr-meta-highlight">${escapeHtml(meta.source_file_name || 'unknown.md')}</span>
                    </div>
                    <div class="pr-meta-divider"></div>
                    <div class="pr-meta-item">
                        Lines: <span class="pr-meta-value">${meta.line_start || 0} - ${meta.line_end || 0}</span>
                    </div>
                    <div class="pr-meta-divider"></div>
                    <div class="pr-meta-item">
                        <span class="pr-meta-value">${charCount.toLocaleString()}</span> chars
                    </div>
                    <div class="pr-meta-divider"></div>
                    <div class="pr-meta-item">
                        <span class="pr-meta-value">${variables.length}</span> variables
                    </div>
                </div>

                <!-- Tabs -->
                <div class="pr-tabs-row">
                    <span class="pr-tabs-label">Prompt Content</span>
                    <div class="pr-tabs">
                        <button class="pr-tab active" data-tab="rendered">Rendered</button>
                        <button class="pr-tab" data-tab="raw">Raw</button>
                        <button class="pr-tab" data-tab="variables">Variables</button>
                        <button class="pr-tab pr-copy-btn" data-action="copy">
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <rect x="9" y="9" width="13" height="13" rx="2"/>
                                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                            </svg>
                            Copy
                        </button>
                    </div>
                </div>

                <!-- Tab content -->
                <div class="pr-tab-content" data-tab-content="rendered">
                    ${render(content)}
                </div>
                <div class="pr-tab-content" data-tab-content="raw" style="display: none;">
                    ${renderRaw(content)}
                </div>
                <div class="pr-tab-content" data-tab-content="variables" style="display: none;">
                    ${renderVariables(content)}
                </div>
            </div>`;
    }

    /**
     * Initialize tab switching for a prompt view
     * @param {HTMLElement} container - Container element
     * @param {string} content - Raw content for copy functionality
     */
    function initTabs(container, content) {
        const tabs = container.querySelectorAll('.pr-tab[data-tab]');
        const contents = container.querySelectorAll('.pr-tab-content');
        const copyBtn = container.querySelector('.pr-copy-btn');

        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                const tabName = tab.dataset.tab;

                // Update active tab
                tabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');

                // Show corresponding content
                contents.forEach(c => {
                    c.style.display = c.dataset.tabContent === tabName ? 'block' : 'none';
                });
            });
        });

        if (copyBtn) {
            copyBtn.addEventListener('click', async () => {
                try {
                    await navigator.clipboard.writeText(content);
                    const originalText = copyBtn.innerHTML;
                    copyBtn.innerHTML = `
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="20,6 9,17 4,12"/>
                        </svg>
                        Copied!`;
                    setTimeout(() => {
                        copyBtn.innerHTML = originalText;
                    }, 2000);
                } catch (err) {
                    console.error('Failed to copy:', err);
                }
            });
        }
    }

    // Export public API
    return {
        render,
        renderVariables,
        renderRaw,
        createView,
        initTabs,
        tokenize,
        extractVariables,
        detectPattern
    };
})();

// Make available globally
window.PromptRenderer = PromptRenderer;
