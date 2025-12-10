// QanaLabs Workflow Documentation App
// Main application logic

// Utility functions
function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}

function convertToYAML(obj, indent = 0) {
    const spaces = '  '.repeat(indent);
    let yaml = '';

    for (const [key, value] of Object.entries(obj)) {
        if (value === null || value === undefined) {
            yaml += `${spaces}${key}: null\n`;
        } else if (Array.isArray(value)) {
            if (value.length === 0) {
                yaml += `${spaces}${key}: []\n`;
            } else if (typeof value[0] === 'object' && value[0] !== null) {
                yaml += `${spaces}${key}:\n`;
                value.forEach(item => {
                    yaml += `${spaces}- `;
                    if (typeof item === 'object') {
                        const itemYaml = convertToYAML(item, indent + 1);
                        yaml += itemYaml.substring((indent + 1) * 2);
                    } else {
                        yaml += `${item}\n`;
                    }
                });
            } else {
                yaml += `${spaces}${key}: [${value.join(', ')}]\n`;
            }
        } else if (typeof value === 'object') {
            yaml += `${spaces}${key}:\n`;
            yaml += convertToYAML(value, indent + 1);
        } else if (typeof value === 'string' && (value.includes('\n') || value.includes(':') || value.length > 80)) {
            yaml += `${spaces}${key}: |\n`;
            value.split('\n').forEach(line => {
                yaml += `${spaces}  ${line}\n`;
            });
        } else if (typeof value === 'string') {
            yaml += `${spaces}${key}: "${value}"\n`;
        } else {
            yaml += `${spaces}${key}: ${value}\n`;
        }
    }

    return yaml;
}

// State
const state = {
    currentView: 'overview',
    currentWorkflow: null,
    currentAction: null,
    currentTab: 'details',
    dagZoom: 1,
    dagTransform: { x: 0, y: 0 },
    dagLayout: 'horizontal', // 'vertical' or 'horizontal'
    navigationContext: null // Tracks where the user came from: 'workflow', 'actions-list', 'sidebar', etc.
};

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
    // Check if data is already loaded
    if (catalog && runs) {
        initializeApp();
    }
    // If not, initializeApp will be called from the data loading script
});

function initializeApp() {
    // Make sure data is loaded
    if (!catalog || !runs) {
        console.warn('Data not loaded yet, waiting...');
        return;
    }

    renderSidebar();
    renderOverview();
    setupEventListeners();
    setupSearch();
}

// ============================================
// SIDEBAR RENDERING
// ============================================

function renderSidebar() {
    const workflows = Object.values(catalog.workflows);

    // Update counts
    document.getElementById('workflow-count').textContent = catalog.stats.total_workflows;
    document.getElementById('action-count').textContent = catalog.stats.total_actions;
    document.getElementById('prompt-count').textContent = catalog.stats.total_prompts || 0;
    document.getElementById('schema-count').textContent = catalog.stats.total_schemas || 0;

    // Render workflows list
    const workflowsList = document.getElementById('workflows-list');
    workflowsList.innerHTML = '';

    workflows.forEach(workflow => {
        const li = document.createElement('li');
        const link = document.createElement('a');
        link.href = '#';
        link.className = 'nav-link';
        link.textContent = workflow.name;
        link.dataset.workflow = workflow.id;
        link.addEventListener('click', (e) => {
            e.preventDefault();
            showWorkflow(workflow.id);
        });
        li.appendChild(link);
        workflowsList.appendChild(li);
    });

    // Render all actions list
    const actionsList = document.getElementById('actions-list');
    actionsList.innerHTML = '';

    const allActions = [];
    workflows.forEach(workflow => {
        Object.values(workflow.actions).forEach(action => {
            allActions.push({ ...action, workflowId: workflow.id, workflowName: workflow.name });
        });
    });

    // Sort actions alphabetically
    allActions.sort((a, b) => a.name.localeCompare(b.name));

    // Get unique actions (by name)
    const uniqueActions = new Map();
    allActions.forEach(action => {
        if (!uniqueActions.has(action.name)) {
            uniqueActions.set(action.name, action);
        }
    });

    Array.from(uniqueActions.values()).forEach(action => {
        const li = document.createElement('li');
        const link = document.createElement('a');
        link.href = '#';
        link.className = 'nav-link';
        link.textContent = action.name;
        link.addEventListener('click', (e) => {
            e.preventDefault();
            showAction(action.name);
        });
        li.appendChild(link);
        actionsList.appendChild(li);
    });

    // Render prompts list
    const promptsList = document.getElementById('prompts-list');
    if (promptsList && catalog.prompts) {
        promptsList.innerHTML = '';
        const promptsArray = Object.values(catalog.prompts);
        promptsArray.sort((a, b) => a.name.localeCompare(b.name));

        promptsArray.forEach(prompt => {
            const li = document.createElement('li');
            const link = document.createElement('a');
            link.href = '#';
            link.className = 'nav-link';
            link.innerHTML = `${prompt.name} <span style="font-size: 0.7rem; color: var(--text-muted);">(${prompt.workflow})</span>`;
            link.addEventListener('click', (e) => {
                e.preventDefault();
                showPrompt(prompt.id);
            });
            li.appendChild(link);
            promptsList.appendChild(li);
        });
    }

    // Render schemas list
    const schemasList = document.getElementById('schemas-list');
    if (schemasList && catalog.schemas) {
        schemasList.innerHTML = '';
        const schemasArray = Object.values(catalog.schemas);
        schemasArray.sort((a, b) => a.name.localeCompare(b.name));

        schemasArray.forEach(schema => {
            const li = document.createElement('li');
            const link = document.createElement('a');
            link.href = '#';
            link.className = 'nav-link';
            link.textContent = schema.name;
            link.addEventListener('click', (e) => {
                e.preventDefault();
                showSchema(schema.id);
            });
            li.appendChild(link);
            schemasList.appendChild(li);
        });
    }

    // Setup collapsible sections with navigation
    document.querySelectorAll('.nav-header.clickable').forEach(header => {
        header.addEventListener('click', (e) => {
            const section = header.dataset.section;

            // Navigate to appropriate view based on section
            if (section === 'workflows') {
                showAllWorkflows();
            } else if (section === 'actions') {
                showFilteredActions('all-actions');
            } else if (section === 'prompts') {
                showAllPrompts();
            } else if (section === 'schemas') {
                showAllSchemas();
            }

            // Also toggle collapsed state
            header.parentElement.classList.toggle('collapsed');
        });
    });
}

// ============================================
// OVERVIEW RENDERING
// ============================================

function renderOverview() {
    // Update stats
    document.getElementById('stat-workflows').textContent = catalog.stats.total_workflows;
    document.getElementById('stat-actions').textContent = catalog.stats.total_actions;
    document.getElementById('stat-llm').textContent = catalog.stats.llm_actions;
    document.getElementById('stat-tools').textContent = catalog.stats.tool_actions;
    document.getElementById('stat-prompts').textContent = catalog.stats.total_prompts || 0;
    document.getElementById('stat-schemas').textContent = catalog.stats.total_schemas || 0;

    // Render recent runs
    renderRecentRuns();
}

let runsFilterManager = null;

function renderRecentRuns() {
    const tbody = document.getElementById('recent-runs-table-body');
    if (!tbody) return;

    // Get all runs and enrich with workflow names
    const allRuns = runs.executions ? [...runs.executions].map(run => {
        // Get workflow name from catalog
        const workflow = catalog.workflows[run.workflow_id];
        return {
            ...run,
            workflow_name: workflow ? workflow.name : run.workflow_id,
            started_at_timestamp: new Date(run.started_at).getTime()
        };
    }) : [];

    // Get unique workflows and statuses for filters
    const uniqueWorkflows = [...new Set(allRuns.map(r => r.workflow_name))];
    const uniqueStatuses = [...new Set(allRuns.map(r => r.status))];

    // Initialize filter manager if not already initialized
    if (!runsFilterManager) {
        runsFilterManager = new FilterManager('runs', {
            defaultSort: { id: 'started-desc', label: 'Recent First', field: 'started_at_timestamp', direction: 'desc' },
            sortOptions: [
                { id: 'started-desc', label: 'Recent First', field: 'started_at_timestamp', direction: 'desc' },
                { id: 'started-asc', label: 'Oldest First', field: 'started_at_timestamp', direction: 'asc' },
                { id: 'duration-desc', label: 'Duration (Longest)', field: 'duration_seconds', direction: 'desc' },
                { id: 'duration-asc', label: 'Duration (Shortest)', field: 'duration_seconds', direction: 'asc' },
                { id: 'workflow-asc', label: 'Workflow (A-Z)', field: 'workflow_name', direction: 'asc' },
                { id: 'workflow-desc', label: 'Workflow (Z-A)', field: 'workflow_name', direction: 'desc' }
            ],
            filterGroups: [
                {
                    label: 'STATUS',
                    options: uniqueStatuses.map(status => ({
                        id: `status-${status}`,
                        label: status.charAt(0).toUpperCase() + status.slice(1)
                    }))
                },
                {
                    label: 'WORKFLOW',
                    options: uniqueWorkflows.map(workflow => ({
                        id: `workflow-${workflow}`,
                        label: workflow
                    }))
                }
            ],
            searchFields: ['workflow_name'],
            filterFunctions: {
                ...uniqueStatuses.reduce((acc, status) => ({
                    ...acc,
                    [`status-${status}`]: (run) => run.status === status
                }), {}),
                ...uniqueWorkflows.reduce((acc, workflow) => ({
                    ...acc,
                    [`workflow-${workflow}`]: (run) => run.workflow_name === workflow
                }), {})
            },
            onFilter: (filteredRuns) => {
                renderRecentRunsTable(filteredRuns.slice(0, 10));
            }
        });

        // Setup table header sorting
        setupTableSorting('runs');
    }

    // Set runs and apply filters
    runsFilterManager.setItems(allRuns);
}

