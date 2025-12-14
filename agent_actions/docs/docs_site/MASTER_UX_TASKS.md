# Master UX Task List
## Agent Actions Documentation Site - Production Readiness

**Generated:** 2025-12-14
**Overall Readiness Score:** 73/100 (Needs Improvements)
**Navigation Health Score:** 92/100 (Excellent)

---

## 📊 Executive Summary

### Scores by Category
- ✅ **Navigation:** 92/100 - Excellent
- ✅ **Visual Design:** 90-95/100 - Excellent
- ✅ **User Experience:** 90-95/100 - Excellent
- ✅ **Functionality:** 90-95/100 - Excellent
- ⚠️ **Accessibility:** 0/100 - Critical Issues
- ⚠️ **Content/IA:** 85/100 - Needs Work

### Issue Breakdown
- 🔴 **Critical Issues:** 0 blockers
- 🟠 **High Priority:** 15 accessibility issues
- 🟡 **Medium Priority:** 12 navigation/UX improvements
- 🟢 **Low Priority:** 8 nice-to-have features

---

## 🎯 Prioritized Task List

Use this table to track all UX improvements. Mark tasks as complete as you finish them.

| # | Priority | Category | Task | Files to Modify | Effort | Status |
|---|----------|----------|------|-----------------|--------|--------|
| **PHASE 1: CRITICAL FIXES (Must Do Before Production)** |
| 1 | 🔴 Critical | Accessibility | Fix multiple H1 headings - ensure only ONE H1 per page | `index.html` | Low | ⬜ Todo |
| 2 | 🔴 Critical | Accessibility | Add aria-labels to all 15 unlabeled buttons | `index.html` | Low | ⬜ Todo |
| 3 | 🔴 Critical | Accessibility | Add `<label>` elements for all search input fields | `index.html` | Low | ⬜ Todo |
| 4 | 🔴 Critical | Content/IA | Fix page titles to match current page (not always "QanaLabs Workflows") | `js/app.js` | Low | ⬜ Todo |
| 5 | 🟠 High | Navigation | Add workflow context badges to action/prompt/schema cards | `js/app.js` (createActionCard, createPromptCard, createSchemaCard) | Medium | ⬜ Todo |
| 6 | 🟠 High | Navigation | Implement breadcrumb navigation system | `index.html`, `js/app.js`, `css/components/breadcrumbs.css` | Medium | ⬜ Todo |
| 7 | 🟠 High | Navigation | Add back buttons to all detail pages | `js/app.js` | Low | ⬜ Todo |
| **PHASE 2: UX IMPROVEMENTS (Production Ready+)** |
| 8 | 🟡 Medium | UX | Add loading skeletons/placeholders for better perceived performance | `index.html`, `css/components/loading.css` | Medium | ⬜ Todo |
| 9 | 🟡 Medium | UX | Add empty state illustrations/messages when no data | `js/app.js`, `css/components/empty-states.css` | Medium | ⬜ Todo |
| 10 | 🟡 Medium | UX | Add tooltips/help text for complex features | `index.html`, `js/tooltips.js` | Low | ⬜ Todo |
| 11 | 🟡 Medium | Functionality | Add "Create New" / primary action buttons on list pages | `index.html`, `js/app.js` | Low | ⬜ Todo |
| 12 | 🟡 Medium | Navigation | Add tabs to workflow detail (Overview/Actions/Prompts/Schemas/Runs) | `index.html`, `js/app.js`, `css/components/tabs.css` | High | ⬜ Todo |
| 13 | 🟡 Medium | Navigation | Add cross-reference links (action → workflow, prompt → workflow) | `js/app.js` | Medium | ⬜ Todo |
| 14 | 🟡 Medium | Navigation | Add "View All" links from filtered views | `index.html`, `js/app.js` | Low | ⬜ Todo |
| 15 | 🟡 Medium | Visual | Add active filter indicators (filter chips) | `js/filters.js`, `css/components/filters.css` | Low | ⬜ Todo |
| **PHASE 3: ENHANCED FEATURES (Nice to Have)** |
| 16 | 🟢 Low | Functionality | Add pagination for large datasets | `js/app.js`, `css/components/pagination.css` | Medium | ⬜ Todo |
| 17 | 🟢 Low | Functionality | Add export/download functionality | `js/export.js` | Medium | ⬜ Todo |
| 18 | 🟢 Low | UX | Add keyboard shortcuts (/ for search, g+w for workflows) | `js/keyboard-shortcuts.js` | Medium | ⬜ Todo |
| 19 | 🟢 Low | UX | Implement dark mode toggle | `css/themes/dark.css`, `js/theme-switcher.js` | High | ⬜ Todo |
| 20 | 🟢 Low | UX | Add command palette (Cmd+K) | `js/command-palette.js`, `css/components/command-palette.css` | High | ⬜ Todo |
| 21 | 🟢 Low | Navigation | Implement scroll position memory on back navigation | `js/app.js` | Low | ⬜ Todo |
| 22 | 🟢 Low | Dashboard | Add real-time updates to metric cards | `js/app.js` | Medium | ⬜ Todo |
| 23 | 🟢 Low | Dashboard | Add data visualizations/charts | `js/charts.js`, install chart library | High | ⬜ Todo |

