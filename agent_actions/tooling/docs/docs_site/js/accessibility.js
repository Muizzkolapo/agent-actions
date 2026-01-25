/**
 * Accessibility Utilities
 * Reusable helpers for WCAG 2.1 AA compliance
 */

// ============================================
// FOCUS MANAGEMENT
// ============================================

/**
 * Focus Trap for modals and dropdowns
 * Prevents keyboard navigation from leaving a modal
 *
 * @example
 * const trap = new FocusTrap(modalElement);
 * trap.activate();
 * // Later...
 * trap.deactivate();
 */
export class FocusTrap {
    constructor(element) {
        this.element = element;
        this.previousFocus = null;
        this.handleKeydown = this.handleKeydown.bind(this);
    }

    getFocusableElements() {
        const selector = [
            'a[href]',
            'button:not([disabled])',
            'textarea:not([disabled])',
            'input:not([disabled])',
            'select:not([disabled])',
            '[tabindex]:not([tabindex="-1"])'
        ].join(',');

        return Array.from(this.element.querySelectorAll(selector))
            .filter(el => isVisible(el));
    }

    activate() {
        this.previousFocus = document.activeElement;
        this.focusableElements = this.getFocusableElements();
        this.firstFocusable = this.focusableElements[0];
        this.lastFocusable = this.focusableElements[this.focusableElements.length - 1];

        // Focus first element
        if (this.firstFocusable) {
            this.firstFocusable.focus();
        }

        // Add event listener
        this.element.addEventListener('keydown', this.handleKeydown);
    }

    deactivate() {
        this.element.removeEventListener('keydown', this.handleKeydown);

        // Restore focus
        if (this.previousFocus && this.previousFocus.focus) {
            this.previousFocus.focus();
        }
    }

    handleKeydown(e) {
        // Handle Tab key
        if (e.key === 'Tab') {
            if (this.focusableElements.length === 1) {
                e.preventDefault();
                return;
            }

            if (e.shiftKey) {
                // Shift + Tab
                if (document.activeElement === this.firstFocusable) {
                    e.preventDefault();
                    this.lastFocusable.focus();
                }
            } else {
                // Tab
                if (document.activeElement === this.lastFocusable) {
                    e.preventDefault();
                    this.firstFocusable.focus();
                }
            }
        }

        // Handle Escape key
        if (e.key === 'Escape') {
            this.deactivate();
            // Emit custom event for parent to handle close
            this.element.dispatchEvent(new CustomEvent('trap-escape'));
        }
    }
}

/**
 * Check if element is visible
 */
function isVisible(element) {
    return !!(
        element.offsetWidth ||
        element.offsetHeight ||
        element.getClientRects().length
    ) && window.getComputedStyle(element).visibility !== 'hidden';
}

/**
 * Move focus to element with fallback
 */
export function moveFocusTo(element, fallback = null) {
    if (element && element.focus) {
        element.focus();
        return true;
    }

    if (fallback && fallback.focus) {
        fallback.focus();
        return true;
    }

    return false;
}

// ============================================
// SCREEN READER ANNOUNCEMENTS
// ============================================

let liveRegion = null;

/**
 * Announce message to screen readers
 *
 * @param {string} message - Message to announce
 * @param {string} priority - 'polite' or 'assertive'
 * @param {number} delay - Delay before announcement (ms)
 *
 * @example
 * announceToScreenReader('5 items found', 'polite');
 * announceToScreenReader('Error occurred!', 'assertive');
 */
export function announceToScreenReader(message, priority = 'polite', delay = 100) {
    // Create live region if it doesn't exist
    if (!liveRegion) {
        liveRegion = document.createElement('div');
        liveRegion.id = 'aria-live-region';
        liveRegion.className = 'visually-hidden';
        liveRegion.setAttribute('aria-live', priority);
        liveRegion.setAttribute('aria-atomic', 'true');
        document.body.appendChild(liveRegion);
    }

    // Update priority if different
    if (liveRegion.getAttribute('aria-live') !== priority) {
        liveRegion.setAttribute('aria-live', priority);
    }

    // Clear and announce after delay (allows screen reader to reset)
    liveRegion.textContent = '';

    setTimeout(() => {
        liveRegion.textContent = message;
    }, delay);
}

/**
 * Create a status message element
 */
export function createStatusMessage(message, type = 'info') {
    const statusEl = document.createElement('div');
    statusEl.className = `status-message status-${type}`;
    statusEl.setAttribute('role', 'status');
    statusEl.setAttribute('aria-live', 'polite');
    statusEl.textContent = message;

    return statusEl;
}

// ============================================
// KEYBOARD HANDLING
// ============================================

/**
 * Handle keyboard activation (Enter or Space)
 *
 * @example
 * element.addEventListener('keydown', (e) => {
 *     handleKeyboardActivation(e, () => {
 *         // Do something
 *     });
 * });
 */
export function handleKeyboardActivation(event, callback) {
    if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        callback(event);
    }
}

/**
 * Make element keyboard activatable
 *
 * @example
 * makeKeyboardActivatable(element, () => {
 *     console.log('Activated!');
 * });
 */
