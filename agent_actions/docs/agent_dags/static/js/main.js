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
            span.innerHTML = '<span class="icon">⚙️</span>' + item.name;
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
            ul.style.display = 'none'; // Hide nested folders initially
            li.appendChild(ul);
            parentElement.appendChild(li);
            renderFolderStructure(item.children, ul);
        } else if (item.type === 'file') {
            const span = document.createElement('span');
            span.className = 'file';
            span.innerHTML = '<span class="icon">📄</span>' + item.name;
            span.onclick = () => generateAgentLineage(item.path);
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
    const container = document.querySelector('.container');
    container.innerHTML = `<pre>${JSON.stringify(data, null, 2)}</pre>`;
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
        .attr("refX", 25)  // adjust this value to move arrowhead closer/further from the node
        .attr("refY", 0)
        .attr("markerWidth", 10)
        .attr("markerHeight", 10)
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
        .force("link", d3.forceLink(edges).id(d => d.id).distance(200))
        .force("charge", d3.forceManyBody().strength(-400))
        .force("x", d3.forceX(d => d.level * 200).strength(1))
        .force("y", d3.forceY(height / 2).strength(1))
        .force("center", d3.forceCenter(width / 2, height / 2));

    const link = svg.append("g")
        .attr("class", "links")
        .selectAll("line")
        .data(edges)
        .enter().append("line")
        .attr("class", "link")
        .attr("stroke", "#999")
        .attr("stroke-opacity", 0.6)
        .attr("stroke-width", 2)
        .attr("marker-end", "url(#end)");

    const node = svg.append("g")
        .attr("class", "nodes")
        .selectAll("g")
        .data(nodes)
        .enter().append("g")
        .attr("class", "node")
        .on("click", function(event, d) {
            fetchAgentDetails(filename, d.id);
        });

    node.append("rect")
        .attr("width", 150)
        .attr("height", 30)
        .attr("rx", 10)  // rounded corners
        .attr("ry", 10)
        .attr("fill", d => d3.schemeCategory10[d.id % 10]);

    node.append("text")
        .attr("dx", 75)
        .attr("dy", 20)
        .attr("text-anchor", "middle")
        .attr("fill", "#fff")
        .text(d => d.id);

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
            .attr("x2", d => d.target.x)
            .attr("y2", d => d.target.y);

        node
            .attr("transform", d => `translate(${d.x - 75},${d.y - 15})`);  // center the rectangles
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
        body: JSON.stringify({ filename, agent_name: agentName }),
    })
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            alert(data.error);
        } else {
            showModal(JSON.stringify(data, null, 2));
        }
    });
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

function showModal(content) {
    const modal = document.getElementById("customModal");
    const modalText = document.getElementById("modal-text");
    modalText.innerText = content;
    modal.style.display = "block";
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
