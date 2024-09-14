document.addEventListener('DOMContentLoaded', () => {
    loadYamlFiles();
    document.getElementById('search-bar').addEventListener('input', handleSearch);
    document.getElementById('search-button').addEventListener('click', handleSearch);
});

function loadYamlFiles() {
    fetch('/list_yaml_files')
        .then(response => response.json())
        .then(files => {
            const fileList = document.getElementById('file-list');
            fileList.innerHTML = '';
            renderFolderStructure(files, fileList);
        });
}

function renderFolderStructure(structure, parentElement) {
    structure.forEach(item => {
        const li = document.createElement('li');
        if (item.type === 'folder') {
            const span = document.createElement('span');
            span.className = 'folder';
            span.innerHTML = '<span class="icon">📁</span>' + item.name;
            span.onclick = () => {
                const ul = li.querySelector('ul');
                if (ul) {
                    ul.style.display = ul.style.display === 'none' ? 'block' : 'none';
                }
            };
            li.appendChild(span);
            const ul = document.createElement('ul');
            ul.style.listStyleType = 'none';
            ul.style.marginLeft = '20px';
            ul.style.display = 'none';
            li.appendChild(ul);
            parentElement.appendChild(li);
            renderFolderStructure(item.children, ul);
        } else if (item.type === 'file') {
            const span = document.createElement('span');
            span.className = 'file';
            span.innerHTML = '<span class="icon">📄</span>' + item.name;
            span.onclick = () => generateAgentLineage(item.path);
            span.setAttribute('data-path', item.path);  // Store the file path for later use
            li.appendChild(span);
            parentElement.appendChild(li);
        }
    });
}

function generateAgentLineage(filename) {
    fetch('/generate_agent_lineage', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ filename }),
    })
    .then(response => response.json())
    .then(data => {
        renderGraph(data.nodes, data.edges, filename);
    });
}

function fetchAgentDetails(filename, agentName) {
    fetch('/get_agent_details', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ filename, agentName }),
    })
    .then(response => response.json())
    .then(data => {
        displayAgentDetails(data);
    });
}

function displayAgentDetails(data) {
    const modal = document.getElementById("customModal");
    const modalText = document.getElementById("modal-text");
    modalText.innerHTML = `<pre><code class="yaml">${jsyaml.dump(data)}</code></pre>`;
    modal.style.display = "block";
    hljs.highlightAll();  // Highlight the code
}

function handleSearch() {
    const searchTerm = document.getElementById('search-bar').value.toLowerCase();
    const nodes = d3.selectAll(".nodes text");
    nodes.each(function(d) {
        const element = d3.select(this);
        const parent = d3.select(this.parentNode);
        if (d.id.toLowerCase().includes(searchTerm)) {
            element.style.fill = "red";
            parent.raise();
            centerNode(d);
        } else {
            element.style.fill = "#fff";
        }
    });
}

function centerNode(nodeData) {
    const svg = d3.select("svg");
    const width = +svg.attr("width");
    const height = +svg.attr("height");
    const x = width / 2 - nodeData.x;
    const y = height / 2 - nodeData.y;
    svg.transition().duration(750).call(
        d3.zoom().transform,
        d3.zoomIdentity.translate(x, y).scale(1)
    );
}

function renderGraph(nodes, edges, filename) {
    const svg = d3.select("svg"),
        width = +svg.attr("width"),
        height = +svg.attr("height");

    svg.selectAll("*").remove();  // Clear the previous graph

    // Define marker for arrowheads
    svg.append("defs").selectAll("marker")
        .data(["end"])
        .enter().append("marker")
        .attr("id", String)
        .attr("viewBox", "0 -5 10 10")
        .attr("refX", 12)  // adjust this value to move arrowhead closer/further from the node
        .attr("refY", 0)
        .attr("markerWidth", 6)
        .attr("markerHeight", 6)
        .attr("orient", "auto")
        .append("path")
        .attr("d", "M0,-5L10,0L0,5")
        .attr("fill", "#999");

    // Calculate levels for nodes
    const levels = {};
    let level = 0;
    nodes.forEach(node => {
        if (!levels[node.id]) {
            levels[node.id] = level++;
        }
        node.level = levels[node.id];
    });

    // Force simulation
    const simulation = d3.forceSimulation(nodes)
        .force("link", d3.forceLink(edges).id(d => d.id).distance(300))  // Increase distance between nodes
        .force("charge", d3.forceManyBody().strength(-500))  // Increase repulsion between nodes
        .force("x", d3.forceX(d => d.level * 300).strength(1))  // Increase horizontal spacing
        .force("y", d3.forceY(height / 2).strength(1));

    const g = svg.append("g");

    const link = g.append("g")
        .attr("class", "links")
        .selectAll("line")
        .data(edges)
        .enter().append("line")
        .attr("class", "link")
        .attr("stroke", "#999")
        .attr("stroke-opacity", 0.6)
        .attr("stroke-width", 2)
        .attr("marker-end", "url(#end)");

    const node = g.append("g")
        .attr("class", "nodes")
        .selectAll("g")
        .data(nodes)
        .enter().append("g")
        .attr("class", "node")
        .on("click", function(event, d) {
            fetchAgentDetails(filename, d.id);
        });

    node.append("rect")
        .attr("height", 30)
        .attr("rx", 5)  // rounded corners
        .attr("ry", 5)
        .attr("fill", "#f0f0f0")
        .attr("stroke", "#999")
        .attr("stroke-width", 1);

    node.append("text")
        .attr("dx", 10)
        .attr("dy", 20)
        .attr("text-anchor", "start")
        .attr("fill", "#000")
        .text(d => d.id)
        .each(function(d) {
            const bbox = this.getBBox();
            d.bbox = bbox;
        });

    node.select("rect")
        .attr("width", d => d.bbox.width + 20);  // Add padding to the text width

    simulation
        .nodes(nodes)
        .on("tick", ticked);

    simulation.force("link")
        .links(edges);

    setTimeout(() => {
        simulation.force("x", null)
                  .force("y", null);
    }, 1000);  // Allow forces to position nodes for 1 second, then remove the forces

    function ticked() {
        link
            .attr("x1", d => d.source.x)
            .attr("y1", d => d.source.y)
            .attr("x2", d => {
                const dx = d.target.x - d.source.x;
                const dy = d.target.y - d.source.y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                const offsetX = (dx / dist) * (d.target.bbox.width / 2 + 5);  // Adjust this value to move arrowhead closer/further from the node
                return d.target.x - offsetX;
            })
            .attr("y2", d => {
                const dx = d.target.x - d.source.x;
                const dy = d.target.y - d.source.y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                const offsetY = (dy / dist) * (d.target.bbox.height / 2 + 5);  // Adjust this value to move arrowhead closer/further from the node
                return d.target.y - offsetY;
            });

        node
            .attr("transform", d => `translate(${d.x - d.bbox.width / 2},${d.y - 15})`);  // center the rectangles

        // Center the graph
        const graphBBox = g.node().getBBox();
        const graphWidth = graphBBox.width;
        const graphHeight = graphBBox.height;
        const offsetX = (width - graphWidth) / 2 - graphBBox.x;
        const offsetY = (height - graphHeight) / 2 - graphBBox.y;
        g.attr("transform", `translate(${offsetX},${offsetY})`);
    }

    function dragstarted(event, d) {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
    }

    function dragged(event, d) {
        d.fx = event.x;
        d.fy = event.y;
    }

    function dragended(event, d) {
        if (!event.active) simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
    }

    node.call(d3.drag()
        .on("start", dragstarted)
        .on("drag", dragged)
        .on("end", dragended));
}