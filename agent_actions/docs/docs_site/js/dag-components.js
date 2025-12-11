/**
 * DAG React Components
 * Custom node components and main WorkflowDAG container using vanilla JS React
 */

// Debug: Log what's available
console.log('=== DAG Components Loading ===');
console.log('React:', typeof window.React);
console.log('ReactDOM:', typeof window.ReactDOM);
console.log('ReactFlow:', typeof window.ReactFlow);
console.log('XYFlow:', typeof window.XYFlow);
console.log('Window keys with "react":', Object.keys(window).filter(k => k.toLowerCase().includes('react')));
console.log('Window keys with "flow":', Object.keys(window).filter(k => k.toLowerCase().includes('flow')));

// Wait for all dependencies to load
(function() {
    'use strict';

    // Check if dependencies are loaded
    if (typeof window.React === 'undefined') {
        console.error('React is not loaded!');
        return;
    }
    if (typeof window.ReactDOM === 'undefined') {
        console.error('ReactDOM is not loaded!');
        return;
    }
    if (typeof window.ReactFlow === 'undefined' && typeof window.XYFlow === 'undefined') {
        console.error('ReactFlow is not loaded! Available:', Object.keys(window).filter(k => k.toLowerCase().includes('react') || k.toLowerCase().includes('flow') || k.toLowerCase().includes('xy')));
        return;
    }
    const RF_CHECK = window.ReactFlow || window.XYFlow;
    if (typeof RF_CHECK.ReactFlow === 'undefined' && typeof RF_CHECK.default === 'undefined') {
        console.log('ReactFlow module structure:', Object.keys(RF_CHECK).slice(0, 20));
        // Newer versions might export ReactFlow directly without .default
    }
    if (typeof window.dagre === 'undefined') {
        console.error('dagre is not loaded!');
        return;
    }

    // Access React from global
    const React = window.React;
    const h = React.createElement;

    // Access ReactFlow - newer versions export as window.ReactFlow
    // Fallback to window.XYFlow for @xyflow/react package
    const RF = window.ReactFlow || window.XYFlow;

    console.log('✓ ReactFlow module loaded successfully');
    console.log('ReactFlow object:', RF);
    console.log('ReactFlow properties:', Object.keys(RF).join(', '));
    console.log('Has ReactFlow component?', 'ReactFlow' in RF);
    console.log('Has useNodesState?', 'useNodesState' in RF);

    // Verify required exports are available
    if (!RF.default) {
        console.error('RF.default not found. Available keys:', Object.keys(RF));
        return;
    }

    // ============================================
    // MODEL NODE COMPONENT
    // ============================================
    window.ModelNode = function({ data, isConnectable }) {
        const isInactive = data.inPlan === false;
        return h('div', {
            className: 'rf-node-card rf-model-node',
            style: {
                width: '350px',                   // Increased from 280px
                minHeight: '110px',               // Increased from 90px
                maxHeight: data.fieldsExpanded ? '600px' : '140px',  // Increased heights
                background: isInactive
                    ? 'linear-gradient(135deg, #1a1f2e 0%, #16191f 100%)'
                    : 'linear-gradient(135deg, #1e293b 0%, #1a2332 100%)',
                border: `2px solid ${isInactive ? '#4a5568' : (data.isOperational ? '#3b82f6' : '#6b7280')}`,
                borderRadius: '8px',
                padding: '14px',                  // Increased from 10px
                boxShadow: '0 4px 12px rgba(0, 0, 0, 0.3)',
                display: 'flex',
                flexDirection: 'column',
                overflow: 'hidden',
                opacity: isInactive ? 0.5 : 1
            }
        }, [
            // Top handle
            h(RF.Handle, {
                key: 'target',
                type: 'target',
                position: RF.Position.Top,
                isConnectable: isConnectable,
                style: { background: '#3b82f6', width: '10px', height: '10px' }
            }),

            // Header with icon and title
            h('div', {
                key: 'header',
                style: {
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px',                  // Increased from 6px
                    marginBottom: '12px',         // Increased from 8px
                    paddingBottom: '10px',        // Increased from 6px
                    borderBottom: '1px solid #334155'
                }
            }, [
                h('div', {
                    key: 'icon',
                    style: {
                        width: '32px',            // Increased from 24px
                        height: '32px',
                        borderRadius: '50%',
                        background: '#3b82f6',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: '16px'          // Increased from 12px
                    }
                }, '🤖'),
                h('div', {
                    key: 'title',
                    style: {
                        flex: 1,
                        fontWeight: 600,
                        color: '#f1f5f9',
                        fontSize: '1rem',         // Increased from 0.85rem
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap'
                    }
                }, data.label)
            ]),

            // Body with model info
            h('div', {
                key: 'body',
                style: {
                    fontSize: '0.7rem',
                    color: '#cbd5e0',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '5px'
                }
            }, [
                h('div', {
                    key: 'provider',
                    style: { display: 'flex', justifyContent: 'space-between' }
                }, [
                    h('span', { key: 'label', style: { color: '#94a3b8' }}, 'Provider:'),
                    h('span', {
                        key: 'value',
                        style: {
                            textTransform: 'capitalize',
                            color: data.provider === 'openai' ? '#10b981' :
                                   data.provider === 'anthropic' ? '#a855f7' :
                                   data.provider === 'google' ? '#3b82f6' : '#94a3b8',
                            fontWeight: 500
                        }
                    }, data.provider)
                ]),
                h('div', {
                    key: 'model',
                    style: { display: 'flex', justifyContent: 'space-between' }
                }, [
                    h('span', { key: 'label', style: { color: '#94a3b8' }}, 'Model:'),
                    h('span', {
                        key: 'value',
                        style: {
                            fontFamily: 'monospace',
                            fontSize: '0.7rem'
                        }
                    }, data.model)
                ])
            ]),

            // Fields section with expand button
            (data.inputFields && data.inputFields.length > 0) || (data.outputFields && data.outputFields.length > 0) ?
            h('div', {
                key: 'fields-section',
                style: {
                    marginTop: '8px',
                    paddingTop: '8px',
                    borderTop: '1px solid #334155',
                    flex: data.fieldsExpanded ? '1 1 auto' : '0 0 auto',
                    overflow: data.fieldsExpanded ? 'auto' : 'visible',
                    minHeight: data.fieldsExpanded ? '0' : 'auto'
                }
            }, [
                // Expand button
                h('button', {
                    key: 'expand-btn',
                    onClick: (e) => {
                        e.stopPropagation();
                        if (data.onExpandFields) {
                            data.onExpandFields(data.label);
                        }
                    },
                    style: {
                        background: 'none',
                        border: 'none',
                        color: '#3b82f6',
                        cursor: 'pointer',
                        fontSize: '0.65rem',
                        padding: '4px 0',
                        width: '100%',
                        textAlign: 'left',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '4px'
                    }
                }, [
                    h('span', { key: 'arrow' }, data.fieldsExpanded ? '▼' : '▶'),
                    h('span', { key: 'text' }, data.fieldsExpanded ? 'Hide fields' : 'Show fields'),
                    h('span', {
                        key: 'count',
                        style: { marginLeft: 'auto', color: '#94a3b8' }
                    }, `(${(data.inputFields?.length || 0) + (data.outputFields?.length || 0)})`)
                ]),

                // Expanded fields list
                data.fieldsExpanded && h('div', {
                    key: 'fields-list',
                    style: {
                        marginTop: '6px',
                        fontSize: '0.65rem'
                    }
                }, [
                    // Input fields
                    data.inputFields && data.inputFields.length > 0 && h('div', {
                        key: 'inputs',
                        style: { marginBottom: '6px' }
                    }, [
                        h('div', {
                            key: 'header',
                            style: {
                                color: '#60a5fa',
                                fontWeight: 600,
                                marginBottom: '4px',
                                fontSize: '0.6rem'
                            }
                        }, 'INPUTS'),
                        ...data.inputFields.map(field =>
                            h('div', {
                                key: field,
                                style: {
                                    padding: '3px 6px',
                                    background: '#1e3a5f',
                                    borderRadius: '3px',
                                    marginBottom: '2px',
                                    color: '#cbd5e0',
                                    fontFamily: 'monospace',
                                    fontSize: '0.65rem'
                                }
                            }, field)
                        )
                    ]),
                    // Output fields
                    data.outputFields && data.outputFields.length > 0 && h('div', {
                        key: 'outputs'
                    }, [
                        h('div', {
                            key: 'header',
                            style: {
                                color: '#34d399',
                                fontWeight: 600,
                                marginBottom: '4px',
                                fontSize: '0.6rem'
                            }
                        }, 'OUTPUTS'),
                        ...data.outputFields.map(field =>
                            h('div', {
                                key: field,
                                style: {
                                    padding: '3px 6px',
                                    background: '#1a3d2e',
                                    borderRadius: '3px',
                                    marginBottom: '2px',
                                    color: '#cbd5e0',
                                    fontFamily: 'monospace',
                                    fontSize: '0.65rem'
                                }
                            }, field)
                        )
                    ])
                ])
            ]) : null,

            // Bottom handle
            h(RF.Handle, {
                key: 'source',
                type: 'source',
                position: RF.Position.Bottom,
                isConnectable: isConnectable,
                style: { background: '#3b82f6', width: '10px', height: '10px' }
            })
        ]);
    };

    // ============================================
    // TOOL NODE COMPONENT
    // ============================================
    window.ToolNode = function({ data, isConnectable }) {
        const isInactive = data.inPlan === false;
        return h('div', {
            className: 'rf-node-card rf-tool-node',
            style: {
                width: '350px',                   // Increased from 280px
                minHeight: '110px',               // Increased from 90px
                maxHeight: data.fieldsExpanded ? '600px' : '140px',  // Increased heights
                background: isInactive
                    ? 'linear-gradient(135deg, #1a1f2e 0%, #16191f 100%)'
                    : 'linear-gradient(135deg, #1e293b 0%, #1a2332 100%)',
                border: `2px solid ${isInactive ? '#4a5568' : (data.isOperational ? '#10b981' : '#6b7280')}`,
                borderRadius: '8px',
                padding: '14px',                  // Increased from 10px
                boxShadow: '0 4px 12px rgba(0, 0, 0, 0.3)',
                display: 'flex',
                flexDirection: 'column',
                overflow: 'hidden',
                opacity: isInactive ? 0.5 : 1
            }
        }, [
            // Top handle
            h(RF.Handle, {
                key: 'target',
                type: 'target',
                position: RF.Position.Top,
                isConnectable: isConnectable,
                style: { background: '#10b981', width: '10px', height: '10px' }
            }),

            // Header
            h('div', {
                key: 'header',
                style: {
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px',                  // Increased from 6px
                    marginBottom: '12px',         // Increased from 8px
                    paddingBottom: '10px',        // Increased from 6px
                    borderBottom: '1px solid #334155'
                }
            }, [
                h('div', {
                    key: 'icon',
                    style: {
                        width: '32px',            // Increased from 24px
                        height: '32px',
                        borderRadius: '50%',
                        background: '#10b981',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: '16px'          // Increased from 12px
                    }
                }, '🔧'),
                h('div', {
                    key: 'title',
                    style: {
                        flex: 1,
                        fontWeight: 600,
                        color: '#f1f5f9',
                        fontSize: '1rem',         // Increased from 0.85rem
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap'
                    }
                }, data.label)
            ]),

            // Body
            h('div', {
                key: 'body',
                style: {
                    fontSize: '0.7rem',
                    color: '#cbd5e0',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '5px'
                }
            }, [
                h('div', {
                    key: 'provider',
                    style: { display: 'flex', justifyContent: 'space-between' }
                }, [
                    h('span', { key: 'label', style: { color: '#94a3b8' }}, 'Provider:'),
                    h('span', {
                        key: 'value',
                        style: {
                            textTransform: 'capitalize',
                            color: '#10b981',
                            fontWeight: 500
                        }
                    }, data.provider)
                ]),
                h('div', {
                    key: 'impl',
                    style: { display: 'flex', justifyContent: 'space-between' }
                }, [
                    h('span', { key: 'label', style: { color: '#94a3b8' }}, 'Type:'),
                    h('span', {
                        key: 'value',
                        style: {
                            fontFamily: 'monospace',
                            fontSize: '0.7rem'
                        }
                    }, data.impl)
                ])
            ]),

            // Fields section with expand button
            (data.inputFields && data.inputFields.length > 0) || (data.outputFields && data.outputFields.length > 0) ?
            h('div', {
                key: 'fields-section',
                style: {
                    marginTop: '8px',
                    paddingTop: '8px',
                    borderTop: '1px solid #334155',
                    flex: data.fieldsExpanded ? '1 1 auto' : '0 0 auto',
                    overflow: data.fieldsExpanded ? 'auto' : 'visible',
                    minHeight: data.fieldsExpanded ? '0' : 'auto'
                }
            }, [
                // Expand button
                h('button', {
                    key: 'expand-btn',
                    onClick: (e) => {
                        e.stopPropagation();
                        if (data.onExpandFields) {
                            data.onExpandFields(data.label);
                        }
                    },
                    style: {
                        background: 'none',
                        border: 'none',
                        color: '#10b981',
                        cursor: 'pointer',
                        fontSize: '0.65rem',
                        padding: '4px 0',
                        width: '100%',
                        textAlign: 'left',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '4px'
                    }
                }, [
                    h('span', { key: 'arrow' }, data.fieldsExpanded ? '▼' : '▶'),
                    h('span', { key: 'text' }, data.fieldsExpanded ? 'Hide fields' : 'Show fields'),
                    h('span', {
                        key: 'count',
                        style: { marginLeft: 'auto', color: '#94a3b8' }
                    }, `(${(data.inputFields?.length || 0) + (data.outputFields?.length || 0)})`)
                ]),

                // Expanded fields list
                data.fieldsExpanded && h('div', {
                    key: 'fields-list',
                    style: {
                        marginTop: '6px',
                        fontSize: '0.65rem'
                    }
                }, [
                    // Input fields
                    data.inputFields && data.inputFields.length > 0 && h('div', {
                        key: 'inputs',
                        style: { marginBottom: '6px' }
                    }, [
                        h('div', {
                            key: 'header',
                            style: {
                                color: '#60a5fa',
                                fontWeight: 600,
                                marginBottom: '4px',
                                fontSize: '0.6rem'
                            }
                        }, 'INPUTS'),
                        ...data.inputFields.map(field =>
                            h('div', {
                                key: field,
                                style: {
                                    padding: '3px 6px',
                                    background: '#1e3a5f',
                                    borderRadius: '3px',
                                    marginBottom: '2px',
                                    color: '#cbd5e0',
                                    fontFamily: 'monospace',
                                    fontSize: '0.65rem'
                                }
                            }, field)
                        )
                    ]),
                    // Output fields
                    data.outputFields && data.outputFields.length > 0 && h('div', {
                        key: 'outputs'
                    }, [
                        h('div', {
                            key: 'header',
                            style: {
                                color: '#34d399',
                                fontWeight: 600,
                                marginBottom: '4px',
                                fontSize: '0.6rem'
                            }
                        }, 'OUTPUTS'),
                        ...data.outputFields.map(field =>
                            h('div', {
                                key: field,
                                style: {
                                    padding: '3px 6px',
                                    background: '#1a3d2e',
                                    borderRadius: '3px',
                                    marginBottom: '2px',
                                    color: '#cbd5e0',
                                    fontFamily: 'monospace',
                                    fontSize: '0.65rem'
                                }
                            }, field)
                        )
                    ])
                ])
            ]) : null,

            // Bottom handle
            h(RF.Handle, {
                key: 'source',
                type: 'source',
                position: RF.Position.Bottom,
                isConnectable: isConnectable,
                style: { background: '#10b981', width: '10px', height: '10px' }
            })
        ]);
    };

    // ============================================
    // FIELD ACTION NODE COMPONENT (For Lineage)
    // ============================================
    window.FieldActionNode = function({ data, isConnectable }) {
        const [expanded, setExpanded] = React.useState(data.initiallyExpanded || false);

        const toggleExpand = () => {
            setExpanded(!expanded);
            // Notify parent to update edges visibility
            if (data.onExpandChange) {
                data.onExpandChange(data.label, !expanded);
            }
        };

        // Icon styling based on node type
        const iconStyle = data.type === 'llm' ? {
            background: '#7b61ff',
            icon: '🤖'
        } : {
            background: '#059669',
            icon: '🔧'
        };

        // Calculate handles - input fields on left, output fields on right
        const inputHandles = (data.inputFields || []).map((field, idx) => {
            const yOffset = expanded ? (80 + (idx * 32)) : 60; // Adjust for expanded/collapsed

            return h(RF.Handle, {
                key: `input-${field}`,
                type: 'target',
                position: RF.Position.Left,
                id: `input-${field}`,
                isConnectable: isConnectable,
                style: {
                    background: '#3b82f6',
                    width: '6px',
                    height: '6px',
                    top: expanded ? `${yOffset}px` : '50%',
                    left: '-3px',
                    border: 'none'
                }
            });
        });

        const outputHandles = (data.outputFields || []).map((field, idx) => {
            const inputCount = (data.inputFields || []).length;
            const yOffset = expanded ? (80 + inputCount * 32 + 40 + (idx * 32)) : 60;

            return h(RF.Handle, {
                key: `output-${field}`,
                type: 'source',
                position: RF.Position.Right,
                id: `output-${field}`,
                isConnectable: isConnectable,
                style: {
                    background: '#f59e0b',
                    width: '6px',
                    height: '6px',
                    top: expanded ? `${yOffset}px` : '50%',
                    right: '-3px',
                    border: 'none'
                }
            });
        });

        return h('div', {
            className: 'rf-node-card rf-field-action-node',
            style: {
                width: '350px',                   // Increased from 280px
                minHeight: '110px',               // Increased from 90px
                maxHeight: expanded ? '600px' : '140px',  // Increased heights
                background: '#ffffff',
                border: '1px solid #e5e7eb',
                borderRadius: '6px',
                boxShadow: '0 1px 3px rgba(0, 0, 0, 0.1)',
                fontSize: '0.875rem',
                overflow: 'hidden',
                display: 'flex',
                flexDirection: 'column'
            }
        }, [
            // Header
            h('div', {
                key: 'header',
                style: {
                    padding: '12px 14px',
                    background: '#ffffff',
                    borderBottom: '1px solid #e5e7eb',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    cursor: 'pointer'
                },
                onClick: toggleExpand
            }, [
                h('div', {
                    key: 'icon',
                    style: {
                        width: '20px',
                        height: '20px',
                        borderRadius: '3px',
                        background: iconStyle.background,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: '11px',
                        flexShrink: 0
                    }
                }, iconStyle.icon),
                h('div', {
                    key: 'title',
                    style: {
                        flex: 1,
                        fontWeight: 500,
                        fontSize: '0.875rem',
                        color: '#111827',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap'
                    }
                }, data.label),
                h('div', {
                    key: 'expand-btn',
                    style: {
                        color: '#9ca3af',
                        fontSize: '12px',
                        flexShrink: 0
                    }
                }, expanded ? '▼' : '▶')
            ]),

            // Body content
            h('div', {
                key: 'body',
                style: {
                    padding: expanded ? '12px' : '8px 14px',
                    background: '#fafafa',
                    flex: expanded ? '1 1 auto' : '0 0 auto',
                    overflow: expanded ? 'auto' : 'visible',
                    minHeight: expanded ? '0' : 'auto'
                }
            }, [
                // Expanded view - show fields
                expanded && h('div', {
                    key: 'expanded',
                    style: {
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '12px'
                    }
                }, [
                    // Input fields
                    (data.inputFields && data.inputFields.length > 0) && h('div', {
                        key: 'inputs'
                    }, [
                        h('div', {
                            key: 'header',
                            style: {
                                fontSize: '0.75rem',
                                fontWeight: 600,
                                color: '#6b7280',
                                marginBottom: '6px',
                                textTransform: 'uppercase',
                                letterSpacing: '0.025em'
                            }
                        }, 'Inputs'),
                        h('div', {
                            key: 'list',
                            style: {
                                display: 'flex',
                                flexDirection: 'column',
                                gap: '4px'
                            }
                        }, data.inputFields.map(field =>
                            h('div', {
                                key: field,
                                style: {
                                    padding: '8px 10px',
                                    background: '#dbeafe',
                                    borderRadius: '4px',
                                    color: '#1e40af',
                                    fontSize: '0.8125rem',
                                    fontFamily: 'ui-monospace, monospace',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '6px'
                                }
                            }, [
                                h('span', {
                                    key: 'dot',
                                    style: {
                                        width: '6px',
                                        height: '6px',
                                        borderRadius: '50%',
                                        background: '#3b82f6',
                                        flexShrink: 0
                                    }
                                }),
                                h('span', { key: 'name' }, field)
                            ])
                        ))
                    ]),

                    // Output fields
                    (data.outputFields && data.outputFields.length > 0) && h('div', {
                        key: 'outputs'
                    }, [
                        h('div', {
                            key: 'header',
                            style: {
                                fontSize: '0.75rem',
                                fontWeight: 600,
                                color: '#6b7280',
                                marginBottom: '6px',
                                textTransform: 'uppercase',
                                letterSpacing: '0.025em'
                            }
                        }, 'Outputs'),
                        h('div', {
                            key: 'list',
                            style: {
                                display: 'flex',
                                flexDirection: 'column',
                                gap: '4px'
                            }
                        }, data.outputFields.map(field =>
                            h('div', {
                                key: field,
                                style: {
                                    padding: '8px 10px',
                                    background: '#dbeafe',
                                    borderRadius: '4px',
                                    color: '#1e40af',
                                    fontSize: '0.8125rem',
                                    fontFamily: 'ui-monospace, monospace',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'space-between',
                                    gap: '6px'
                                }
                            }, [
                                h('span', { key: 'name' }, field),
                                h('span', {
                                    key: 'dot',
                                    style: {
                                        width: '6px',
                                        height: '6px',
                                        borderRadius: '50%',
                                        background: '#f59e0b',
                                        flexShrink: 0
                                    }
                                })
                            ])
                        ))
                    ])
                ]),

                // Collapsed view - show summary
                !expanded && h('div', {
                    key: 'collapsed',
                    style: {
                        fontSize: '0.75rem',
                        color: '#6b7280',
                        display: 'flex',
                        gap: '8px',
                        alignItems: 'center'
                    }
                }, [
                    data.inputFields && data.inputFields.length > 0 && h('span', {
                        key: 'inputs',
                        style: { color: '#3b82f6' }
                    }, `${data.inputFields.length} inputs`),
                    data.inputFields && data.inputFields.length > 0 && data.outputFields && data.outputFields.length > 0 && h('span', {
                        key: 'sep',
                        style: { color: '#d1d5db' }
                    }, '•'),
                    data.outputFields && data.outputFields.length > 0 && h('span', {
                        key: 'outputs',
                        style: { color: '#f59e0b' }
                    }, `${data.outputFields.length} outputs`)
                ])
            ]),

            // Handles
            ...inputHandles,
            ...outputHandles
        ]);
    };

    // ============================================
    // LEGEND PANEL COMPONENT
    // ============================================
    function LegendPanel() {
        return h('div', {
            className: 'rf-legend-panel'
        }, [
            h('div', {
                key: 'title',
                className: 'rf-legend-title'
            }, 'LEGEND'),

            // Model Node item
            h('div', {
                key: 'model',
                className: 'rf-legend-item'
            }, [
                h('div', {
                    key: 'icon',
                    className: 'rf-legend-icon model'
                }, '🤖'),
                h('span', { key: 'text' }, 'Model Node')
            ]),

            // Tool Node item
            h('div', {
                key: 'tool',
                className: 'rf-legend-item'
            }, [
                h('div', {
                    key: 'icon',
                    className: 'rf-legend-icon tool'
                }, '🔧'),
                h('span', { key: 'text' }, 'Tool Node')
            ]),

            // Operational item
            h('div', {
                key: 'operational',
                className: 'rf-legend-item'
            }, [
                h('div', {
                    key: 'dot',
                    className: 'rf-legend-dot operational'
                }),
                h('span', { key: 'text' }, 'Operational')
            ]),

            // Not Operational item
            h('div', {
                key: 'not-operational',
                className: 'rf-legend-item'
            }, [
                h('div', {
                    key: 'dot',
                    className: 'rf-legend-dot not-operational'
                }),
                h('span', { key: 'text' }, 'Not Operational')
            ])
        ]);
    }

    // ============================================
    // CUSTOM CONTROLS COMPONENT
    // ============================================
    function CustomControls() {
        const { zoomTo } = RF.useReactFlow();

        // Fullscreen toggle handler
        const handleFullscreen = React.useCallback(() => {
            const container = document.getElementById('dag-container');
            if (!container) return;

            if (!document.fullscreenElement) {
                if (container.requestFullscreen) {
                    container.requestFullscreen();
                } else if (container.webkitRequestFullscreen) {
                    container.webkitRequestFullscreen();
                }
            } else {
                if (document.exitFullscreen) {
                    document.exitFullscreen();
                } else if (document.webkitExitFullscreen) {
                    document.webkitExitFullscreen();
                }
            }
        }, []);

        // Zoom reset handler
        const handleZoomReset = React.useCallback(() => {
            zoomTo(1.0, { duration: 300 });
        }, [zoomTo]);

        return h('div', {
            className: 'rf-custom-controls'
        }, [
            // Fullscreen button
            h('button', {
                key: 'fullscreen',
                className: 'rf-control-btn',
                onClick: handleFullscreen,
                title: 'Toggle Fullscreen'
            }, [
                h('svg', {
                    key: 'icon',
                    width: '18',
                    height: '18',
                    viewBox: '0 0 18 18',
                    fill: 'none',
                    stroke: 'currentColor',
                    strokeWidth: '2'
                }, [
                    h('path', {
                        key: 'path',
                        d: 'M2 6V2h4M16 6V2h-4M2 12v4h4M16 12v4h-4'
                    })
                ])
            ]),

            // Zoom reset button
            h('button', {
                key: 'zoom',
                className: 'rf-control-btn',
                onClick: handleZoomReset,
                title: 'Reset Zoom'
            }, [
                h('svg', {
                    key: 'icon',
                    width: '18',
                    height: '18',
                    viewBox: '0 0 18 18',
                    fill: 'none',
                    stroke: 'currentColor',
                    strokeWidth: '2'
                }, [
                    h('circle', {
                        key: 'circle',
                        cx: '8',
                        cy: '8',
                        r: '6'
                    }),
                    h('path', {
                        key: 'line',
                        d: 'M12 12l4 4'
                    })
                ])
            ])
        ]);
    }

    // ============================================
    // MAIN WORKFLOW DAG COMPONENT (Inner)
    // ============================================
    function WorkflowDAGContent({ workflow, workflowId }) {
        // Use ReactFlow's state management hooks for proper interactivity
        const [nodes, setNodes, onNodesChange] = RF.useNodesState([]);
        const [edges, setEdges, onEdgesChange] = RF.useEdgesState([]);
        const { fitView } = RF.useReactFlow();

        // Track which nodes have fields expanded
        // Initialize as null - will be populated when workflow loads
        const [expandedFields, setExpandedFields] = React.useState(null);

        // Handle field expansion toggle
        // When node is in Set → expanded, when not in Set → collapsed
        const handleExpandFields = React.useCallback((nodeName) => {
            setExpandedFields(prev => {
                const newSet = new Set(prev);
                if (newSet.has(nodeName)) {
                    newSet.delete(nodeName);  // Remove from Set = collapse fields
                } else {
                    newSet.add(nodeName);     // Add to Set = expand fields
                }
                return newSet;
            });
        }, []);

        const nodeTypes = React.useMemo(() => ({
            modelNode: window.ModelNode,
            toolNode: window.ToolNode
        }), []);

        // Initialize from workflow data
        React.useEffect(() => {
            console.log('Transforming workflow:', workflow.name);
            const transformed = window.transformWorkflowToReactFlow(workflow);
            console.log('Transformed data:', transformed);

            // Initialize expandedFields Set with ALL node labels to start with all fields expanded
            // This ensures the toggle button logic works correctly (node in Set = expanded)
            const allNodeLabels = transformed.nodes.map(node => node.data.label);
            setExpandedFields(new Set(allNodeLabels));

            // Add the onExpandFields callback to all nodes immediately
            const nodesWithCallbacks = transformed.nodes.map(node => ({
                ...node,
                data: {
                    ...node.data,
                    fieldsExpanded: true,   // Start with fields expanded by default
                    onExpandFields: handleExpandFields
                }
            }));

            setNodes(nodesWithCallbacks);
            setEdges(transformed.edges);

            // Fit view after layout
            setTimeout(() => {
                try {
                    fitView({ padding: 0.2, duration: 800 });
                } catch (e) {
                    console.warn('fitView failed:', e);
                }
            }, 100);
        }, [workflow, fitView, setNodes, setEdges, handleExpandFields]);

        // Update nodes with field expansion state whenever expandedFields changes
        React.useEffect(() => {
            // Only update if expandedFields has been initialized
            if (!expandedFields) return;

            setNodes(currentNodes =>
                currentNodes.map(node => ({
                    ...node,
                    data: {
                        ...node.data,
                        fieldsExpanded: expandedFields.has(node.data.label),  // Node is expanded if its label is in the Set
                        onExpandFields: handleExpandFields
                    }
                }))
            );
        }, [expandedFields, handleExpandFields, setNodes]);

        // Handle fullscreen changes - force ReactFlow to resize and center
        React.useEffect(() => {
            const handleFullscreenChange = () => {
                console.log('Fullscreen changed, resizing ReactFlow');

                // Trigger window resize event to force ReactFlow to recalculate dimensions
                window.dispatchEvent(new Event('resize'));

                // Wait for the transition and resize to complete
                setTimeout(() => {
                    // Trigger resize again
                    window.dispatchEvent(new Event('resize'));

                    try {
                        // Use more aggressive centering with smaller padding
                        fitView({
                            padding: 0.1,
                            includeHiddenNodes: false,
                            minZoom: 0.2,
                            maxZoom: 1.2,
                            duration: 400
                        });
                    } catch (e) {
                        console.warn('fitView failed on fullscreen change:', e);
                    }
                }, 200);

                // Second pass to ensure proper centering after everything settles
                setTimeout(() => {
                    try {
                        fitView({
                            padding: 0.15,
                            duration: 200
                        });
                    } catch (e) {
                        console.warn('Second fitView failed:', e);
                    }
                }, 600);
            };

            // Listen for fullscreen change events
            document.addEventListener('fullscreenchange', handleFullscreenChange);
            document.addEventListener('webkitfullscreenchange', handleFullscreenChange);
            document.addEventListener('mozfullscreenchange', handleFullscreenChange);

            return () => {
                document.removeEventListener('fullscreenchange', handleFullscreenChange);
                document.removeEventListener('webkitfullscreenchange', handleFullscreenChange);
                document.removeEventListener('mozfullscreenchange', handleFullscreenChange);
            };
        }, [fitView]);

        // Handle node clicks - navigate to action view
        const onNodeClick = React.useCallback((event, node) => {
            if (window.showAction) {
                window.showAction(workflowId, node.id);
            }
        }, [workflowId]);

        return h(RF.ReactFlow, {
            nodes: nodes,
            edges: edges,
            nodeTypes: nodeTypes,
            onNodesChange: onNodesChange,
            onEdgesChange: onEdgesChange,
            onNodeClick: onNodeClick,
            fitView: true,
            minZoom: 0.2,
            maxZoom: 1.5,
            nodesDraggable: true,
            nodesConnectable: false,
            elementsSelectable: true,
            defaultEdgeOptions: {
                type: 'smoothstep',
                animated: true
            },
            style: { width: '100%', height: '100%', background: '#1a2332' }
        }, [
            h(RF.Background, {
                key: 'bg',
                color: '#334155',
                gap: 16,
                size: 1
            }),

            // Built-in ReactFlow controls (left side)
            h(RF.Controls, {
                key: 'controls',
                showInteractive: true,
                style: {
                    background: 'rgba(15, 23, 42, 0.9)',
                    border: '1px solid #334155'
                }
            }),

            // Legend panel (top-left) - COMMENTED OUT
            // h(RF.Panel, {
            //     key: 'legend-panel',
            //     position: 'top-left',
            //     style: {
            //         margin: '16px'
            //     }
            // }, h(LegendPanel)),

            // Custom controls (top-right)
            h(RF.Panel, {
                key: 'controls-panel',
                position: 'top-right',
                style: {
                    margin: '16px'
                }
            }, h(CustomControls)),

            h(RF.MiniMap, {
                key: 'minimap',
                nodeColor: (n) => n.type === 'modelNode' ? '#3b82f6' : '#10b981',
                nodeBorderRadius: 2,
                style: {
                    background: '#1e293b',
                    border: '1px solid #334155'
                }
            })
        ]);
    }

    // ============================================
    // MAIN WORKFLOW DAG COMPONENT (Exported)
    // ============================================
    window.WorkflowDAG = function({ workflow, workflowId }) {
        return h('div', {
            id: 'dag-container',              // ID for fullscreen target
            className: 'dag-container',       // Class for styling
            style: {
                width: '100%',
                height: '600px',              // Default height
                position: 'relative'
            }
        },
            h(RF.ReactFlowProvider, null,
                h(WorkflowDAGContent, { workflow, workflowId })
            )
        );
    };

    console.log('✓ WorkflowDAG component exported to window.WorkflowDAG');
    console.log('WorkflowDAG available?', typeof window.WorkflowDAG !== 'undefined');
})();