function renderRecentRunsTable(runsToShow) {
    const tbody = document.getElementById('recent-runs-table-body');
    if (!tbody) return;

    tbody.innerHTML = '';

    if (runsToShow.length === 0) {
        const row = document.createElement('tr');
        row.innerHTML = '<td colspan="6" style="text-align: center; color: var(--text-subtle); padding: var(--space-8);">No runs match the current filters</td>';
        tbody.appendChild(row);
        return;
    }

    runsToShow.forEach(run => {
        const row = document.createElement('tr');
        row.style.cursor = 'pointer';
        row.addEventListener('click', () => {
            showWorkflow(run.workflow_id);
            // Switch to runs tab
            setTimeout(() => {
                const runsTab = document.querySelector('[data-tab="runs"]');
                if (runsTab) runsTab.click();
            }, 100);
        });

        const startedDate = new Date(run.started_at);
        const now = new Date();
        const diffMs = now - startedDate;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMs / 3600000);
        const diffDays = Math.floor(diffMs / 86400000);

        let timeAgo;
        if (diffMins < 1) timeAgo = 'Just now';
        else if (diffMins < 60) timeAgo = `${diffMins}m ago`;
        else if (diffHours < 24) timeAgo = `${diffHours}h ago`;
        else timeAgo = `${diffDays}d ago`;

        const durationText = formatDuration(run.duration_seconds);
        const actionsText = `${run.successful_actions}/${run.total_actions}`;

        row.innerHTML = `
            <td style="width: 30px;">
                <button class="expand-btn" onclick="toggleActionDetails(event, '${run.id}')"
                        style="border:none; background:none; cursor:pointer; padding:4px 8px;">
                    <span id="expand-icon-${run.id}">▶</span>
                </button>
            </td>
            <td><strong>${run.workflow_name}</strong></td>
            <td><span class="status-badge ${run.status}">${run.status}</span></td>
            <td class="timestamp">${timeAgo}</td>
            <td>${durationText}</td>
            <td>${actionsText}</td>
        `;

        tbody.appendChild(row);
    });
}

function toggleActionDetails(event, runId) {
    event.stopPropagation(); // Prevent row click from navigating

    const detailsRowId = `action-details-${runId}`;
    const existingRow = document.getElementById(detailsRowId);
    const icon = document.getElementById(`expand-icon-${runId}`);

    if (existingRow) {
        // Collapse
        existingRow.remove();
        icon.textContent = '▶';
    } else {
        // Expand
        const run = runs.executions.find(r => r.id === runId);
        if (!run || !run.actions) return;

        const currentRow = event.target.closest('tr');
        const detailsRow = document.createElement('tr');
        detailsRow.id = detailsRowId;
        detailsRow.innerHTML = `
            <td colspan="6" style="padding: 0; background: var(--bg-subtle);">
                ${renderActionDetails(run)}
            </td>
        `;

        currentRow.insertAdjacentElement('afterend', detailsRow);
        icon.textContent = '▼';
    }
}

function renderActionDetails(run) {
    const actions = Object.entries(run.actions || {});

    if (actions.length === 0) {
        return '<div style="padding: var(--space-4); text-align: center; color: var(--text-subtle);">No action details available</div>';
    }

    let html = `
        <div style="padding: var(--space-4); max-height: 400px; overflow-y: auto;">
            <table style="width: 100%; border-collapse: collapse;">
                <thead>
                    <tr style="border-bottom: 1px solid var(--border-subtle);">
                        <th style="text-align: left; padding: var(--space-2); font-size: 0.85rem; color: var(--text-subtle);">ACTION</th>
                        <th style="text-align: left; padding: var(--space-2); font-size: 0.85rem; color: var(--text-subtle);">TYPE</th>
                        <th style="text-align: left; padding: var(--space-2); font-size: 0.85rem; color: var(--text-subtle);">STATUS</th>
                        <th style="text-align: right; padding: var(--space-2); font-size: 0.85rem; color: var(--text-subtle);">DURATION</th>
                        <th style="text-align: right; padding: var(--space-2); font-size: 0.85rem; color: var(--text-subtle);">TOKENS</th>
                    </tr>
                </thead>
                <tbody>
    `;

    actions.forEach(([actionName, actionData]) => {
        const statusClass = actionData.status === 'success' ? 'SUCCESS' :
                          actionData.status === 'failed' ? 'FAILED' :
                          actionData.status === 'skipped' ? 'PAUSED' : '';

        const tokens = actionData.tokens && actionData.tokens.total_tokens
            ? `${(actionData.tokens.total_tokens / 1000).toFixed(1)}K`
            : 'N/A';

        const duration = actionData.duration_seconds
            ? `${actionData.duration_seconds.toFixed(2)}s`
            : 'N/A';

        const typeLabel = actionData.type === 'llm' ? 'LLM' : 'Tool';

        html += `
            <tr style="border-bottom: 1px solid var(--border-subtle);">
                <td style="padding: var(--space-2); font-family: var(--font-mono); font-size: 0.9rem;">${actionName}</td>
                <td style="padding: var(--space-2); font-size: 0.9rem;">${typeLabel}</td>
                <td style="padding: var(--space-2);"><span class="status-badge ${statusClass}">${actionData.status}</span></td>
                <td style="padding: var(--space-2); text-align: right; font-family: var(--font-mono); font-size: 0.9rem;">${duration}</td>
                <td style="padding: var(--space-2); text-align: right; font-family: var(--font-mono); font-size: 0.9rem;">${tokens}</td>
            </tr>
        `;
    });

    html += `
                </tbody>
            </table>
        </div>
    `;

    return html;
}

function setupTableSorting(viewId) {
    const headers = document.querySelectorAll(`#${viewId}-filter-bar ~ .recent-runs-container .sortable-header`);

    headers.forEach(header => {
        header.addEventListener('click', () => {
            const field = header.dataset.sortField;
            if (!field) return;

            // Determine current sort direction
            const isAsc = header.classList.contains('sorted-asc');
            const newDirection = isAsc ? 'desc' : 'asc';

            // Remove all sorted classes
            headers.forEach(h => h.classList.remove('sorted-asc', 'sorted-desc'));

            // Add new sorted class
            header.classList.add(`sorted-${newDirection}`);

            // Map field names to sort option IDs
            const fieldMap = {
                'workflow': `workflow-${newDirection}`,
                'status': null, // No direct sort for status
                'started': `started-${newDirection}`,
                'duration': `duration-${newDirection}`
            };

            const sortId = fieldMap[field];
            if (sortId && runsFilterManager) {
                const sortOption = runsFilterManager.options.sortOptions.find(opt => opt.id === sortId);
                if (sortOption) {
                    runsFilterManager.setSort(sortOption);
                }
            }
        });
    });
}

