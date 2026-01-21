// ============================================
// FILTER & SORT SYSTEM
// ============================================

class FilterManager {
    constructor(viewId, options = {}) {
        this.viewId = viewId;
        this.options = options;
        this.activeFilters = {};
        this.currentSort = options.defaultSort || null;
        this.searchQuery = '';
        this.allItems = [];
        this.filteredItems = [];

        // Element IDs
        this.ids = {
            search: `${viewId}-filter-search`,
            filterButton: `${viewId}-filter-button`,
            filterCount: `${viewId}-filter-count`,
            filterPanel: `${viewId}-filter-panel`,
            filterPanelContent: `${viewId}-filter-panel-content`,
            sortButton: `${viewId}-sort-button`,
            sortLabel: `${viewId}-sort-label`,
            sortMenu: `${viewId}-sort-menu`,
            activeFilters: `${viewId}-active-filters`,
            clearAll: `${viewId}-filter-clear-all`
        };

        this.init();
    }

    init() {
        console.log('[FilterManager] Initializing for view:', this.viewId);
        this.setupSearchInput();
        this.setupFilterButton();
        this.setupSortDropdown();
        this.setupClearAll();
        this.renderSortOptions();
        this.renderFilterPanel();
        this.restoreState();
    }

    setupSearchInput() {
        const searchInput = document.getElementById(this.ids.search);
        if (!searchInput) return;

        // Get clear button and results count elements
        const clearButton = document.getElementById(`${this.viewId}-search-clear`);
        const resultsCount = document.getElementById(`${this.viewId}-results-count`);

        // Setup clear button click handler
        if (clearButton) {
            clearButton.addEventListener('click', () => {
                searchInput.value = '';
                this.searchQuery = '';
                clearButton.style.display = 'none';
                if (resultsCount) resultsCount.style.display = 'none';
                this.applyFilters();
                this.saveState();
                searchInput.focus();
            });
        }

        let debounceTimer;
        searchInput.addEventListener('input', (e) => {
            clearTimeout(debounceTimer);

            // Show/hide clear button
            const hasValue = e.target.value.length > 0;
            if (clearButton) {
                clearButton.style.display = hasValue ? 'block' : 'none';
            }

            debounceTimer = setTimeout(() => {
                this.searchQuery = e.target.value.toLowerCase();
                this.applyFilters();
                this.saveState();
                this.updateResultsCount();
            }, 300);
        });
    }

    updateResultsCount() {
        const resultsCount = document.getElementById(`${this.viewId}-results-count`);
        if (!resultsCount) return;

        const count = this.filteredItems.length;
        const total = this.allItems.length;

        if (this.searchQuery || Object.keys(this.activeFilters).length > 0) {
            resultsCount.textContent = `Showing ${count} of ${total} ${this.viewId === 'workflows' ? 'workflows' : 'runs'}`;
            resultsCount.style.display = 'block';
        } else {
            resultsCount.style.display = 'none';
        }
    }

    setupFilterButton() {
        const filterButton = document.getElementById(this.ids.filterButton);
        const filterPanel = document.getElementById(this.ids.filterPanel);
        if (!filterButton || !filterPanel) return;

        filterButton.addEventListener('click', () => {
            const isVisible = filterPanel.style.display !== 'none';

            if (!isVisible) {
                // Position the panel below the button
                const buttonRect = filterButton.getBoundingClientRect();
                const filterBar = filterButton.closest('.filter-bar');

                // Get filter bar's position to align panel with it
                const filterBarRect = filterBar ? filterBar.getBoundingClientRect() : { left: buttonRect.left };

                // Use fixed positioning to place panel below button
                filterPanel.style.position = 'fixed';
                filterPanel.style.top = `${buttonRect.bottom + 4}px`;
                filterPanel.style.left = `${filterBarRect.left}px`;
                filterPanel.style.display = 'block';
                filterButton.classList.add('active');
            } else {
                filterPanel.style.display = 'none';
                filterButton.classList.remove('active');
            }
        });

        // Close on click outside
        document.addEventListener('click', (e) => {
            if (!filterButton.contains(e.target) && !filterPanel.contains(e.target)) {
                filterPanel.style.display = 'none';
                filterButton.classList.remove('active');
            }
        });
    }