---

## 📝 Detailed Task Descriptions & Implementation Guide

### PHASE 1: CRITICAL FIXES

#### Task 1: Fix Multiple H1 Headings
**Problem:** Each page has 11 H1 headings instead of 1, harming SEO and accessibility.

**Solution:**
```html
<!-- index.html - Change all secondary headings from h1 to h2 -->

<!-- BEFORE (wrong) -->
<h1 class="section-heading">All Workflows</h1>
<h1 class="section-heading">All Actions</h1>

<!-- AFTER (correct) -->
<h2 class="section-heading">All Workflows</h2>
<h2 class="section-heading">All Actions</h2>

<!-- Keep only ONE h1 per page - the main page title -->
<h1>Agent Actions Documentation</h1>
```

**Files:** `index.html`
**Search for:** `<h1 class="section-heading"`
**Replace with:** `<h2 class="section-heading"`

---

#### Task 2: Add ARIA Labels to Buttons
**Problem:** 15 buttons lack accessible labels for screen readers.

**Solution:**
```html
<!-- Add aria-label to all icon-only buttons -->

<!-- Filter button -->
<button class="filter-button" id="workflows-filter-button" aria-label="Show filters">
    <svg>...</svg>
    Filters
</button>

<!-- Sort button -->
<button class="sort-button" id="workflows-sort-button" aria-label="Sort options">
    <svg>...</svg>
    <span id="workflows-sort-label">Sort: Name (A-Z)</span>
</button>

<!-- View toggle buttons -->
<button class="view-btn active" data-view="grid" data-target="workflows"
        title="Grid View" aria-label="Switch to grid view">
    <svg>...</svg>
</button>

<!-- Search clear button -->
<button class="search-clear-btn" id="workflows-search-clear"
        title="Clear search" aria-label="Clear search">
    <svg>...</svg>
</button>
```

**Files:** `index.html`
**Action:** Add `aria-label` attribute to all buttons without text content.

---

#### Task 3: Add Labels to Input Fields
**Problem:** 7 search input fields missing `<label>` elements.

**Solution:**
```html
<!-- BEFORE -->
<input type="text" placeholder="Search workflows..." id="workflows-filter-search" />

<!-- AFTER - Option 1: Visible label -->
<label for="workflows-filter-search" class="sr-only">Search workflows</label>
<input type="text" placeholder="Search workflows..." id="workflows-filter-search" />

<!-- AFTER - Option 2: aria-label (if no visible label desired) -->
<input type="text" placeholder="Search workflows..."
       id="workflows-filter-search"
       aria-label="Search workflows" />
```

**Files:** `index.html`
**Action:** Add either `<label>` elements or `aria-label` attributes to all inputs:
- `#workflows-filter-search`
- `#actions-filter-search`
- `#prompts-filter-search`
- `#schemas-filter-search`
- `#runs-filter-search`
- `#runs-list-filter-search`
- `#search-input`

**CSS for screen-reader-only labels:**
```css
/* Add to css/utilities.css */
.sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border-width: 0;
}
```

---

#### Task 4: Fix Page Titles
**Problem:** All pages show "QanaLabs Workflows" regardless of current page.