export function makeKeyboardActivatable(element, callback, options = {}) {
    const {
        role = 'button',
        tabindex = '0',
        ariaLabel = null
    } = options;

    // Set ARIA attributes
    element.setAttribute('role', role);
    element.setAttribute('tabindex', tabindex);
    if (ariaLabel) {
        element.setAttribute('aria-label', ariaLabel);
    }

    // Add keyboard handler
    element.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            callback(e);
        }
    });

    // Add click handler if not already present
    if (!element.onclick) {
        element.addEventListener('click', callback);
    }
}

/**
 * Arrow key navigation for lists
 *
 * @example
 * const nav = new ArrowKeyNavigator(listElement, {
 *     itemSelector: '.nav-item',
 *     onActivate: (item) => console.log('Activated:', item)
 * });
 */
export class ArrowKeyNavigator {
    constructor(container, options = {}) {
        this.container = container;
        this.options = {
            itemSelector: options.itemSelector || 'li',
            orientation: options.orientation || 'vertical', // 'vertical' or 'horizontal'
            loop: options.loop !== false, // Default true
            onActivate: options.onActivate || null
        };

        this.currentIndex = -1;
        this.handleKeydown = this.handleKeydown.bind(this);

        this.container.addEventListener('keydown', this.handleKeydown);
    }

    getItems() {
        return Array.from(
            this.container.querySelectorAll(this.options.itemSelector)
        ).filter(isVisible);
    }

    handleKeydown(e) {
        const items = this.getItems();
        if (items.length === 0) return;

        const isVertical = this.options.orientation === 'vertical';
        const nextKey = isVertical ? 'ArrowDown' : 'ArrowRight';
        const prevKey = isVertical ? 'ArrowUp' : 'ArrowLeft';

        let handled = false;

        if (e.key === nextKey) {
            handled = true;
            this.currentIndex = this.currentIndex + 1;
            if (this.currentIndex >= items.length) {
                this.currentIndex = this.options.loop ? 0 : items.length - 1;
            }
        } else if (e.key === prevKey) {
            handled = true;
            this.currentIndex = this.currentIndex - 1;
            if (this.currentIndex < 0) {
                this.currentIndex = this.options.loop ? items.length - 1 : 0;
            }
        } else if (e.key === 'Home') {
            handled = true;
            this.currentIndex = 0;
        } else if (e.key === 'End') {
            handled = true;
            this.currentIndex = items.length - 1;
        } else if (e.key === 'Enter' || e.key === ' ') {
            if (this.currentIndex >= 0 && this.options.onActivate) {
                handled = true;
                this.options.onActivate(items[this.currentIndex]);
            }
        }

        if (handled) {
            e.preventDefault();
            const item = items[this.currentIndex];
            if (item) {
                item.focus();
            }
        }
    }

    destroy() {
        this.container.removeEventListener('keydown', this.handleKeydown);
    }
}

// ============================================
// ARIA HELPERS
// ============================================

/**
 * Update ARIA expanded state
 */
export function updateAriaExpanded(element, isExpanded) {
    element.setAttribute('aria-expanded', isExpanded.toString());
}

/**
 * Update ARIA selected state
 */
export function updateAriaSelected(element, isSelected) {
    element.setAttribute('aria-selected', isSelected.toString());
}

/**
 * Update ARIA pressed state
 */
export function updateAriaPressed(element, isPressed) {
    element.setAttribute('aria-pressed', isPressed.toString());
}

/**
 * Update ARIA hidden state
 */
export function updateAriaHidden(element, isHidden) {
    element.setAttribute('aria-hidden', isHidden.toString());

    // Also update tabindex for keyboard navigation
    if (isHidden) {
        const focusable = element.querySelectorAll(
            'a, button, input, textarea, select, [tabindex]:not([tabindex="-1"])'
        );
        focusable.forEach(el => {
            el.setAttribute('data-original-tabindex', el.getAttribute('tabindex') || '0');
            el.setAttribute('tabindex', '-1');
        });
    } else {
        const focusable = element.querySelectorAll('[data-original-tabindex]');
        focusable.forEach(el => {
            el.setAttribute('tabindex', el.getAttribute('data-original-tabindex'));
            el.removeAttribute('data-original-tabindex');
        });
    }
}

/**
 * Create progress bar with ARIA
 */
export function createProgressBar(current, max, label) {
    const progressBar = document.createElement('div');
    progressBar.className = 'progress-bar';
    progressBar.setAttribute('role', 'progressbar');
    progressBar.setAttribute('aria-valuenow', current.toString());
    progressBar.setAttribute('aria-valuemin', '0');
    progressBar.setAttribute('aria-valuemax', max.toString());
    progressBar.setAttribute('aria-label', label);

    const percentage = (current / max) * 100;
    const fill = document.createElement('div');
    fill.className = 'progress-fill';
    fill.style.width = `${percentage}%`;

    progressBar.appendChild(fill);

    return progressBar;
}

// ============================================
// MODAL/DIALOG HELPERS
// ============================================