    setupSortDropdown() {
        const sortButton = document.getElementById(this.ids.sortButton);
        const sortMenu = document.getElementById(this.ids.sortMenu);
        if (!sortButton || !sortMenu) return;

        sortButton.addEventListener('click', (e) => {
            e.stopPropagation();
            const isVisible = sortMenu.style.display === 'block';
            sortMenu.style.display = isVisible ? 'none' : 'block';
            sortButton.classList.toggle('active', !isVisible);
        });

        // Close on click outside
        document.addEventListener('click', (e) => {
            if (!sortButton.contains(e.target) && !sortMenu.contains(e.target)) {
                sortMenu.style.display = 'none';
                sortButton.classList.remove('active');
            }
        });
    }

    setupClearAll() {
        const clearAllButton = document.getElementById(this.ids.clearAll);
        if (!clearAllButton) return;

        clearAllButton.addEventListener('click', () => {
            this.clearAllFilters();
        });
    }

    renderSortOptions() {
        const sortMenu = document.getElementById(this.ids.sortMenu);
        if (!sortMenu || !this.options.sortOptions) return;

        sortMenu.innerHTML = '';
        this.options.sortOptions.forEach(option => {
            const optionEl = document.createElement('div');
            optionEl.className = 'sort-option';
            optionEl.dataset.sortId = option.id;

            const isActive = this.currentSort && this.currentSort.id === option.id;
            if (isActive) {
                optionEl.classList.add('active');
            }

            optionEl.innerHTML = `
                <span>${option.label}</span>
                ${isActive ? '<span class="sort-direction">✓</span>' : ''}
            `;

            optionEl.addEventListener('click', () => {
                this.setSort(option);
            });

            sortMenu.appendChild(optionEl);
        });
    }

    renderFilterPanel() {
        const panelContent = document.getElementById(this.ids.filterPanelContent);
        if (!panelContent || !this.options.filterGroups) return;

        panelContent.innerHTML = '';
        this.options.filterGroups.forEach(group => {
            const groupEl = document.createElement('div');
            groupEl.className = 'filter-group';

            const label = document.createElement('div');
            label.className = 'filter-group-label';
            label.textContent = group.label;
            groupEl.appendChild(label);

            group.options.forEach(option => {
                const optionEl = document.createElement('div');
                optionEl.className = 'filter-option';

                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.id = `filter-${option.id}`;
                checkbox.checked = this.activeFilters[option.id] || false;

                checkbox.addEventListener('change', (e) => {
                    if (e.target.checked) {
                        this.addFilter(option.id, true, option.label);
                    } else {
                        this.removeFilter(option.id);
                    }
                });

                const labelEl = document.createElement('label');
                labelEl.htmlFor = `filter-${option.id}`;
                labelEl.textContent = option.label;

                optionEl.appendChild(checkbox);
                optionEl.appendChild(labelEl);
                groupEl.appendChild(optionEl);
            });

            panelContent.appendChild(groupEl);
        });
    }

    setSort(sortOption) {
        this.currentSort = sortOption;

        // Update label
        const sortLabel = document.getElementById(this.ids.sortLabel);
        if (sortLabel) {
            sortLabel.textContent = `Sort: ${sortOption.label}`;
        }

        // Update menu
        this.renderSortOptions();

        // Close dropdown
        const sortMenu = document.getElementById(this.ids.sortMenu);
        if (sortMenu) {
            sortMenu.style.display = 'none';
        }

        // Apply filters
        this.applyFilters();
        this.saveState();
    }

    addFilter(filterKey, filterValue, displayText) {
        this.activeFilters[filterKey] = filterValue;
        this.renderFilterChips();
        this.updateFilterCount();
        this.applyFilters();
        this.saveState();
    }

    removeFilter(filterKey) {
        delete this.activeFilters[filterKey];

        // Update checkbox
        const checkbox = document.getElementById(`filter-${filterKey}`);
        if (checkbox) {
            checkbox.checked = false;
        }

        this.renderFilterChips();
        this.updateFilterCount();
        this.applyFilters();
        this.saveState();
    }

    renderFilterChips() {
        const container = document.getElementById(this.ids.activeFilters);
        if (!container) return;

        container.innerHTML = '';

        // Find filter labels
        const filterGroups = this.options.filterGroups || [];
        const filterMap = {};
        filterGroups.forEach(group => {
            group.options.forEach(option => {
                filterMap[option.id] = option.label;
            });
        });

        for (const [key, value] of Object.entries(this.activeFilters)) {
            if (!value) continue;

            const chip = document.createElement('div');
            chip.className = 'filter-chip';
            chip.dataset.filterKey = key;

            chip.innerHTML = `
                <span>${filterMap[key] || key}</span>
                <button class="filter-chip-remove" aria-label="Remove filter">
                    <svg width="12" height="12" viewBox="0 0 12 12">
                        <path d="M3 3l6 6M9 3l-6 6" stroke="currentColor" stroke-width="1.5"/>
                    </svg>
                </button>
            `;

            chip.querySelector('.filter-chip-remove').addEventListener('click', () => {
                this.removeFilter(key);
            });

            container.appendChild(chip);
        }
    }

