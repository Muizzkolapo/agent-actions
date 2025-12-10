/**
 * DAG Data Transformer
 * Converts catalog workflow data to ReactFlow node/edge format with dagre layout
 */

// Extract provider from model name
function getProvider(model) {
    if (!model) return 'unknown';
    if (model.includes('gpt') || model.includes('o1') || model.includes('o3')) return 'openai';
    if (model.includes('claude')) return 'anthropic';
    if (model.includes('gemini')) return 'google';
    if (model.includes('llama') || model.includes('mistral')) return 'ollama';
    return 'unknown';
}

// Extract field mappings from action (defined early for use in buildNodesAndEdges)
function extractActionFields(action) {
    const raw = action.raw_yaml || {};
    const contextScope = raw.context_scope || {};

    // Extract input fields - keep original prefixed names for display
    let inputFields = [];
    let inputFieldMappings = []; // Track source action for each field

    if (raw.observe && Array.isArray(raw.observe)) {
        raw.observe.forEach(field => {
            inputFields.push(field);
            const parts = field.split('.');
            if (parts.length > 1) {
                inputFieldMappings.push({
                    displayField: field,
                    sourceAction: parts[0],
                    sourceField: parts.slice(1).join('.')
                });
            } else {
                inputFieldMappings.push({
                    displayField: field,
                    sourceAction: null,
                    sourceField: field
                });
            }
        });
    }

    if (contextScope.observe && Array.isArray(contextScope.observe)) {
        contextScope.observe.forEach(field => {
            inputFields.push(field);
            const parts = field.split('.');
            if (parts.length >= 2) {
                inputFieldMappings.push({
                    displayField: field,
                    sourceAction: parts[0],
                    sourceField: parts.slice(1).join('.')
                });
            } else {
                inputFieldMappings.push({
                    displayField: field,
                    sourceAction: null,
                    sourceField: field
                });
            }
        });
    }

    if (contextScope.passthrough && Array.isArray(contextScope.passthrough)) {
        contextScope.passthrough.forEach(field => {
            inputFields.push(field);
            const parts = field.split('.');
            if (parts.length > 1) {
                inputFieldMappings.push({
                    displayField: field,
                    sourceAction: parts[0],
                    sourceField: parts.slice(1).join('.')
                });
            } else {
                inputFieldMappings.push({
                    displayField: field,
                    sourceAction: null,
                    sourceField: field
                });
            }
        });
    }

    inputFields = [...new Set(inputFields)];

    // Fallback: use action.inputs from catalog if no fields extracted
    if (inputFields.length === 0 && action.inputs && Array.isArray(action.inputs)) {
        inputFields = action.inputs;
        // Build mappings for catalog inputs
        action.inputs.forEach(field => {
            const parts = field.split('.');
            if (parts.length >= 2) {
                inputFieldMappings.push({
                    displayField: field,
                    sourceAction: parts[0],
                    sourceField: parts.slice(1).join('.')
                });
            }
        });
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
            outputFields = Object.keys(schema);
        }
    }
    if (contextScope.passthrough && Array.isArray(contextScope.passthrough)) {
        contextScope.passthrough.forEach(field => {
            const parts = field.split('.');
            const fieldName = parts.length > 1 ? parts.slice(1).join('.') : field;
            outputFields.push(fieldName);
        });
    }
    outputFields = [...new Set(outputFields)];

    // Fallback: use action.output_fields from catalog if no fields extracted
    if (outputFields.length === 0 && action.output_fields && Array.isArray(action.output_fields)) {
        outputFields = action.output_fields.map(field => field.name);
    }

    // Extract dropped fields
    let droppedFields = [];
    if (raw.drops && Array.isArray(raw.drops)) {
        droppedFields = droppedFields.concat(raw.drops);
    }
    if (contextScope.drop && Array.isArray(contextScope.drop)) {
        droppedFields = droppedFields.concat(contextScope.drop);
    }
    droppedFields = [...new Set(droppedFields)];

    return { inputFields, outputFields, droppedFields, inputFieldMappings };
}