function formatDuration(seconds) {
    if (seconds < 60) return `${seconds}s`;
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}m ${secs}s`;
}

function renderWorkflowsView(workflows, containerId, viewType) {
    const container = document.getElementById(containerId);
    if (!container) return;

    container.innerHTML = '';

    if (viewType === 'list') {
        // Render table view
        const table = createWorkflowsTable(workflows);
        container.appendChild(table);
        container.className = 'workflows-table-container';
    } else {
        // Render grid view with cards
        container.className = 'workflows-grid';
        workflows.forEach(workflow => {
            const card = createWorkflowCard(workflow);
            container.appendChild(card);
        });
    }
}

function createWorkflowsTable(workflows) {
    const table = document.createElement('table');
    table.className = 'workflows-table';

    // Create table header
    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    headerRow.innerHTML = `
        <th>Name</th>
        <th>Description</th>
        <th>Version</th>
        <th>Actions</th>
    `;
    thead.appendChild(headerRow);
    table.appendChild(thead);

    // Create table body
    const tbody = document.createElement('tbody');
    workflows.forEach(workflow => {
        const row = createWorkflowTableRow(workflow);
        tbody.appendChild(row);
    });
    table.appendChild(tbody);

    return table;
}

function createWorkflowTableRow(workflow) {
    const row = document.createElement('tr');
    row.style.cursor = 'pointer';
    row.addEventListener('click', () => showWorkflow(workflow.id));

    const actionCount = Object.keys(workflow.actions).length;
    const llmCount = Object.values(workflow.actions).filter(a => a.type === 'llm').length;
    const toolCount = Object.values(workflow.actions).filter(a => a.type === 'tool').length;

    row.innerHTML = `
        <td class="workflow-name">${workflow.name}</td>
        <td class="workflow-description">${workflow.description || 'No description'}</td>
        <td><span class="workflow-version-badge">v${workflow.version}</span></td>
        <td class="workflow-meta">${actionCount} total · ${llmCount} LLM · ${toolCount} tools</td>
    `;

    return row;
}

function createWorkflowCard(workflow) {
    const card = document.createElement('div');
    card.className = 'workflow-card';
    card.addEventListener('click', () => showWorkflow(workflow.id));

    const actionCount = Object.keys(workflow.actions).length;
    const llmCount = Object.values(workflow.actions).filter(a => a.type === 'llm').length;
    const toolCount = Object.values(workflow.actions).filter(a => a.type === 'tool').length;

    card.innerHTML = `
        <div class="workflow-card-header">
            <div>
                <h3>${workflow.name}</h3>
            </div>
            <span class="workflow-version">v${workflow.version}</span>
        </div>
        <p>${workflow.description || 'No description'}</p>
        <div class="workflow-meta">
            <span>${actionCount} actions</span>
            <span>${llmCount} LLM</span>
            <span>${toolCount} tools</span>
        </div>
    `;

    return card;
}

function createActionCard(action, workflowName, workflowId) {
    const card = document.createElement('div');
    card.className = 'workflow-card';
    card.addEventListener('click', () => showAction(action.name));

    const depsCount = action.dependencies.length;
    const depsText = depsCount === 0 ? 'No dependencies' : `${depsCount} ${depsCount === 1 ? 'dependency' : 'dependencies'}`;

    card.innerHTML = `
        <div class="workflow-card-header">
            <div>
                <h3>${action.name}</h3>
            </div>
            <span class="action-badge ${action.type}">${action.type}</span>
        </div>
        <p>${action.intent || 'No description'}</p>
        <div class="workflow-meta">
            <span>${workflowName}</span>
            <span>${depsText}</span>
        </div>
    `;

    return card;
}

// ============================================
// ALL WORKFLOWS LIST VIEW
// ============================================

let workflowsFilterManager = null;

function showAllWorkflows() {
    state.currentView = 'workflows-list';
    updateNavigation();
    switchView('workflows-list-view');

    const workflows = Object.values(catalog.workflows);
    const totalWorkflows = workflows.length;

    // Update header
    document.getElementById('workflows-list-subtitle').textContent = `Browse all ${totalWorkflows} workflows in the catalog`;
    document.getElementById('workflows-list-heading').textContent = `${totalWorkflows} Workflows`;

    // Restore saved view preference for workflows list
    const savedView = localStorage.getItem('workflowsListView') || 'grid';

    // Initialize filter manager if not already initialized
    if (!workflowsFilterManager) {
        workflowsFilterManager = new FilterManager('workflows', {
            defaultSort: { id: 'name-asc', label: 'Name (A-Z)', field: 'name', direction: 'asc' },
            sortOptions: [
                { id: 'name-asc', label: 'Name (A-Z)', field: 'name', direction: 'asc' },
                { id: 'name-desc', label: 'Name (Z-A)', field: 'name', direction: 'desc' },
                { id: 'version-desc', label: 'Version (Newest)', field: 'version', direction: 'desc' },
                { id: 'version-asc', label: 'Version (Oldest)', field: 'version', direction: 'asc' },
                { id: 'actions-desc', label: 'Actions (Most)', field: 'actionCount', direction: 'desc' },
                { id: 'actions-asc', label: 'Actions (Least)', field: 'actionCount', direction: 'asc' }
            ],
            filterGroups: [
                {
                    label: 'TYPE',
                    options: [
                        { id: 'has-llm', label: 'Has LLM Actions' },
                        { id: 'has-tools', label: 'Has Tool Actions' }
                    ]
                }
            ],
            searchFields: ['name', 'description'],
            filterFunctions: {
                'has-llm': (workflow) => {
                    const llmCount = Object.values(workflow.actions).filter(a => a.type === 'llm').length;
                    return llmCount > 0;
                },
                'has-tools': (workflow) => {
                    const toolCount = Object.values(workflow.actions).filter(a => a.type === 'tool').length;
                    return toolCount > 0;
                }
            },
            onFilter: (filteredWorkflows) => {
                // Add action count to workflows for sorting
                const workflowsWithCount = filteredWorkflows.map(w => ({
                    ...w,
                    actionCount: Object.keys(w.actions).length
                }));

                // Render filtered workflows
                renderWorkflowsView(workflowsWithCount, 'workflows-list-grid', savedView);

                // Update heading with count
                document.getElementById('workflows-list-heading').textContent = `${filteredWorkflows.length} Workflows`;
            }
        });
    }

    // Set workflows and apply filters
    const workflowsWithCount = workflows.map(w => ({
        ...w,
        actionCount: Object.keys(w.actions).length
    }));
    workflowsFilterManager.setItems(workflowsWithCount);

    // Update toggle buttons
    const container = document.getElementById('workflows-list-grid').closest('.content-view');
    if (container) {
        const gridBtn = container.querySelector('[data-view="grid"][data-target="workflows-list"]');
        const listBtn = container.querySelector('[data-view="list"][data-target="workflows-list"]');
        if (gridBtn && listBtn) {
            if (savedView === 'list') {
                gridBtn.classList.remove('active');
                listBtn.classList.add('active');
            } else {
                gridBtn.classList.add('active');
                listBtn.classList.remove('active');
            }
        }
    }
}

// ============================================
// ALL PROMPTS LIST VIEW
// ============================================

function showAllPrompts() {
    state.currentView = 'prompts-list';
    updateNavigation();
    switchView('prompts-list-view');

    const prompts = Object.values(catalog.prompts || {});
    const totalPrompts = prompts.length;

    // Update header
    document.getElementById('prompts-list-subtitle').textContent = `Browse all ${totalPrompts} prompts in the catalog`;

    // Render prompt cards
    const grid = document.getElementById('prompts-list-grid');
    grid.innerHTML = '';

    prompts.sort((a, b) => a.name.localeCompare(b.name));

    prompts.forEach(prompt => {
        const card = createPromptCard(prompt);
        grid.appendChild(card);
    });
}

function createPromptCard(prompt) {
    const card = document.createElement('div');
    card.className = 'workflow-card';
    card.style.cursor = 'pointer';
    card.addEventListener('click', () => showPrompt(prompt.id));

    card.innerHTML = `
        <div class="workflow-card-header">
            <h3>${prompt.name}</h3>
            <span class="badge" style="background: #7b61ff; color: white; font-size: 0.75rem; padding: 0.25rem 0.5rem; border-radius: 4px;">Prompt</span>
        </div>
        <p class="workflow-description">${prompt.preview}</p>
        <div class="workflow-meta">
            <span><strong>Workflow:</strong> ${prompt.workflow}</span>
            ${prompt.variables.length > 0 ? `<span><strong>Variables:</strong> ${prompt.variable_count}</span>` : ''}
        </div>
    `;

    return card;
}

// ============================================
// ALL SCHEMAS LIST VIEW
// ============================================

function showAllSchemas() {
    state.currentView = 'schemas-list';
    updateNavigation();
    switchView('schemas-list-view');

    const schemas = Object.values(catalog.schemas || {});
    const totalSchemas = schemas.length;

    // Update header
    document.getElementById('schemas-list-subtitle').textContent = `Browse all ${totalSchemas} schemas in the catalog`;

    // Render schema cards
    const grid = document.getElementById('schemas-list-grid');
    grid.innerHTML = '';

    schemas.sort((a, b) => a.name.localeCompare(b.name));

    schemas.forEach(schema => {
        const card = createSchemaCard(schema);
        grid.appendChild(card);
    });
}

function createSchemaCard(schema) {
    const card = document.createElement('div');
    card.className = 'workflow-card';
    card.style.cursor = 'pointer';
    card.addEventListener('click', () => showSchema(schema.id));

    card.innerHTML = `
        <div class="workflow-card-header">
            <h3>${schema.name}</h3>
            <span class="badge" style="background: #059669; color: white; font-size: 0.75rem; padding: 0.25rem 0.5rem; border-radius: 4px;">Schema</span>
        </div>
        <p class="workflow-description">${schema.preview}</p>
        <div class="workflow-meta">
            <span><strong>Type:</strong> ${schema.type}</span>
        </div>
    `;

    return card;
}

// ============================================
// ALL RUNS LIST VIEW
// ============================================

let runsListFilterManager = null;

function showAllRuns() {
    state.currentView = 'runs-list';
    updateNavigation();
    switchView('runs-list-view');

    // Get all runs and enrich with workflow names
    const allRuns = runs.executions ? [...runs.executions].map(run => {
        const workflow = catalog.workflows[run.workflow_id];
        return {
            ...run,
            workflow_name: workflow ? workflow.name : run.workflow_id,
            started_at_timestamp: new Date(run.started_at).getTime()
        };
    }) : [];

    const totalRuns = allRuns.length;

    // Update header
    document.getElementById('runs-list-subtitle').textContent = `Browse all ${totalRuns} workflow executions`;

    // Get unique workflows and statuses for filters
    const uniqueWorkflows = [...new Set(allRuns.map(r => r.workflow_name))];
    const uniqueStatuses = [...new Set(allRuns.map(r => r.status))];

    // Initialize filter manager if not already initialized
    if (!runsListFilterManager) {
        runsListFilterManager = new FilterManager('runs-list', {
            defaultSort: { id: 'started-desc', label: 'Recent First', field: 'started_at_timestamp', direction: 'desc' },
            sortOptions: [
                { id: 'started-desc', label: 'Recent First', field: 'started_at_timestamp', direction: 'desc' },
                { id: 'started-asc', label: 'Oldest First', field: 'started_at_timestamp', direction: 'asc' },
                { id: 'duration-desc', label: 'Duration (Longest)', field: 'duration_seconds', direction: 'desc' },
                { id: 'duration-asc', label: 'Duration (Shortest)', field: 'duration_seconds', direction: 'asc' },
                { id: 'workflow-asc', label: 'Workflow (A-Z)', field: 'workflow_name', direction: 'asc' },
                { id: 'workflow-desc', label: 'Workflow (Z-A)', field: 'workflow_name', direction: 'desc' }
            ],
            filterGroups: [
                {
                    label: 'STATUS',
                    options: uniqueStatuses.map(status => ({
                        id: `status-${status}`,
                        label: status.charAt(0).toUpperCase() + status.slice(1)
                    }))
                },
                {
                    label: 'WORKFLOW',
                    options: uniqueWorkflows.map(workflow => ({
                        id: `workflow-${workflow}`,
                        label: workflow
                    }))
                }
            ],
            searchFields: ['workflow_name'],
            filterFunctions: {
                ...uniqueStatuses.reduce((acc, status) => ({
                    ...acc,
                    [`status-${status}`]: (run) => run.status === status
                }), {}),
                ...uniqueWorkflows.reduce((acc, workflow) => ({
                    ...acc,
                    [`workflow-${workflow}`]: (run) => run.workflow_name === workflow
                }), {})
            },
            onFilter: (filteredRuns) => {
                renderRunsListTable(filteredRuns);
            }
        });

        // Setup table header sorting
        setupTableSorting('runs-list');
    }

    // Set runs and apply filters
    runsListFilterManager.setItems(allRuns);
}

function renderRunsListTable(runsToShow) {
    const tbody = document.getElementById('runs-list-table-body');
    if (!tbody) return;

    tbody.innerHTML = '';

    if (runsToShow.length === 0) {
        const row = document.createElement('tr');
        row.innerHTML = '<td colspan="6" style="text-align: center; color: var(--text-subtle); padding: var(--space-8);">No runs match the current filters</td>';
        tbody.appendChild(row);
        return;
    }

    runsToShow.forEach(run => {
        const row = document.createElement('tr');
        row.style.cursor = 'pointer';
        row.addEventListener('click', () => {
            showWorkflow(run.workflow_id);
            setTimeout(() => {
                const runsTab = document.querySelector('[data-tab="runs"]');
                if (runsTab) runsTab.click();
            }, 100);
        });

        const startedDate = new Date(run.started_at);
        const now = new Date();
        const diffMs = now - startedDate;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMs / 3600000);
        const diffDays = Math.floor(diffMs / 86400000);

        let timeAgo;
        if (diffMins < 1) timeAgo = 'Just now';
        else if (diffMins < 60) timeAgo = `${diffMins}m ago`;
        else if (diffHours < 24) timeAgo = `${diffHours}h ago`;
        else timeAgo = `${diffDays}d ago`;

        const durationText = formatDuration(run.duration_seconds);
        const actionsText = `${run.successful_actions}/${run.total_actions}`;

        row.innerHTML = `
            <td style="width: 30px;">
                <button class="expand-btn" onclick="toggleActionDetails(event, '${run.id}')"
                        style="border:none; background:none; cursor:pointer; padding:4px 8px;">
                    <span id="expand-icon-${run.id}">▶</span>
                </button>
            </td>
            <td><strong>${run.workflow_name}</strong></td>
            <td><span class="status-badge ${run.status}">${run.status}</span></td>
            <td class="timestamp">${timeAgo}</td>
            <td>${durationText}</td>
            <td>${actionsText}</td>
        `;

        tbody.appendChild(row);
    });
}

// ============================================
// FILTERED ACTIONS LIST VIEW
// ============================================

function showFilteredActions(filterType) {
    state.currentView = 'actions-list';
    updateNavigation();
    switchView('actions-list-view');

    // Gather all actions from all workflows
    const allActions = [];
    Object.values(catalog.workflows).forEach(workflow => {
        Object.values(workflow.actions).forEach(action => {
            allActions.push({
                ...action,
                workflowId: workflow.id,
                workflowName: workflow.name
            });
        });
    });

    // Filter actions based on type
    let filteredActions = allActions;
    let title, subtitle, heading;

    switch(filterType) {
        case 'all-actions':
            title = 'All Actions';
            subtitle = `Browse all ${allActions.length} actions across workflows`;
            heading = `${allActions.length} Actions`;
            break;
        case 'llm':
            filteredActions = allActions.filter(a => a.type === 'llm');
            title = 'LLM Actions';
            subtitle = `${filteredActions.length} actions that use language models`;
            heading = `${filteredActions.length} LLM Actions`;
            break;
        case 'tool':
            filteredActions = allActions.filter(a => a.type === 'tool');
            title = 'Tool Actions';
            subtitle = `${filteredActions.length} actions that use tool implementations`;
            heading = `${filteredActions.length} Tool Actions`;
            break;
        default:
            title = 'Actions';
            subtitle = 'Browse actions';
            heading = 'Actions';
    }

    // Update header
    document.getElementById('filter-type-breadcrumb').textContent = title;
    document.getElementById('filter-type-title').textContent = title;
    document.getElementById('filter-type-subtitle').textContent = subtitle;
    document.getElementById('actions-list-heading').textContent = heading;

    // Render action cards
    const grid = document.getElementById('actions-filtered-grid');
    grid.innerHTML = '';

    filteredActions.forEach(action => {
        const card = createActionCard(action, action.workflowName, action.workflowId);
        grid.appendChild(card);
    });

    // Restore saved view preference for actions
    const savedView = localStorage.getItem('actionsView');
    if (savedView === 'list') {
        grid.classList.remove('workflows-grid');
        grid.classList.add('workflows-list');
    }
}

// ============================================
// WORKFLOW VIEW
// ============================================

function showWorkflow(workflowId) {
    const workflow = catalog.workflows[workflowId];
    if (!workflow) return;

    state.currentWorkflow = workflowId;
    state.currentView = 'workflow';
    state.currentTab = 'details';

    // Update navigation
    updateNavigation();
    switchView('workflow-view');

    // Update header
    document.getElementById('workflow-name').textContent = workflow.name;
    document.getElementById('workflow-title').textContent = workflow.name;
    document.getElementById('workflow-description').textContent = workflow.description;

    // Render tabs
    renderFieldLineage(workflow);
    renderWorkflowDetails(workflow);
    renderWorkflowRuns(workflow);
}

function renderFieldLineage(workflow) {
    const container = document.getElementById('field-lineage-container');
    if (!container) {
        console.error('field-lineage-container not found!');
        return;
    }

    // Use the same proven DAG rendering approach
    // This will show the workflow with proper dark theme and working ReactFlow
    renderDAG(workflow, container);
}

function renderFieldLineageDAG(workflow, container) {
    // Use the transformer to create nodes and edges
    const { nodes, edges } = window.transformWorkflowToFieldLineage(workflow, 'TB');

    // Register the fieldActionNode type
    const nodeTypes = {
        fieldActionNode: window.FieldActionNode
    };

    // Create the React component
    const FieldLineageFlow = window.React.createElement(
        window.ReactFlow.ReactFlowProvider,
        null,
        window.React.createElement(FieldLineageFlowContent, {
            nodes,
            edges,
            nodeTypes,
            workflow
        })
    );

    // Render to container
    const root = window.ReactDOM.createRoot(container);
    root.render(FieldLineageFlow);
}

// Lineage Flow Content Component
function FieldLineageFlowContent({ nodes: initialNodes, edges: initialEdges, nodeTypes, workflow }) {
    const [nodes, setNodes, onNodesChange] = window.ReactFlow.useNodesState(initialNodes);
    const [allEdges] = window.React.useState(initialEdges); // Store all edges
    const [expandedNodes, setExpandedNodes] = window.React.useState(new Set());
    const [visibleEdges, setVisibleEdges] = window.React.useState([]);

    // Update visible edges when expanded nodes change
    window.React.useEffect(() => {
        if (expandedNodes.size === 0) {
            // No nodes expanded - show no field-to-field edges, only action-to-action
            setVisibleEdges([]);
        } else {
            // Show only edges connected to expanded nodes
            const filtered = allEdges.filter(edge => {
                const sourceExpanded = expandedNodes.has(edge.source);
                const targetExpanded = expandedNodes.has(edge.target);
                return sourceExpanded || targetExpanded;
            });
            setVisibleEdges(filtered);
        }
    }, [expandedNodes, allEdges]);

    // Handle node expansion changes
    const handleExpandChange = window.React.useCallback((nodeName, isExpanded) => {
        setExpandedNodes(prev => {
            const newSet = new Set(prev);
            if (isExpanded) {
                newSet.add(nodeName);
            } else {
                newSet.delete(nodeName);
            }
            return newSet;
        });
    }, []);

    // Add expand callback to nodes
    window.React.useEffect(() => {
        setNodes(currentNodes =>
            currentNodes.map(node => ({
                ...node,
                data: {
                    ...node.data,
                    onExpandChange: handleExpandChange
                }
            }))
        );
    }, [handleExpandChange, setNodes]);

    return window.React.createElement(
        'div',
        { style: { width: '100%', height: '100%' } },
        window.React.createElement(window.ReactFlow.ReactFlow, {
            nodes: nodes,
            edges: visibleEdges,
            onNodesChange: onNodesChange,
            nodeTypes: nodeTypes,
            fitView: true,
            minZoom: 0.1,
            maxZoom: 1.5,
            defaultEdgeOptions: {
                type: 'smoothstep',
                animated: false
            },
            style: {
                background: '#fafafa'
            }
        }, [
            window.React.createElement(window.ReactFlow.Background, {
                key: 'background',
                color: '#e5e7eb',
                gap: 16,
                size: 1
            }),
            window.React.createElement(window.ReactFlow.Controls, {
                key: 'controls',
                position: 'top-right',
                style: { margin: '16px' }
            }),
            window.React.createElement(window.ReactFlow.MiniMap, {
                key: 'minimap',
                nodeColor: (n) => {
                    if (!n.data) return '#9ca3af';
                    return n.data.type === 'llm' ? '#7b61ff' : '#059669';
                },
                nodeBorderRadius: 4,
                style: {
                    background: '#ffffff',
                    border: '1px solid #e5e7eb'
                }
            })
        ])
    );
}

function extractFieldMappings(actions) {
    const mappings = [];

    actions.forEach(action => {
        const raw = action.raw_yaml || {};
        const contextScope = raw.context_scope || {};

        // Extract input fields
        let inputFields = [];

        // From observe
        if (raw.observe && Array.isArray(raw.observe)) {
            inputFields = inputFields.concat(raw.observe);
        }

        // From context_scope.observe
        if (contextScope.observe && Array.isArray(contextScope.observe)) {
            inputFields = inputFields.concat(contextScope.observe);
        }

        // From context_scope.passthrough (these are both input and output)
        if (contextScope.passthrough && Array.isArray(contextScope.passthrough)) {
            inputFields = inputFields.concat(contextScope.passthrough);
        }

        // Remove duplicates
        inputFields = [...new Set(inputFields)];

        // Fallback: check for inputs array (catalog format)
        if (inputFields.length === 0 && action.inputs && Array.isArray(action.inputs)) {
            inputFields = action.inputs;
        }

        // Extract output fields from schema
        let outputFields = [];

        if (action.schema && action.schema.structure) {
            const schema = action.schema.structure;

            if (schema.type === 'object' && schema.properties) {
                outputFields = Object.keys(schema.properties);
            } else if (schema.type === 'array' && schema.items && schema.items.properties) {
                outputFields = Object.keys(schema.items.properties);
            } else if (typeof schema === 'object' && !schema.type) {
                // Inline schema format like {field1: "string", field2: "number"}
                outputFields = Object.keys(schema);
            }
        }

        // Fallback: check for output_fields array (catalog format)
        if (outputFields.length === 0 && action.output_fields && Array.isArray(action.output_fields)) {
            outputFields = action.output_fields.map(field => field.name);
        }

        // Add passthrough fields to outputs as well
        if (contextScope.passthrough && Array.isArray(contextScope.passthrough)) {
            outputFields = outputFields.concat(contextScope.passthrough);
        }

        // Remove duplicates
        outputFields = [...new Set(outputFields)];

        // Extract dropped fields
        let droppedFields = [];

        if (raw.drops && Array.isArray(raw.drops)) {
            droppedFields = droppedFields.concat(raw.drops);
        }

        if (contextScope.drop && Array.isArray(contextScope.drop)) {
            droppedFields = droppedFields.concat(contextScope.drop);
        }

        // Remove duplicates
        droppedFields = [...new Set(droppedFields)];

        mappings.push({
            actionName: action.name,
            type: action.type,
            inputFields: inputFields,
            outputFields: outputFields,
            droppedFields: droppedFields,
            dependencies: action.dependencies || []
        });
    });

    return mappings;
}

function renderWorkflowDetails(workflow) {
    const container = document.getElementById('workflow-details');
    if (!container) {
        console.error('workflow-details container not found!');
        return;
    }

    console.log('Rendering workflow details for:', workflow.name);
    container.innerHTML = '';

    const actionCount = Object.keys(workflow.actions).length;
    const llmCount = Object.values(workflow.actions).filter(a => a.type === 'llm').length;
    const toolCount = Object.values(workflow.actions).filter(a => a.type === 'tool').length;

    console.log('Action counts:', { actionCount, llmCount, toolCount });

    // Create a well-structured layout with proper sections
    const detailsHTML = `
        <!-- Overview Section -->
        <div class="detail-card full-width">
            <h3>Overview</h3>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: var(--space-4); margin-top: var(--space-4);">
                <div>
                    <div style="font-size: 0.875rem; color: var(--text-muted); margin-bottom: var(--space-1);">Version</div>
                    <div style="font-size: 1.25rem; font-weight: 600;">${workflow.version}</div>
                </div>
                <div>
                    <div style="font-size: 0.875rem; color: var(--text-muted); margin-bottom: var(--space-1);">Total Actions</div>
                    <div style="font-size: 1.25rem; font-weight: 600;">${actionCount}</div>
                </div>
                <div>
                    <div style="font-size: 0.875rem; color: var(--text-muted); margin-bottom: var(--space-1);">LLM Actions</div>
                    <div style="font-size: 1.25rem; font-weight: 600; color: #7c3aed;">${llmCount}</div>
                </div>
                <div>
                    <div style="font-size: 0.875rem; color: var(--text-muted); margin-bottom: var(--space-1);">Tool Actions</div>
                    <div style="font-size: 1.25rem; font-weight: 600; color: #059669;">${toolCount}</div>
                </div>
            </div>
        </div>

        <!-- Description Section -->
        <div class="detail-card full-width">
            <h3>Description</h3>
            <p style="margin-top: var(--space-4); line-height: 1.6;">${workflow.description || 'No description available'}</p>
        </div>

        <!-- Path Section -->
        <div class="detail-card full-width">
            <h3>Workflow Path</h3>
            <p style="margin-top: var(--space-4);"><code>${workflow.path}</code></p>
        </div>
    `;

    container.innerHTML = detailsHTML;

    // Add Actions section
    const actionsSection = document.createElement('div');
    actionsSection.className = 'detail-card full-width';
    actionsSection.style.marginTop = 'var(--space-6)';

    const actionsHeader = document.createElement('h3');
    actionsHeader.textContent = 'Actions';
    actionsSection.appendChild(actionsHeader);

    // Get actions array
    const actions = Object.values(workflow.actions);

    // Create table wrapper
    const tableWrapper = document.createElement('div');
    tableWrapper.style.overflowX = 'auto';
    tableWrapper.style.marginTop = 'var(--space-4)';

    const table = document.createElement('table');
    table.className = 'actions-table';

    // Header
    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    headerRow.innerHTML = `
        <th>Name</th>
        <th>Type</th>
        <th>Model/Implementation</th>
        <th>Intent</th>
        <th>Dependencies</th>
    `;
    thead.appendChild(headerRow);
    table.appendChild(thead);

    // Body
    const tbody = document.createElement('tbody');
    actions.forEach(action => {
        const row = document.createElement('tr');
        row.className = 'action-row';
        row.style.cursor = 'pointer';
        row.addEventListener('click', () => showAction(workflow.id, action.name));

        const depsCount = action.dependencies.length;
        const depsText = depsCount === 0 ? 'None' : `${depsCount} action${depsCount > 1 ? 's' : ''}`;

        // Get model or implementation info
        let modelInfo = '<span style="color: var(--text-subtle);">-</span>';
        if (action.type === 'llm' && action.model) {
            modelInfo = `<code style="font-size: 0.8125rem;">${action.model}</code>`;
        } else if (action.type === 'tool' && action.impl) {
            modelInfo = `<code style="font-size: 0.8125rem;">${action.impl}</code>`;
        }

        row.innerHTML = `
            <td><strong>${action.name}</strong></td>
            <td><span class="action-badge ${action.type}">${action.type}</span></td>
            <td>${modelInfo}</td>
            <td>${action.intent || '<span style="color: var(--text-subtle);">No description</span>'}</td>
            <td style="color: var(--text-muted);">${depsText}</td>
        `;
        tbody.appendChild(row);
    });
    table.appendChild(tbody);

    tableWrapper.appendChild(table);
    actionsSection.appendChild(tableWrapper);
    container.appendChild(actionsSection);
}

function renderWorkflowActions(workflow) {
    const container = document.getElementById('workflow-actions');
    container.innerHTML = '';

    // Get actions array
    const actions = Object.values(workflow.actions);

    // Add a summary header
    const summary = document.createElement('div');
    summary.style.marginBottom = 'var(--space-5)';
    summary.innerHTML = `
        <p style="color: var(--text-muted); font-size: 0.9375rem;">
            <strong>${actions.length}</strong> actions in this workflow
        </p>
    `;
    container.appendChild(summary);

    // Create wrapper for table
    const tableWrapper = document.createElement('div');
    tableWrapper.style.overflowX = 'auto';

    const table = document.createElement('table');
    table.className = 'actions-table';

    // Header
    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    headerRow.innerHTML = `
        <th>Name</th>
        <th>Type</th>
        <th>Model/Implementation</th>
        <th>Intent</th>
        <th>Dependencies</th>
    `;
    thead.appendChild(headerRow);
    table.appendChild(thead);

    // Body
    const tbody = document.createElement('tbody');
    actions.forEach(action => {
        const row = document.createElement('tr');
        row.className = 'action-row';
        row.style.cursor = 'pointer';
        row.addEventListener('click', () => showAction(workflow.id, action.name));

        const depsCount = action.dependencies.length;
        const depsText = depsCount === 0 ? 'None' : `${depsCount} action${depsCount > 1 ? 's' : ''}`;

        // Get model or implementation info
        let modelInfo = '<span style="color: var(--text-subtle);">-</span>';
        if (action.type === 'llm' && action.model) {
            modelInfo = `<code style="font-size: 0.8125rem;">${action.model}</code>`;
        } else if (action.type === 'tool' && action.impl) {
            modelInfo = `<code style="font-size: 0.8125rem;">${action.impl}</code>`;
        }

        row.innerHTML = `
            <td><strong>${action.name}</strong></td>
            <td><span class="action-badge ${action.type}">${action.type}</span></td>
            <td>${modelInfo}</td>
            <td>${action.intent || '<span style="color: var(--text-subtle);">No description</span>'}</td>
            <td style="color: var(--text-muted);">${depsText}</td>
        `;
        tbody.appendChild(row);
    });
    table.appendChild(tbody);

    tableWrapper.appendChild(table);
    container.appendChild(tableWrapper);
}

function renderWorkflowRuns(workflow) {
    // Check if runs data is available
    if (typeof runs === 'undefined') {
        console.warn('Runs data not available');
        return;
    }

    // Get workflow-specific metrics and runs
    const workflowMetrics = runs.workflow_metrics[workflow.id] || {
        total_runs: 0,
        successful_runs: 0,
        failed_runs: 0,
        success_rate: 0,
        avg_duration_seconds: 0,
        total_tokens: 0
    };

    const workflowRuns = runs.executions.filter(run => run.workflow_id === workflow.id);

    // Populate metrics cards
    document.getElementById('workflow-total-runs').textContent = workflowMetrics.total_runs;
    document.getElementById('workflow-success-rate').textContent =
        `${Math.round(workflowMetrics.success_rate * 100)}%`;
    document.getElementById('workflow-avg-duration').textContent =
        formatDuration(workflowMetrics.avg_duration_seconds);
    document.getElementById('workflow-total-cost').textContent =
        `${(workflowMetrics.total_tokens / 1000).toFixed(1)}K`;

    // Update progress bar
    const progressBar = document.getElementById('workflow-success-progress');
    progressBar.style.width = `${workflowMetrics.success_rate * 100}%`;
    progressBar.style.backgroundColor = workflowMetrics.success_rate >= 0.8 ?
        'var(--success)' : workflowMetrics.success_rate >= 0.5 ? '#f59e0b' : 'var(--error)';

    // Add trend indicators
    const runsTrend = document.getElementById('workflow-runs-trend');
    runsTrend.textContent = `${workflowMetrics.successful_runs} succeeded, ${workflowMetrics.failed_runs} failed`;
    runsTrend.style.fontSize = '0.75rem';
    runsTrend.style.color = 'var(--text-muted)';

    const costInfo = document.getElementById('workflow-cost-info');
    if (workflowMetrics.total_tokens) {
        costInfo.textContent = `${(workflowMetrics.total_tokens / 1000).toFixed(1)}K tokens`;
        costInfo.style.fontSize = '0.75rem';
        costInfo.style.color = 'var(--text-muted)';
    }

    // Render run timeline
    renderRunTimeline(workflowRuns);

    // Render runs table
    renderRunsTable(workflowRuns);
}

function renderRunTimeline(workflowRuns) {
    const container = document.getElementById('workflow-run-timeline');
    container.innerHTML = '';

    if (workflowRuns.length === 0) {
        container.innerHTML = '<div style="padding: 2rem; text-align: center; color: var(--text-muted);">No run history available</div>';
        return;
    }

    // Sort runs by date (most recent first)
    const sortedRuns = [...workflowRuns].sort((a, b) =>
        new Date(b.started_at) - new Date(a.started_at)
    );

    // Group runs by day for the timeline
    const runsByDay = {};
    sortedRuns.forEach(run => {
        const date = new Date(run.started_at);
        const dayKey = date.toISOString().split('T')[0];

        if (!runsByDay[dayKey]) {
            runsByDay[dayKey] = [];
        }
        runsByDay[dayKey].push(run);
    });

    // Get last 30 days
    const days = [];
    const today = new Date();
    for (let i = 29; i >= 0; i--) {
        const date = new Date(today);
        date.setDate(date.getDate() - i);
        days.push(date.toISOString().split('T')[0]);
    }

    // Create timeline visualization
    const timelineHTML = days.map(day => {
        const dayRuns = runsByDay[day] || [];
        const dayDate = new Date(day);
        const isToday = day === today.toISOString().split('T')[0];

        // Count statuses
        const successCount = dayRuns.filter(r => r.status === 'success').length;
        const failedCount = dayRuns.filter(r => r.status === 'failed').length;
        const runningCount = dayRuns.filter(r => r.status === 'running').length;

        const totalRuns = dayRuns.length;
        const hasRuns = totalRuns > 0;

        // Calculate bar height (max 100px)
        const maxHeight = 100;
        const barHeight = hasRuns ? Math.max(20, Math.min(maxHeight, totalRuns * 20)) : 5;

        // Determine bar color based on status
        let barColor = '#e5e7eb'; // default gray for no runs
        if (hasRuns) {
            if (failedCount > 0) {
                barColor = 'var(--error)';
            } else if (successCount > 0) {
                barColor = 'var(--success)';
            } else if (runningCount > 0) {
                barColor = '#f59e0b';
            }
        }

        return `
            <div class="timeline-bar ${!hasRuns ? 'empty' : ''}"
                 style="height: ${barHeight}px; background: ${barColor};"
                 title="${dayDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}: ${totalRuns} run${totalRuns !== 1 ? 's' : ''}${hasRuns ? ` (${successCount} success, ${failedCount} failed)` : ''}">
                ${isToday ? '<div style="position: absolute; bottom: -20px; left: 50%; transform: translateX(-50%); font-size: 0.65rem; color: var(--primary); font-weight: 600;">Today</div>' : ''}
                ${totalRuns > 0 && (dayDate.getDate() === 1 || dayDate.getDay() === 0) ?
                    `<div style="position: absolute; bottom: -20px; left: 50%; transform: translateX(-50%); font-size: 0.65rem; color: var(--text-muted); white-space: nowrap;">
                        ${dayDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                    </div>` : ''}
            </div>
        `;
    }).join('');

    container.innerHTML = timelineHTML;
}

function renderRunsTable(workflowRuns) {
    const tbody = document.getElementById('workflow-runs-table-body');
    tbody.innerHTML = '';

    if (workflowRuns.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; padding: 2rem; color: var(--text-muted);">No executions found</td></tr>';
        return;
    }

    // Sort runs by date (most recent first)
    const sortedRuns = [...workflowRuns].sort((a, b) =>
        new Date(b.started_at) - new Date(a.started_at)
    );

    // Show up to 10 most recent runs
    const recentRuns = sortedRuns.slice(0, 10);

    recentRuns.forEach(run => {
        const row = document.createElement('tr');

        // Get tokens for this run
        const runTokens = run.total_tokens || 0;
        const tokensDisplay = runTokens > 0 ? `${(runTokens / 1000).toFixed(1)}K` : 'N/A';

        // Format status badge
        const statusClass = run.status === 'success' ? 'success' :
                           run.status === 'failed' ? 'failed' : 'running';
        const statusBadge = `<span class="status-badge ${statusClass}">${run.status}</span>`;

        // Format actions summary
        const actionsSummary = `${run.successful_actions}/${run.total_actions}`;

        // Format date
        const startDate = new Date(run.started_at);
        const formattedDate = formatRelativeTime(startDate);

        row.innerHTML = `
            <td><code style="font-size: 0.75rem;">${run.id}</code></td>
            <td>${statusBadge}</td>
            <td>${formatDuration(run.duration_seconds)}</td>
            <td>${actionsSummary}</td>
            <td>${tokensDisplay}</td>
            <td>${formattedDate}</td>
        `;

        // Add click event to show run details
        row.style.cursor = 'pointer';
        row.addEventListener('click', () => showRunDetails(run));

        tbody.appendChild(row);
    });
}

function formatDuration(seconds) {
    if (seconds < 60) {
        return `${seconds}s`;
    } else if (seconds < 3600) {
        const minutes = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return `${minutes}m ${secs}s`;
    } else {
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        return `${hours}h ${minutes}m`;
    }
}

function formatRelativeTime(date) {
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) {
        return 'just now';
    } else if (diffMins < 60) {
        return `${diffMins}m ago`;
    } else if (diffHours < 24) {
        return `${diffHours}h ago`;
    } else if (diffDays < 7) {
        return `${diffDays}d ago`;
    } else {
        return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    }
}

function showRunDetails(run) {
    // For now, just log the run details
    // In the future, this could open a modal or navigate to a detailed view
    console.log('Run details:', run);

    // Show a simple alert with run information
    const details = `