    updateFilterCount() {
        const count = Object.keys(this.activeFilters).length;
        const badge = document.getElementById(this.ids.filterCount);
        const clearAll = document.getElementById(this.ids.clearAll);

        if (badge) {
            badge.textContent = count;
            badge.style.display = count > 0 ? 'inline-flex' : 'none';
        }

        if (clearAll) {
            clearAll.style.display = count > 0 ? 'inline-block' : 'none';
        }
    }

    clearAllFilters() {
        this.activeFilters = {};
        this.searchQuery = '';

        const searchInput = document.getElementById(this.ids.search);
        if (searchInput) {
            searchInput.value = '';
        }

        // Uncheck all checkboxes
        const filterGroups = this.options.filterGroups || [];
        filterGroups.forEach(group => {
            group.options.forEach(option => {
                const checkbox = document.getElementById(`filter-${option.id}`);
                if (checkbox) {
                    checkbox.checked = false;
                }
            });
        });

        this.renderFilterChips();
        this.updateFilterCount();
        this.applyFilters();
        this.saveState();
    }

    setItems(items) {
        this.allItems = items;
        this.applyFilters();
    }

    applyFilters() {
        let items = [...this.allItems];

        // Apply search
        if (this.searchQuery) {
            items = items.filter(item => this.matchesSearch(item));
        }

        // Apply filters
        for (const [key, value] of Object.entries(this.activeFilters)) {
            if (value) {
                items = items.filter(item => this.matchesFilter(item, key));
            }
        }

        // Apply sort
        if (this.currentSort) {
            items = this.sortItems(items, this.currentSort);
        }

        this.filteredItems = items;

        // Update results count
        this.updateResultsCount();

        // Notify callback
        if (this.options.onFilter) {
            this.options.onFilter(items);
        }

        return items;
    }

    matchesSearch(item) {
        if (!this.options.searchFields) return true;

        return this.options.searchFields.some(field => {
            const value = this.getNestedValue(item, field);
            return value && String(value).toLowerCase().includes(this.searchQuery);
        });
    }

    matchesFilter(item, filterKey) {
        if (!this.options.filterFunctions) return true;

        const filterFn = this.options.filterFunctions[filterKey];
        if (!filterFn) return true;

        return filterFn(item);
    }

    sortItems(items, sortOption) {
        const { field, direction } = sortOption;

        return [...items].sort((a, b) => {
            const aVal = this.getNestedValue(a, field);
            const bVal = this.getNestedValue(b, field);

            let comparison = 0;
            if (aVal < bVal) comparison = -1;
            if (aVal > bVal) comparison = 1;

            return direction === 'desc' ? -comparison : comparison;
        });
    }

    getNestedValue(obj, path) {
        return path.split('.').reduce((current, key) => current?.[key], obj);
    }

    saveState() {
        const state = {
            filters: this.activeFilters,
            sort: this.currentSort,
            search: this.searchQuery
        };
        localStorage.setItem(`filterState_${this.viewId}`, JSON.stringify(state));
    }

    restoreState() {
        const saved = localStorage.getItem(`filterState_${this.viewId}`);
        if (!saved) return;

        try {
            const state = JSON.parse(saved);
            this.activeFilters = state.filters || {};
            this.currentSort = state.sort;
            this.searchQuery = state.search || '';

            // Restore UI
            const searchInput = document.getElementById(this.ids.search);
            if (searchInput && this.searchQuery) {
                searchInput.value = this.searchQuery;

                // Show clear button if search has value
                const clearButton = document.getElementById(`${this.viewId}-search-clear`);
                if (clearButton) {
                    clearButton.style.display = 'block';
                }
            }

            if (this.currentSort) {
                const sortLabel = document.getElementById(this.ids.sortLabel);
                if (sortLabel) {
                    sortLabel.textContent = `Sort: ${this.currentSort.label}`;
                }
            }

            // Restore checkboxes
            for (const [key, value] of Object.entries(this.activeFilters)) {
                if (value) {
                    const checkbox = document.getElementById(`filter-${key}`);
                    if (checkbox) {
                        checkbox.checked = true;
                    }
                }
            }

            this.renderFilterChips();
            this.updateFilterCount();
            this.renderSortOptions();
        } catch (e) {
            console.error('[FilterManager] Error restoring state:', e);
        }
    }
}