**Solution:**
```javascript
// js/app.js - Add to each view function

function showAllWorkflows() {
    // ... existing code ...
    document.title = 'Workflows - Agent Actions';
}

function showFilteredActions(filterType) {
    // ... existing code ...
    const titles = {
        'all-actions': 'All Actions - Agent Actions',
        'llm': 'LLM Actions - Agent Actions',
        'tool': 'Tool Actions - Agent Actions'
    };
    document.title = titles[filterType] || 'Actions - Agent Actions';
}

function showAllPrompts() {
    document.title = 'Prompts - Agent Actions';
}

function showAllSchemas() {
    document.title = 'Schemas - Agent Actions';
}

function showRunsList() {
    document.title = 'Runs - Agent Actions';
}

function showObservability() {
    document.title = 'Observability Dashboard - Agent Actions';
}

function showHome() {
    document.title = 'Dashboard - Agent Actions';
}
```

**Files:** `js/app.js`
**Action:** Add `document.title = '...'` to each view rendering function.

---

#### Task 5: Add Workflow Context Badges
**Problem:** When viewing "All Actions", users can't see which workflow each action belongs to.

**Solution:**
```javascript
// js/app.js - Update card creation functions

function createActionCard(action, workflowName, workflowId) {
    const card = document.createElement('div');
    card.className = 'workflow-card';
    card.style.cursor = 'pointer';
    card.addEventListener('click', () => showActionDetail(action.id, workflowId));

    card.innerHTML = `
        <div class="workflow-card-header">
            <div>
                <h3>${action.name}</h3>
                <!-- ADD THIS: Workflow context badge -->
                <span class="workflow-context-badge"
                      onclick="event.stopPropagation(); navigateToWorkflow('${workflowId}');"
                      title="Part of ${workflowName}">
                    <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor">
                        <path d="M2 3h8v1H2V3zm0 3h8v1H2V6zm0 3h5v1H2V9z"/>
                    </svg>
                    ${workflowName}
                </span>
            </div>
            <span class="badge badge-${action.type}">${action.type}</span>
        </div>
        <p class="workflow-description">${action.intent || 'No description'}</p>
        <div class="workflow-meta">
            <span><strong>Type:</strong> ${action.type}</span>
        </div>
    `;

    return card;
}

// Similar updates for createPromptCard and createSchemaCard
function createPromptCard(prompt, workflowName, workflowId) {
    // ... add workflow-context-badge span similar to above
}

function createSchemaCard(schema, workflowName, workflowId) {
    // ... add workflow-context-badge span similar to above
}

// Helper function for navigation
function navigateToWorkflow(workflowId) {
    window.location.hash = `#/workflows/${workflowId}`;
}
```

**CSS:**
```css
/* css/components/badges.css - Add workflow context badge styles */

.workflow-context-badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 8px;
    margin-top: 4px;
    font-size: 0.75rem;
    color: var(--accent);
    background: var(--accent-light);
    border-radius: 4px;
    cursor: pointer;
    transition: all 0.2s;
    font-weight: 500;
}

.workflow-context-badge:hover {
    background: var(--accent);
    color: white;
    transform: translateY(-1px);
}

.workflow-context-badge svg {
    opacity: 0.7;
}
```

**Files:**
- `js/app.js` (createActionCard, createPromptCard, createSchemaCard)
- `css/components/badges.css` (new file or add to existing)

---

#### Task 6: Implement Breadcrumb Navigation
**Problem:** Users don't know where they are in the site hierarchy.

**Solution:**

**HTML Structure:**
```html
<!-- index.html - Add breadcrumb container to each content-view -->
<div class="content-view" id="workflows-list-view">
    <div class="page-header">
        <!-- ADD THIS: Breadcrumbs -->
        <nav aria-label="Breadcrumb" class="breadcrumb-container">
            <ol class="breadcrumb" id="breadcrumb-list">
                <li><a href="#/">Home</a></li>
                <li class="active">Workflows</li>
            </ol>
        </nav>

        <div class="page-title-section">
            <h1 class="page-title">Workflows</h1>
            <p class="subtitle">Browse and manage workflows</p>
        </div>
    </div>
    <!-- ... rest of content ... -->
</div>
```

**JavaScript:**
```javascript
// js/breadcrumbs.js - Create new file

class BreadcrumbManager {
    constructor() {
        this.container = document.getElementById('breadcrumb-list');
    }

    update(crumbs) {
        if (!this.container) return;

        this.container.innerHTML = '';

        crumbs.forEach((crumb, index) => {
            const li = document.createElement('li');

            if (index === crumbs.length - 1) {
                // Last item (current page)
                li.className = 'active';
                li.textContent = crumb.label;
            } else {
                // Clickable items
                const link = document.createElement('a');
                link.href = crumb.url;
                link.textContent = crumb.label;
                li.appendChild(link);
            }

            this.container.appendChild(li);
        });
    }
}