Run ID: ${run.id}
Status: ${run.status}
Duration: ${formatDuration(run.duration_seconds)}
Actions: ${run.successful_actions}/${run.total_actions}
Started: ${new Date(run.started_at).toLocaleString()}
${run.error ? `\nError: ${run.error}` : ''}
    `.trim();

    alert(details);
}

// ============================================
// ACTION VIEW
// ============================================

function showAction(actionNameOrWorkflowId, actionName, navigationContext = null) {
    let action = null;
    let workflowsUsingAction = [];
    let fromWorkflowId = null;

    // If called with two parameters, it's the old way (from workflow context)
    if (actionName) {
        const workflow = catalog.workflows[actionNameOrWorkflowId];
        if (!workflow) return;
        action = workflow.actions[actionName];
        if (!action) return;
        workflowsUsingAction = [{ id: actionNameOrWorkflowId, name: workflow.name }];
        fromWorkflowId = actionNameOrWorkflowId;
        navigationContext = navigationContext || 'workflow';
    } else {
        // New way: just action name, find all workflows using it
        const searchName = actionNameOrWorkflowId;
        Object.values(catalog.workflows).forEach(workflow => {
            if (workflow.actions[searchName]) {
                action = workflow.actions[searchName];
                workflowsUsingAction.push({ id: workflow.id, name: workflow.name });
            }
        });
        if (!action) return;
        navigationContext = navigationContext || 'actions-list';
    }

    state.currentAction = action.name;
    state.currentView = 'action';
    state.currentWorkflow = fromWorkflowId;
    state.navigationContext = navigationContext;

    // Update navigation
    updateNavigation();
    switchView('action-view');

    // Update breadcrumb dynamically based on navigation context
    updateActionBreadcrumb(navigationContext, fromWorkflowId);

    // Update header
    document.getElementById('action-name').textContent = action.name;
    document.getElementById('action-title').textContent = action.name;

    const badge = document.getElementById('action-type-badge');
    badge.className = `action-badge ${action.type}`;
    badge.textContent = action.type;

    // Render details
    renderActionDetails(action, workflowsUsingAction);
}

function updateActionBreadcrumb(context, workflowId) {
    const breadcrumbContainer = document.querySelector('#action-view .breadcrumb');

    if (context === 'workflow' && workflowId) {
        // User came from a workflow
        const workflow = catalog.workflows[workflowId];
        breadcrumbContainer.innerHTML = `
            <a href="#" data-breadcrumb="workflows">Workflows</a>
            <span>/</span>
            <a href="#" data-workflow="${workflowId}">${workflow.name}</a>
            <span>/</span>
            <span id="action-name"></span>
        `;

        // Add click handler for workflow link
        const workflowLink = breadcrumbContainer.querySelector('[data-workflow]');
        workflowLink.addEventListener('click', (e) => {
            e.preventDefault();
            showWorkflow(workflowId);
        });
    } else {
        // User came from actions list or sidebar
        breadcrumbContainer.innerHTML = `
            <a href="#" data-view="overview">Overview</a>
            <span>/</span>
            <a href="#" data-breadcrumb="actions">All Actions</a>
            <span>/</span>
            <span id="action-name"></span>
        `;
    }
}

function renderActionDetails(action, workflowsUsingAction) {
    const container = document.getElementById('action-details');
    container.innerHTML = '';

    // Used in workflows section (show first for standalone context)
    if (workflowsUsingAction && workflowsUsingAction.length > 0) {
        const workflowsSection = document.createElement('div');
        workflowsSection.className = 'action-detail-section';
        workflowsSection.innerHTML = `
            <h2>Used in ${workflowsUsingAction.length} Workflow${workflowsUsingAction.length > 1 ? 's' : ''}</h2>
        `;

        const workflowsList = document.createElement('div');
        workflowsList.className = 'dependency-list';
        workflowsList.style.marginTop = 'var(--space-3)';

        workflowsUsingAction.forEach(workflow => {
            const tag = document.createElement('span');
            tag.className = 'dependency-tag';
            tag.textContent = workflow.name;
            tag.style.cursor = 'pointer';
            tag.addEventListener('click', () => showWorkflow(workflow.id));
            workflowsList.appendChild(tag);
        });

        workflowsSection.appendChild(workflowsList);
        container.appendChild(workflowsSection);
    }

    // Intent section
    const intentSection = document.createElement('div');
    intentSection.className = 'action-detail-section';
    intentSection.innerHTML = `
        <h2>Intent</h2>
        <p>${action.intent}</p>
    `;
    container.appendChild(intentSection);

    // Configuration section
    const configSection = document.createElement('div');
    configSection.className = 'action-detail-section';
    configSection.innerHTML = `<h2>Configuration</h2>`;

    if (action.type === 'llm') {
        const schemaRef = action.schema && typeof action.schema === 'object' ? action.schema.reference : action.schema;
        configSection.innerHTML += `
            <p><strong>Model:</strong> <code>${action.model}</code></p>
            ${schemaRef ? `<p><strong>Schema:</strong> <code>${schemaRef || 'inline'}</code></p>` : ''}
            ${action.prompt ? `<p><strong>Prompt:</strong> <code>${action.prompt.reference || 'inline'}</code></p>` : ''}
        `;
    } else {
        configSection.innerHTML += `
            <p><strong>Implementation:</strong> <code>${action.impl}</code></p>
            ${action.granularity ? `<p><strong>Granularity:</strong> ${action.granularity}</p>` : ''}
            ${action.tool_function ? `<p><strong>File:</strong> <code>${action.tool_function.file_path}</code></p>` : ''}
        `;
    }
    container.appendChild(configSection);

    // Tool function source code section (for tool actions)
    if (action.type === 'tool' && action.tool_function && action.tool_function.found) {
        const toolFunc = action.tool_function;

        // Docstring section
        if (toolFunc.docstring) {
            const docSection = document.createElement('div');
            docSection.className = 'action-detail-section';
            docSection.innerHTML = `
                <h2>Function Documentation</h2>
                <pre style="background: var(--bg-dark); padding: 1rem; border-radius: 4px; overflow-x: auto; font-size: 0.85rem; line-height: 1.4;">${escapeHtml(toolFunc.docstring)}</pre>
            `;
            container.appendChild(docSection);
        }

        // Function signature
        const sigSection = document.createElement('div');
        sigSection.className = 'action-detail-section';
        sigSection.innerHTML = `
            <h2>Function Signature</h2>
            <pre style="background: var(--bg-dark); padding: 1rem; border-radius: 4px; overflow-x: auto; font-size: 0.85rem; line-height: 1.4;"><code class="language-python">${escapeHtml(toolFunc.signature)}</code></pre>
        `;
        container.appendChild(sigSection);

        // Full source code
        const sourceSection = document.createElement('div');
        sourceSection.className = 'action-detail-section';
        sourceSection.innerHTML = `
            <h2>Source Code</h2>
            <pre style="background: var(--bg-dark); padding: 1rem; border-radius: 4px; overflow-x: auto; max-height: 600px; font-size: 0.85rem; line-height: 1.4;"><code class="language-python">${escapeHtml(toolFunc.source_code)}</code></pre>
        `;
        container.appendChild(sourceSection);
    }

    // Dependencies section (show immediately after config for visibility)
    if (action.dependencies && action.dependencies.length > 0) {
        const depsSection = document.createElement('div');
        depsSection.className = 'action-detail-section';
        depsSection.innerHTML = `<h2>Dependencies</h2>`;

        const depsList = document.createElement('div');
        depsList.className = 'dependency-list';

        action.dependencies.forEach(depName => {
            const tag = document.createElement('span');
            tag.className = 'dependency-tag';
            tag.textContent = depName;
            tag.addEventListener('click', () => showAction(depName));
            depsList.appendChild(tag);
        });

        depsSection.appendChild(depsList);
        container.appendChild(depsSection);
    }

    // Dependents section (actions that depend on this one) - across all workflows
    const dependents = [];
    if (workflowsUsingAction) {
        workflowsUsingAction.forEach(wf => {
            const workflow = catalog.workflows[wf.id];
            Object.values(workflow.actions).forEach(a => {
                if (a.dependencies && a.dependencies.includes(action.name)) {
                    dependents.push(a);
                }
            });
        });
    }

    if (dependents.length > 0) {
        const dependentsSection = document.createElement('div');
        dependentsSection.className = 'action-detail-section';
        dependentsSection.innerHTML = `<h2>Dependent Actions</h2>`;

        const depsList = document.createElement('div');
        depsList.className = 'dependency-list';

        dependents.forEach(dep => {
            const tag = document.createElement('span');
            tag.className = 'dependency-tag';
            tag.textContent = dep.name;
            tag.addEventListener('click', () => showAction(dep.name));
            depsList.appendChild(tag);
        });

        dependentsSection.appendChild(depsList);
        container.appendChild(dependentsSection);
    }

    // Guard section (for actions with conditional execution)
    if (action.guard) {
        const guardSection = document.createElement('div');
        guardSection.className = 'action-detail-section';
        guardSection.innerHTML = `
            <h2>Guard Condition</h2>
            <pre style="background: var(--bg-dark); padding: 1rem; border-radius: 4px; overflow-x: auto; font-size: 0.85rem; line-height: 1.4;">${escapeHtml(JSON.stringify(action.guard, null, 2))}</pre>
        `;
        container.appendChild(guardSection);
    }

    // Context scope section (for actions with data flow config)
    if (action.context_scope) {
        const contextSection = document.createElement('div');
        contextSection.className = 'action-detail-section';
        contextSection.innerHTML = `
            <h2>Context Scope</h2>
            <pre style="background: var(--bg-dark); padding: 1rem; border-radius: 4px; overflow-x: auto; max-height: 400px; font-size: 0.85rem; line-height: 1.4;">${escapeHtml(JSON.stringify(action.context_scope, null, 2))}</pre>
        `;
        container.appendChild(contextSection);
    }

    // Schema structure section (for LLM actions)
    if (action.type === 'llm' && action.schema && typeof action.schema === 'object' && action.schema.structure) {
        const schemaSection = document.createElement('div');
        schemaSection.className = 'action-detail-section';
        schemaSection.innerHTML = `
            <h2>Schema</h2>
            <pre style="background: var(--bg-dark); padding: 1rem; border-radius: 4px; overflow-x: auto; max-height: 400px; font-size: 0.85rem; line-height: 1.4;">${escapeHtml(JSON.stringify(action.schema.structure, null, 2))}</pre>
        `;
        container.appendChild(schemaSection);
    }

    // Prompt content section (for LLM actions)
    if (action.type === 'llm' && action.prompt && action.prompt.content) {
        const promptSection = document.createElement('div');
        promptSection.className = 'action-detail-section';
        promptSection.innerHTML = `
            <h2>Prompt</h2>
            <pre style="background: var(--bg-dark); padding: 1rem; border-radius: 4px; overflow-x: auto; max-height: 400px; font-size: 0.85rem; line-height: 1.4;">${escapeHtml(action.prompt.content)}</pre>
        `;
        container.appendChild(promptSection);
    }

    // Raw YAML section (show original config)
    if (action.raw_yaml) {
        const yamlSection = document.createElement('div');
        yamlSection.className = 'action-detail-section';

        // Convert object to YAML-like format
        const yamlString = convertToYAML(action.raw_yaml);

        yamlSection.innerHTML = `
            <h2>Raw YAML Configuration</h2>
            <pre style="background: var(--bg-dark); padding: 1rem; border-radius: 4px; overflow-x: auto; max-height: 400px; font-size: 0.85rem; line-height: 1.4;">${escapeHtml(yamlString)}</pre>
        `;
        container.appendChild(yamlSection);
    }
}

// ============================================
// PROMPT VIEW
// ============================================

function showPrompt(promptId) {
    const prompt = catalog.prompts[promptId];
    if (!prompt) return;

    state.currentView = 'prompt';

    // Update navigation
    updateNavigation();
    switchView('prompt-view');

    // Update header
    document.getElementById('prompt-name').textContent = prompt.name;
    document.getElementById('prompt-title').textContent = prompt.name;

    // Render details
    renderPromptDetails(prompt);
}

function renderPromptDetails(prompt) {
    const container = document.getElementById('prompt-details');
    container.innerHTML = '';

    // Metadata section
    const metaSection = document.createElement('div');
    metaSection.className = 'action-detail-section';
    metaSection.innerHTML = `
        <h2>Metadata</h2>
        <p><strong>Workflow:</strong> ${prompt.workflow}</p>
        <p><strong>File:</strong> <code>${prompt.file_path}</code></p>
        <p><strong>Lines:</strong> ${prompt.line_range[0]} - ${prompt.line_range[1]}</p>
        ${prompt.variables.length > 0 ? `<p><strong>Variables:</strong> ${prompt.variable_count}</p>` : ''}
    `;
    container.appendChild(metaSection);

    // Variables section
    if (prompt.variables && prompt.variables.length > 0) {
        const varsSection = document.createElement('div');
        varsSection.className = 'action-detail-section';
        varsSection.innerHTML = '<h2>Template Variables</h2>';

        const varsList = document.createElement('div');
        varsList.className = 'dependency-list';

        prompt.variables.forEach(varName => {
            const tag = document.createElement('span');
            tag.className = 'dependency-tag';
            tag.textContent = `{${varName}}`;
            tag.style.cursor = 'default';
            varsList.appendChild(tag);
        });

        varsSection.appendChild(varsList);
        container.appendChild(varsSection);
    }

    // Content section
    const contentSection = document.createElement('div');
    contentSection.className = 'action-detail-section';
    contentSection.innerHTML = `
        <h2>Prompt Content</h2>
        <pre style="background: var(--bg-dark); padding: 1rem; border-radius: 4px; overflow-x: auto; white-space: pre-wrap; font-size: 0.875rem; line-height: 1.6;">${escapeHtml(prompt.content)}</pre>
    `;
    container.appendChild(contentSection);
}

// ============================================
// SCHEMA VIEW
// ============================================

function showSchema(schemaId) {
    const schema = catalog.schemas[schemaId];
    if (!schema) return;

    state.currentView = 'schema';

    // Update navigation
    updateNavigation();
    switchView('schema-view');

    // Update header
    document.getElementById('schema-name').textContent = schema.name;
    document.getElementById('schema-title').textContent = schema.name;

    // Render details
    renderSchemaDetails(schema);
}

function renderSchemaDetails(schema) {
    const container = document.getElementById('schema-details');
    container.innerHTML = '';

    // Metadata section
    const metaSection = document.createElement('div');
    metaSection.className = 'action-detail-section';
    metaSection.innerHTML = `
        <h2>Metadata</h2>
        <p><strong>File:</strong> <code>${schema.file_path}</code></p>
        <p><strong>Type:</strong> ${schema.type}</p>
        <p><strong>Preview:</strong> ${schema.preview}</p>
    `;
    container.appendChild(metaSection);

    // Structure section
    const structureSection = document.createElement('div');
    structureSection.className = 'action-detail-section';
    structureSection.innerHTML = `
        <h2>Schema Structure</h2>
        <pre style="background: var(--bg-dark); padding: 1rem; border-radius: 4px; overflow-x: auto; font-size: 0.875rem; line-height: 1.6;">${escapeHtml(convertToYAML(schema.structure))}</pre>
    `;
    container.appendChild(structureSection);
}

// ============================================
// DAG VISUALIZATION (ReactFlow)
// ============================================

function renderDAG(workflow, container) {
    if (!container) {
        console.error('Container element not found for DAG rendering');
        return;
    }

    console.log('Rendering DAG for workflow:', workflow.name);
    console.log('Workflow data:', workflow);
    console.log('React available:', typeof React !== 'undefined');
    console.log('ReactDOM available:', typeof ReactDOM !== 'undefined');
    console.log('WorkflowDAG component available:', typeof window.WorkflowDAG !== 'undefined');

    // Clear container content
    container.innerHTML = '';

    // Check if dependencies are loaded
    if (typeof React === 'undefined' || typeof ReactDOM === 'undefined') {
        container.innerHTML = '<div style="padding: 20px; text-align: center; color: #666;">React libraries not loaded. Please refresh the page.</div>';
        console.error('React or ReactDOM not loaded');
        return;
    }

    if (typeof window.WorkflowDAG === 'undefined') {
        console.warn('WorkflowDAG component not available, using fallback renderer');
        renderSimpleDAG(workflow, container);
        return;
    }

    try {
        // Create React root and render WorkflowDAG component
        const root = ReactDOM.createRoot(container);
        root.render(
            React.createElement(window.WorkflowDAG, {
                workflow: workflow,
                workflowId: workflow.id
            })
        );
        console.log('DAG render initiated successfully');
    } catch (error) {
        console.error('Error rendering DAG:', error);
        renderSimpleDAG(workflow, container);
    }
}

// Simple fallback DAG renderer (doesn't require ReactFlow)
function renderSimpleDAG(workflow, container) {
    container.innerHTML = '';

    const actions = Object.values(workflow.actions);
    if (actions.length === 0) {
        container.innerHTML = '<div style="padding: 40px; text-align: center; color: #999;">No actions in this workflow</div>';
        return;
    }

    // Create a simple vertical flow diagram
    const dagHTML = `
        <div style="padding: 24px; background: #ffffff; border-radius: 8px;">
            <div style="margin-bottom: 16px; font-size: 14px; font-weight: 600; color: #525252;">
                Workflow Actions (${actions.length})
            </div>
            <div style="display: flex; flex-direction: column; gap: 12px;">
                ${actions.map((action, index) => {
                    const isLLM = action.type === 'llm';
                    const bgColor = isLLM ? '#ede9fe' : '#d1fae5';
                    const textColor = isLLM ? '#7c3aed' : '#059669';
                    const icon = isLLM ? '🤖' : '🔧';
                    const deps = action.dependencies || [];

                    return `
                        <div style="background: ${bgColor}; border: 2px solid ${textColor}40; border-radius: 8px; padding: 16px; position: relative;">
                            ${deps.length > 0 ? `
                                <div style="position: absolute; left: 16px; top: -12px; background: #fff; padding: 0 8px; font-size: 11px; color: #999; font-weight: 500;">
                                    ↑ depends on: ${deps.join(', ')}
                                </div>
                            ` : ''}
                            <div style="display: flex; align-items: center; gap: 12px;">
                                <div style="font-size: 24px;">${icon}</div>
                                <div style="flex: 1;">
                                    <div style="font-weight: 600; color: ${textColor}; margin-bottom: 4px;">
                                        ${action.name}
                                    </div>
                                    <div style="font-size: 13px; color: #666;">
                                        ${action.intent || action.description || ''}
                                    </div>
                                    ${action.model ? `
                                        <div style="margin-top: 6px; font-size: 12px; color: ${textColor}; font-family: monospace;">
                                            ${action.model}
                                        </div>
                                    ` : ''}
                                </div>
                                <div style="background: ${textColor}20; color: ${textColor}; padding: 4px 12px; border-radius: 12px; font-size: 11px; font-weight: 600; text-transform: uppercase;">
                                    ${action.type}
                                </div>
                            </div>
                        </div>
                    `;
                }).join('')}
            </div>
            <div style="margin-top: 20px; padding: 12px; background: #f5f5f5; border-radius: 6px; font-size: 12px; color: #666; text-align: center;">
                💡 Interactive DAG visualization will load when ReactFlow library is available
            </div>
        </div>
    `;

    container.innerHTML = dagHTML;
}

// ============================================
// UTILITY FUNCTIONS
// ============================================

function switchView(viewId) {
    document.querySelectorAll('.content-view').forEach(view => {
        view.classList.remove('active');
    });
    document.getElementById(viewId).classList.add('active');
}

function updateNavigation() {
    document.querySelectorAll('.nav-link').forEach(link => {
        link.classList.remove('active');
    });

    if (state.currentView === 'overview') {
        document.querySelector('[data-view="overview"]').classList.add('active');
    } else if (state.currentWorkflow) {
        const workflowLink = document.querySelector(`[data-workflow="${state.currentWorkflow}"]`);
        if (workflowLink) workflowLink.classList.add('active');
    }
}

function setupEventListeners() {
    // Overview link
    document.querySelectorAll('[data-view="overview"]').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            state.currentView = 'overview';
            updateNavigation();
            switchView('overview-view');
        });
    });

    // View all runs link
    document.querySelectorAll('.view-all-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            showAllRuns();
        });
    });

    // Breadcrumb navigation
    document.querySelectorAll('[data-breadcrumb]').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const breadcrumb = link.dataset.breadcrumb;

            switch(breadcrumb) {
                case 'workflows':
                    showAllWorkflows();
                    break;
                case 'actions':
                    showFilteredActions('all-actions');
                    break;
                case 'prompts':
                    showAllPrompts();
                    break;
                case 'schemas':
                    showAllSchemas();
                    break;
            }
        });
    });

    // Tab switching
    document.querySelectorAll('.tab-button').forEach(button => {
        button.addEventListener('click', () => {
            const tab = button.dataset.tab;
            state.currentTab = tab;

            document.querySelectorAll('.tab-button').forEach(b => b.classList.remove('active'));
            button.classList.add('active');

            document.querySelectorAll('.tab-pane').forEach(pane => pane.classList.remove('active'));
            document.getElementById(`${tab}-tab`).classList.add('active');
        });
    });

    // View toggle (Grid/List)
    document.querySelectorAll('.view-btn').forEach(button => {
        button.addEventListener('click', () => {
            const view = button.dataset.view;
            const target = button.dataset.target || 'workflows';

            // Determine which container to update and what data to render
            let containerId;
            let storageKey;
            let workflows;

            if (target === 'actions') {
                containerId = 'actions-filtered-grid';
                storageKey = 'actionsView';
                // For actions, we'll keep the old behavior for now
                const container = document.getElementById(containerId);
                if (!container) return;

                const parentSection = button.closest('.section-header');
                if (parentSection) {
                    parentSection.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
                }
                button.classList.add('active');

                if (view === 'list') {
                    container.classList.remove('workflows-grid');
                    container.classList.add('workflows-list');
                } else {
                    container.classList.remove('workflows-list');
                    container.classList.add('workflows-grid');
                }
                localStorage.setItem(storageKey, view);
                return;
            } else if (target === 'workflows-list') {
                containerId = 'workflows-list-grid';
                storageKey = 'workflowsListView';
                workflows = Object.values(catalog.workflows);
            } else {
                containerId = 'workflows-grid';
                storageKey = 'workflowView';
                workflows = Object.values(catalog.workflows);
            }

            // Update active button
            const parentSection = button.closest('.section-header');
            if (parentSection) {
                parentSection.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
            }
            button.classList.add('active');

            // Re-render workflows with the new view
            renderWorkflowsView(workflows, containerId, view);

            // Store preference
            localStorage.setItem(storageKey, view);
        });
    });

    // Stat card clicks
    document.querySelectorAll('.stat-card').forEach(card => {
        card.addEventListener('click', () => {
            const filter = card.dataset.filter;

            if (!filter) return;

            switch(filter) {
                case 'workflows':
                    // Show all workflows list view
                    showAllWorkflows();
                    break;

                case 'all-actions':
                case 'llm':
                case 'tool':
                    // Show filtered actions list view
                    showFilteredActions(filter);
                    break;

                case 'prompts':
                    // Show all prompts list view
                    showAllPrompts();
                    break;

                case 'schemas':
                    // Show all schemas list view
                    showAllSchemas();
                    break;
            }
        });
    });

    // Sidebar toggle
    const sidebar = document.querySelector('.sidebar');
    const sidebarToggle = document.getElementById('sidebar-toggle');
    const floatingToggle = document.getElementById('floating-sidebar-toggle');

    function toggleSidebar() {
        sidebar.classList.toggle('collapsed');
        const isCollapsed = sidebar.classList.contains('collapsed');

        // Update toggle icon based on state
        updateToggleIcon(isCollapsed);

        // Show/hide floating toggle button
        floatingToggle.style.display = isCollapsed ? 'flex' : 'none';

        // Store preference
        localStorage.setItem('sidebarCollapsed', isCollapsed);
    }

    /**
     * Update toggle icon based on sidebar state
     * @param {boolean} isCollapsed - Whether sidebar is collapsed
     */
    function updateToggleIcon(isCollapsed) {
        const toggleButton = document.getElementById('sidebar-toggle');

        if (isCollapsed) {
            toggleButton.title = 'Expand sidebar';
        } else {
            toggleButton.title = 'Collapse sidebar';
        }
    }

    sidebarToggle.addEventListener('click', toggleSidebar);
    floatingToggle.addEventListener('click', toggleSidebar);

    // Restore sidebar state from localStorage
    const sidebarCollapsed = localStorage.getItem('sidebarCollapsed') === 'true';
    if (sidebarCollapsed) {
        sidebar.classList.add('collapsed');
        floatingToggle.style.display = 'flex';
        updateToggleIcon(true); // Initialize with correct icon for collapsed state
    } else {
        updateToggleIcon(false); // Initialize with correct icon for expanded state
    }
}

function setupSearch() {
    const searchInput = document.getElementById('search-input');
    searchInput.addEventListener('input', (e) => {
        const query = e.target.value.toLowerCase();

        document.querySelectorAll('#workflows-list .nav-link, #actions-list .nav-link').forEach(link => {
            const text = link.textContent.toLowerCase();
            const li = link.parentElement;

            if (text.includes(query)) {
                li.style.display = '';
            } else {
                li.style.display = 'none';
            }
        });
    });
}

function truncateText(text, maxLength) {
    return text.length > maxLength ? text.substring(0, maxLength - 3) + '...' : text;
}