// Build nodes and edges from workflow actions
function buildNodesAndEdges(workflow) {
    const nodes = [];
    const edges = [];
    let edgeId = 0;

    Object.values(workflow.actions).forEach(action => {
        // Determine provider based on action type
        const provider = action.type === 'llm'
            ? getProvider(action.model)
            : 'Tool';

        // Extract field information
        const { inputFields, outputFields, droppedFields } = extractActionFields(action);

        // Create ReactFlow node
        nodes.push({
            id: action.name,
            type: action.type === 'llm' ? 'modelNode' : 'toolNode',
            data: {
                label: action.name,
                model: action.model || 'unknown',
                provider: provider,
                impl: action.impl || action.granularity || 'tool',
                description: action.intent || '',
                isOperational: true, // Can extend with real status later
                // Add field information
                inputFields: inputFields,
                outputFields: outputFields,
                droppedFields: droppedFields,
                // Add plan status
                inPlan: action.in_plan !== false, // Default to true if not specified
                planOrder: action.plan_order || null
            },
            position: { x: 0, y: 0 } // Will be set by dagre
        });

        // Create edges from dependencies
        (action.dependencies || []).forEach((dep) => {
            edges.push({
                id: `e${edgeId++}`,
                source: dep,
                target: action.name,
                type: 'smoothstep',
                animated: true,
                style: { stroke: '#3b82f6', strokeWidth: 2 }
            });
        });
    });

    return { nodes, edges };
}

// Apply dagre layout algorithm
function applyDagreLayout(nodes, edges, direction = 'LR') {
    const dagreGraph = new dagre.graphlib.Graph();
    dagreGraph.setDefaultEdgeLabel(() => ({}));

    // Configure graph layout with better spacing
    dagreGraph.setGraph({
        rankdir: direction,        // Layout direction (LR = left-to-right, TB = top-to-bottom)
        nodesep: 120,              // Horizontal spacing between nodes in same rank (increased from default 50)
        ranksep: 200,              // Vertical spacing between ranks/levels (increased from default 50)
        edgesep: 80,               // Spacing between edges (increased from default 10)
        marginx: 50,               // Margin on x-axis
        marginy: 50                // Margin on y-axis
    });

    // Add nodes to dagre with updated dimensions to match our bigger nodes
    nodes.forEach(node => {
        dagreGraph.setNode(node.id, { width: 350, height: 140 });  // Match our actual node size (was 180x100)
    });

    // Add edges to dagre
    edges.forEach(edge => {
        dagreGraph.setEdge(edge.source, edge.target);
    });

    // Calculate layout
    dagre.layout(dagreGraph);

    // Apply positions to nodes
    return {
        nodes: nodes.map(node => {
            const positioned = dagreGraph.node(node.id);
            return {
                ...node,
                position: {
                    x: positioned.x - 175,  // Center the node (half of 350px width)
                    y: positioned.y - 70    // Center the node (half of 140px height)
                }
            };
        }),
        edges: edges
    };
}

// Main transformer function - exposed globally
window.transformWorkflowToReactFlow = function(workflow, direction = 'LR') {
    const { nodes, edges } = buildNodesAndEdges(workflow);
    return applyDagreLayout(nodes, edges, direction);
};

// ============================================
// Lineage TRANSFORMER
// ============================================

