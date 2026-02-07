import logging
from pathlib import Path
from agent_actions.workflow.runner import AgentRunner

# Mock Logger
logging.basicConfig(level=logging.DEBUG)


def test_dependency_resolution():
    runner = AgentRunner(use_tools=False)

    # Mock agent folder
    agent_folder = "/tmp/mock_agent_folder"
    Path(agent_folder).mkdir(parents=True, exist_ok=True)

    print("--- Test 1: Start Node (Index 0) ---")
    config_0 = {"agent_type": "start_agent", "dependencies": []}
    upstream_dirs, output_dir = runner.setup_directories(agent_folder, config_0, None, 0)
    print(f"Inputs: {upstream_dirs}")
    assert len(upstream_dirs) == 1
    assert str(Path(agent_folder) / "staging") in upstream_dirs[0]

    print("\n--- Test 2: Linear Node (Index 1, No Deps) ---")
    config_1 = {"agent_type": "linear_agent"}
    upstream_dirs, output_dir = runner.setup_directories(agent_folder, config_1, "start_agent", 1)
    print(f"Inputs: {upstream_dirs}")
    assert len(upstream_dirs) == 1
    # Uses simple directory name (no index prefix)
    assert "start_agent" in upstream_dirs[0]

    print("\n--- Test 3: Diamond Merge Node (Explicit Deps) ---")
    # Simulate a workflow where 'agent_A' (idx 1) and 'agent_B' (idx 2) feed into 'merge_agent' (idx 3)
    runner.agent_indices = {"agent_A": 1, "agent_B": 2}

    # Create target dirs so dependency resolution finds them
    (Path(agent_folder) / "target" / "agent_A").mkdir(parents=True, exist_ok=True)
    (Path(agent_folder) / "target" / "agent_B").mkdir(parents=True, exist_ok=True)

    config_merge = {
        "agent_type": "merge_agent",
        "dependencies": ["agent_A", "agent_B"],
        "reduce_key": "id",  # Aggregation pattern — merges all deps
    }

    upstream_dirs, output_dir = runner.setup_directories(agent_folder, config_merge, "agent_B", 3)
    print(f"Inputs: {upstream_dirs}")

    assert len(upstream_dirs) == 2
    # Uses simple directory names (no index prefix)
    assert any("agent_A" in d for d in upstream_dirs)
    assert any("agent_B" in d for d in upstream_dirs)

    print("\n--- VERIFICATION SUCCESSFUL ---")


if __name__ == "__main__":
    test_dependency_resolution()