const breadcrumbManager = new BreadcrumbManager();

// Update in each view function
function showAllWorkflows() {
    breadcrumbManager.update([
        { label: 'Home', url: '#/' },
        { label: 'Workflows', url: '#/workflows' }
    ]);
    // ... rest of function
}

function showFilteredActions(filterType) {
    const labels = {
        'all-actions': 'All Actions',
        'llm': 'LLM Actions',
        'tool': 'Tool Actions'
    };

    breadcrumbManager.update([
        { label: 'Home', url: '#/' },
        { label: 'Actions', url: '#/actions' },
        { label: labels[filterType], url: `#/actions/${filterType}` }
    ]);
    // ... rest of function
}

function showWorkflowDetail(workflowId) {
    const workflow = catalog.workflows[workflowId];

    breadcrumbManager.update([
        { label: 'Home', url: '#/' },
        { label: 'Workflows', url: '#/workflows' },
        { label: workflow.name, url: `#/workflows/${workflowId}` }
    ]);
    // ... rest of function
}
```

**CSS:**
```css
/* css/components/breadcrumbs.css - Create new file */

.breadcrumb-container {
    margin-bottom: 16px;
}

.breadcrumb {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    list-style: none;
    padding: 0;
    margin: 0;
    font-size: 0.875rem;
    color: var(--text-muted);
}

.breadcrumb li {
    display: flex;
    align-items: center;
}

.breadcrumb li:not(:last-child)::after {
    content: '/';
    margin: 0 8px;
    color: var(--text-muted);
    opacity: 0.5;
}

.breadcrumb a {
    color: var(--accent);
    text-decoration: none;
    transition: color 0.2s;
}

.breadcrumb a:hover {
    color: var(--accent-dark);
    text-decoration: underline;
}

.breadcrumb li.active {
    color: var(--text);
    font-weight: 500;
}
```

**Files:**
- `index.html` (add breadcrumb containers)
- `js/breadcrumbs.js` (new file)
- `css/components/breadcrumbs.css` (new file)
- `index.html` (add script tag: `<script src="js/breadcrumbs.js"></script>`)

---

#### Task 7: Add Back Buttons
**Problem:** Detail pages lack explicit back navigation.

**Solution:**
```javascript
// js/app.js - Add helper function