// Build field-to-field edges based on field name matching and explicit mappings
function buildFieldToFieldEdges(actions) {
    const edges = [];
    let edgeId = 0;

    // Create a map of action outputs and field mappings for quick lookup
    const actionOutputs = new Map();
    const actionFieldMappings = new Map();

    actions.forEach(action => {
        const { outputFields, inputFieldMappings } = extractActionFields(action);
        actionOutputs.set(action.name, new Set(outputFields));
        actionFieldMappings.set(action.name, inputFieldMappings || []);
    });

    // For each action, connect fields based on explicit mappings
    actions.forEach(action => {
        const fieldMappings = actionFieldMappings.get(action.name) || [];

        fieldMappings.forEach(mapping => {
            if (mapping.sourceAction) {
                // Explicitly mapped field (e.g., "fact_extractor.candidate_facts_list")
                const sourceOutputs = actionOutputs.get(mapping.sourceAction);
                if (sourceOutputs && sourceOutputs.has(mapping.sourceField)) {
                    edges.push({
                        id: `field-e${edgeId++}`,
                        source: mapping.sourceAction,
                        sourceHandle: `output-${mapping.sourceField}`,
                        target: action.name,
                        targetHandle: `input-${mapping.displayField}`,
                        type: 'smoothstep',
                        animated: false,
                        style: {
                            stroke: '#f59e0b',
                            strokeWidth: 2.5
                        },
                        label: mapping.sourceField,
                        labelStyle: {
                            fontSize: '10px',
                            fill: '#92400e',
                            fontWeight: 600
                        },
                        labelBgStyle: {
                            fill: '#ffffff',
                            fillOpacity: 0.95
                        }
                    });
                }
            } else {
                // Implicit mapping - try to match with direct dependencies
                const deps = action.dependencies || [];
                const inputField = mapping.displayField;

                deps.forEach(depName => {
                    const depOutputs = actionOutputs.get(depName);
                    if (depOutputs) {
                        // Try exact match first
                        if (depOutputs.has(inputField)) {
                            edges.push({
                                id: `field-e${edgeId++}`,
                                source: depName,
                                sourceHandle: `output-${inputField}`,
                                target: action.name,
                                targetHandle: `input-${inputField}`,
                                type: 'smoothstep',
                                animated: false,
                                style: {
                                    stroke: '#f59e0b',
                                    strokeWidth: 2
                                },
                                label: inputField,
                                labelStyle: {
                                    fontSize: '10px',
                                    fill: '#92400e'
                                },
                                labelBgStyle: {
                                    fill: '#ffffff',
                                    fillOpacity: 0.9
                                }
                            });
                        } else {
                            // Check for nested field matches (e.g., "source.page_content" matches "page_content")
                            const fieldParts = inputField.split('.');
                            const fieldName = fieldParts[fieldParts.length - 1];

                            if (depOutputs.has(fieldName)) {
                                edges.push({
                                    id: `field-e${edgeId++}`,
                                    source: depName,
                                    sourceHandle: `output-${fieldName}`,
                                    target: action.name,
                                    targetHandle: `input-${inputField}`,
                                    type: 'smoothstep',
                                    animated: false,
                                    style: {
                                        stroke: '#f59e0b',
                                        strokeWidth: 2,
                                        strokeDasharray: '5,5'
                                    },
                                    label: fieldName,
                                    labelStyle: {
                                        fontSize: '10px',
                                        fill: '#92400e'
                                    },
                                    labelBgStyle: {
                                        fill: '#ffffff',
                                        fillOpacity: 0.9
                                    }
                                });
                            }
                        }
                    }
                });
            }
        });
    });

    return edges;
}

// Build nodes for Lineage view
function buildFieldLineageNodes(workflow) {
    const nodes = [];
    const actions = Object.values(workflow.actions);

    actions.forEach(action => {
        const { inputFields, outputFields, droppedFields } = extractActionFields(action);

        nodes.push({
            id: action.name,
            type: 'fieldActionNode',
            data: {
                label: action.name,
                type: action.type,
                inputFields: inputFields,
                outputFields: outputFields,
                droppedFields: droppedFields,
                initiallyExpanded: false // Start collapsed
            },
            position: { x: 0, y: 0 } // Will be set by dagre
        });
    });

    return nodes;
}

// Main Lineage transformer
window.transformWorkflowToFieldLineage = function(workflow, direction = 'LR') {
    const nodes = buildFieldLineageNodes(workflow);
    const actions = Object.values(workflow.actions);
    const edges = buildFieldToFieldEdges(actions);

    // Apply dagre layout with larger spacing for field nodes
    const dagreGraph = new dagre.graphlib.Graph();
    dagreGraph.setDefaultEdgeLabel(() => ({}));
    dagreGraph.setGraph({
        rankdir: direction,
        nodesep: 180, // Horizontal spacing between nodes (increased)
        ranksep: 350, // Vertical spacing between ranks (increased)
        marginx: 60,  // Margin around the graph
        marginy: 60
    });

    // Add nodes to dagre with proper dimensions for collapsed state
    nodes.forEach(node => {
        // Use collapsed dimensions - nodes will expand in place when clicked
        dagreGraph.setNode(node.id, { width: 320, height: 90 });
    });

    // Add edges to dagre
    edges.forEach(edge => {
        dagreGraph.setEdge(edge.source, edge.target);
    });

    // Calculate layout
    dagre.layout(dagreGraph);

    // Apply positions to nodes
    const positionedNodes = nodes.map(node => {
        const positioned = dagreGraph.node(node.id);
        return {
            ...node,
            position: {
                x: positioned.x - 160, // Center the node (half of width 320/2)
                y: positioned.y - 45   // Center vertically (half of height 90/2)
            }
        };
    });

    return { nodes: positionedNodes, edges };
};