/**
 * Accessible modal dialog
 *
 * @example
 * const modal = new AccessibleModal({
 *     title: 'Confirm Action',
 *     content: 'Are you sure?',
 *     onConfirm: () => console.log('Confirmed')
 * });
 * modal.open();
 */
export class AccessibleModal {
    constructor(options) {
        this.options = {
            title: options.title || 'Dialog',
            content: options.content || '',
            confirmText: options.confirmText || 'Confirm',
            cancelText: options.cancelText || 'Cancel',
            onConfirm: options.onConfirm || null,
            onCancel: options.onCancel || null,
            closeOnEscape: options.closeOnEscape !== false,
            closeOnOverlay: options.closeOnOverlay !== false
        };

        this.element = null;
        this.focusTrap = null;
        this.create();
    }

    create() {
        // Create modal structure
        this.element = document.createElement('div');
        this.element.className = 'modal';
        this.element.setAttribute('role', 'dialog');
        this.element.setAttribute('aria-modal', 'true');
        this.element.setAttribute('aria-labelledby', 'modal-title');
        this.element.setAttribute('aria-describedby', 'modal-description');

        this.element.innerHTML = `
            <div class="modal-overlay"></div>
            <div class="modal-content">
                <div class="modal-header">
                    <h2 id="modal-title">${this.options.title}</h2>
                    <button class="modal-close" aria-label="Close dialog">
                        <svg width="20" height="20" aria-hidden="true">
                            <path d="M6 6l8 8M14 6l-8 8" stroke="currentColor"/>
                        </svg>
                    </button>
                </div>
                <div class="modal-body" id="modal-description">
                    ${this.options.content}
                </div>
                <div class="modal-footer">
                    <button class="modal-cancel">${this.options.cancelText}</button>
                    <button class="modal-confirm">${this.options.confirmText}</button>
                </div>
            </div>
        `;

        // Add event listeners
        this.element.querySelector('.modal-close').addEventListener('click', () => this.close());
        this.element.querySelector('.modal-cancel').addEventListener('click', () => {
            if (this.options.onCancel) this.options.onCancel();
            this.close();
        });
        this.element.querySelector('.modal-confirm').addEventListener('click', () => {
            if (this.options.onConfirm) this.options.onConfirm();
            this.close();
        });

        if (this.options.closeOnOverlay) {
            this.element.querySelector('.modal-overlay').addEventListener('click', () => this.close());
        }

        document.body.appendChild(this.element);
    }

    open() {
        this.element.style.display = 'flex';
        document.body.style.overflow = 'hidden';

        // Create focus trap
        const content = this.element.querySelector('.modal-content');
        this.focusTrap = new FocusTrap(content);
        this.focusTrap.activate();

        // Listen for escape
        if (this.options.closeOnEscape) {
            content.addEventListener('trap-escape', () => this.close());
        }

        // Announce to screen readers
        announceToScreenReader(`Dialog opened: ${this.options.title}`, 'assertive');
    }

    close() {
        this.element.style.display = 'none';
        document.body.style.overflow = '';

        // Deactivate focus trap
        if (this.focusTrap) {
            this.focusTrap.deactivate();
            this.focusTrap = null;
        }

        // Announce to screen readers
        announceToScreenReader('Dialog closed', 'polite');
    }

    destroy() {
        this.close();
        if (this.element) {
            this.element.remove();
        }
    }
}

// ============================================
// UTILITY FUNCTIONS
// ============================================

/**
 * Debounce function for performance
 */
export function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

/**
 * Get all focusable elements in container
 */
export function getFocusableElements(container) {
    const selector = [
        'a[href]',
        'button:not([disabled])',
        'textarea:not([disabled])',
        'input:not([disabled])',
        'select:not([disabled])',
        '[tabindex]:not([tabindex="-1"])'
    ].join(',');

    return Array.from(container.querySelectorAll(selector))
        .filter(isVisible);
}

/**
 * Trap focus within element on Tab key
 */
export function trapFocus(element, event) {
    const focusableElements = getFocusableElements(element);
    const firstFocusable = focusableElements[0];
    const lastFocusable = focusableElements[focusableElements.length - 1];

    if (event.key === 'Tab') {
        if (event.shiftKey) {
            if (document.activeElement === firstFocusable) {
                event.preventDefault();
                lastFocusable.focus();
            }
        } else {
            if (document.activeElement === lastFocusable) {
                event.preventDefault();
                firstFocusable.focus();
            }
        }
    }
}

/**
 * Escape HTML to prevent XSS
 */
export function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}

// ============================================
// EXPORT DEFAULT INSTANCE
// ============================================

// Make available globally for non-module usage
if (typeof window !== 'undefined') {
    window.A11y = {
        FocusTrap,
        ArrowKeyNavigator,
        AccessibleModal,
        announceToScreenReader,
        handleKeyboardActivation,
        makeKeyboardActivatable,
        updateAriaExpanded,
        updateAriaSelected,
        updateAriaPressed,
        updateAriaHidden,
        moveFocusTo,
        getFocusableElements,
        debounce
    };
}