function createBackButton(label, targetUrl) {
    const button = document.createElement('button');
    button.className = 'back-button';
    button.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M10 12L6 8l4-4"/>
        </svg>
        <span>Back to ${label}</span>
    `;
    button.addEventListener('click', () => {
        window.location.hash = targetUrl;
    });
    return button;
}

// Use in detail view functions
function showWorkflowDetail(workflowId) {
    // ... existing code ...

    const pageHeader = document.querySelector('#workflow-detail-view .page-header');
    const backButton = createBackButton('Workflows', '#/workflows');
    pageHeader.insertBefore(backButton, pageHeader.firstChild);

    // ... rest of function
}

function showActionDetail(actionId, workflowId) {
    // ... existing code ...

    const pageHeader = document.querySelector('#action-detail-view .page-header');
    const backButton = createBackButton('Actions', '#/actions');
    pageHeader.insertBefore(backButton, pageHeader.firstChild);

    // ... rest of function
}
```

**CSS:**
```css
/* css/components/buttons.css - Add back button styles */

.back-button {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    margin-bottom: 16px;
    font-size: 0.875rem;
    color: var(--accent);
    background: transparent;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    cursor: pointer;
    transition: all 0.2s;
}

.back-button:hover {
    background: var(--accent-light);
    border-color: var(--accent);
    transform: translateX(-2px);
}

.back-button svg {
    flex-shrink: 0;
}
```

**Files:**
- `js/app.js` (add createBackButton function and use in detail views)
- `css/components/buttons.css`

---

### PHASE 2: UX IMPROVEMENTS

#### Task 8: Add Loading Skeletons
**Problem:** Users see blank screens while data loads.

**Solution:**
```html
<!-- index.html - Add loading skeleton template -->
<template id="loading-skeleton-template">
    <div class="skeleton-card">
        <div class="skeleton-header">
            <div class="skeleton-line skeleton-title"></div>
            <div class="skeleton-line skeleton-badge"></div>
        </div>
        <div class="skeleton-line skeleton-text"></div>
        <div class="skeleton-line skeleton-text short"></div>
        <div class="skeleton-footer">
            <div class="skeleton-line skeleton-meta"></div>
            <div class="skeleton-line skeleton-meta"></div>
        </div>
    </div>
</template>
```

```javascript
// js/app.js - Add loading skeleton functions

function showLoadingSkeleton(containerId, count = 6) {
    const container = document.getElementById(containerId);
    if (!container) return;

    container.innerHTML = '';
    container.className = 'workflows-grid';

    const template = document.getElementById('loading-skeleton-template');
    for (let i = 0; i < count; i++) {
        const clone = template.content.cloneNode(true);
        container.appendChild(clone);
    }
}

function hideLoadingSkeleton(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '';
}

// Use in data fetching
async function showAllWorkflows() {
    // Show skeleton while loading
    showLoadingSkeleton('workflows-list-grid');

    // ... fetch/load data ...

    // Hide skeleton and show real content
    hideLoadingSkeleton('workflows-list-grid');
    renderWorkflowsView(workflows, 'workflows-list-grid', savedView);
}
```

```css
/* css/components/loading.css - Create new file */

.skeleton-card {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    padding: 20px;
    animation: pulse 1.5s ease-in-out infinite;
}

.skeleton-line {
    height: 12px;
    background: linear-gradient(
        90deg,
        var(--border) 25%,
        var(--border-light) 50%,
        var(--border) 75%
    );
    background-size: 200% 100%;
    border-radius: 4px;
    animation: shimmer 1.5s ease-in-out infinite;
}

.skeleton-title {
    height: 20px;
    width: 60%;
    margin-bottom: 12px;
}

.skeleton-badge {
    height: 20px;
    width: 80px;
}

.skeleton-text {
    margin-bottom: 8px;
}

.skeleton-text.short {
    width: 80%;
}

.skeleton-meta {
    width: 100px;
    margin-right: 16px;
}

.skeleton-header {
    display: flex;
    justify-content: space-between;
    margin-bottom: 16px;
}

.skeleton-footer {
    display: flex;
    margin-top: 16px;
}

@keyframes shimmer {
    0% {
        background-position: -200% 0;
    }
    100% {
        background-position: 200% 0;
    }
}

@keyframes pulse {
    0%, 100% {
        opacity: 1;
    }
    50% {
        opacity: 0.6;
    }
}
```

**Files:**
- `index.html` (add template)
- `js/app.js` (add loading functions)
- `css/components/loading.css` (new file)

---

#### Task 9: Add Empty States
**Problem:** When no data is available, users see blank spaces.

**Solution:**
```html
<!-- index.html - Add empty state template -->
<template id="empty-state-template">
    <div class="empty-state">
        <div class="empty-state-icon">
            <svg width="64" height="64" viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="32" cy="32" r="24"/>
                <path d="M32 20v16M32 44h.01"/>
            </svg>
        </div>
        <h3 class="empty-state-title"></h3>
        <p class="empty-state-message"></p>
        <button class="empty-state-action"></button>
    </div>
</template>
```

```javascript
// js/app.js - Add empty state function

function showEmptyState(containerId, config) {
    const container = document.getElementById(containerId);
    if (!container) return;

    container.innerHTML = '';

    const template = document.getElementById('empty-state-template');
    const clone = template.content.cloneNode(true);

    clone.querySelector('.empty-state-title').textContent = config.title;
    clone.querySelector('.empty-state-message').textContent = config.message;

    const actionButton = clone.querySelector('.empty-state-action');
    if (config.actionLabel && config.actionCallback) {
        actionButton.textContent = config.actionLabel;
        actionButton.style.display = 'inline-flex';
        actionButton.addEventListener('click', config.actionCallback);
    } else {
        actionButton.style.display = 'none';
    }

    container.appendChild(clone);
}

// Use when rendering
function renderWorkflowsView(workflows, containerId, viewType) {
    const container = document.getElementById(containerId);
    if (!container) return;

    if (workflows.length === 0) {
        showEmptyState(containerId, {
            title: 'No workflows found',
            message: 'Try adjusting your search or filters to find what you\'re looking for.',
            actionLabel: 'Clear Filters',
            actionCallback: () => workflowsFilterManager.clearAllFilters()
        });
        return;
    }

    // ... normal rendering
}
```

```css
/* css/components/empty-states.css - Create new file */

.empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 64px 32px;
    text-align: center;
    min-height: 400px;
}

.empty-state-icon {
    margin-bottom: 24px;
    color: var(--text-muted);
    opacity: 0.5;
}

.empty-state-title {
    font-size: 1.5rem;
    font-weight: 600;
    color: var(--text);
    margin: 0 0 12px 0;
}

.empty-state-message {
    font-size: 1rem;
    color: var(--text-muted);
    max-width: 400px;
    margin: 0 0 24px 0;
    line-height: 1.5;
}

.empty-state-action {
    padding: 10px 24px;
    font-size: 0.9375rem;
    font-weight: 500;
    color: white;
    background: var(--accent);
    border: none;
    border-radius: var(--radius-sm);
    cursor: pointer;
    transition: all 0.2s;
}

.empty-state-action:hover {
    background: var(--accent-dark);
    transform: translateY(-2px);
}
```

**Files:**
- `index.html` (add template)
- `js/app.js` (add showEmptyState function)
- `css/components/empty-states.css` (new file)

---

#### Task 10-23: Additional Tasks
For brevity, the remaining tasks follow similar patterns. Each task should:
1. Be implemented incrementally
2. Be tested in isolation
3. Follow the existing code patterns
4. Use the established CSS/JS structure

---

## 🚀 Implementation Order

### Week 1: Critical Accessibility Fixes
- [ ] Task 1: Fix H1 headings (30 min)
- [ ] Task 2: Add ARIA labels (1 hour)
- [ ] Task 3: Add input labels (1 hour)
- [ ] Task 4: Fix page titles (30 min)

### Week 2: Navigation Context
- [ ] Task 5: Workflow context badges (3 hours)
- [ ] Task 6: Breadcrumb navigation (4 hours)
- [ ] Task 7: Back buttons (2 hours)

### Week 3: UX Polish
- [ ] Task 8: Loading skeletons (3 hours)
- [ ] Task 9: Empty states (2 hours)
- [ ] Task 10: Tooltips (2 hours)
- [ ] Task 15: Filter chips (2 hours)

### Week 4: Enhanced Features
- [ ] Task 11: Primary action buttons (1 hour)
- [ ] Task 12: Workflow detail tabs (6 hours)
- [ ] Task 13: Cross-reference links (3 hours)
- [ ] Task 14: View All links (1 hour)

### Future Enhancements (Optional)
- [ ] Tasks 16-23: Nice-to-have features

---

## ✅ Testing Checklist

After completing each phase, verify:

### Phase 1 Verification
- [ ] Run Lighthouse accessibility audit - score should improve to 90+
- [ ] Test with screen reader (VoiceOver/NVDA)
- [ ] Verify page titles update correctly on navigation
- [ ] Check all H1 headings (should be exactly 1 per page)

### Phase 2 Verification
- [ ] Navigate from Actions → Workflow → Back to Actions
- [ ] Click workflow badge on action card
- [ ] Use breadcrumbs to navigate hierarchy
- [ ] Test loading states by throttling network

### Phase 3 Verification
- [ ] Search with no results shows empty state
- [ ] Filter chips display when filters active
- [ ] Tooltips appear on hover
- [ ] All interactive elements have hover states

---

## 📊 Success Metrics

Track these metrics before and after implementation:

| Metric | Before | Target | After |
|--------|--------|--------|-------|
| Lighthouse Accessibility Score | 0/100 | 90+/100 | |
| Navigation Health Score | 92/100 | 95+/100 | |
| Overall UX Score | 73/100 | 85+/100 | |
| H1 Headings per Page | 11 | 1 | |
| Unlabeled Buttons | 15 | 0 | |
| Unlabeled Inputs | 7 | 0 | |

---

## 🔗 Related Files

- `UX_NAVIGATION_ANALYSIS.md` - Detailed navigation test results
- `UX_PRODUCTION_READINESS.md` - Full production readiness report
- `test-ux-comprehensive.js` - Automated UX testing script
- `test-ux-navigation.js` - Navigation testing script

---

## 💡 Tips for Implementation

1. **Start with Phase 1** - These are critical for production
2. **Test incrementally** - Don't implement all at once
3. **Use git branches** - Create feature branches for each phase
4. **Mobile test** - Verify responsive design after each task
5. **Document changes** - Update this file as you complete tasks
6. **Run automated tests** - Use the test scripts after major changes

---

**Next Steps:** Start with Task 1 (Fix H1 headings) - it's the quickest win!
