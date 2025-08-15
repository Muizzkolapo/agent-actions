#!/usr/bin/env python3
"""
Test script to verify artifact system integration with workflow execution.
This creates a minimal workflow and runs it to test artifact generation.
"""

import os
import tempfile
import shutil
from pathlib import Path
import json
import yaml

def create_test_project():
    """Create a minimal test project structure."""
    
    # Create temporary directory
    test_dir = Path(tempfile.mkdtemp(prefix="agent_actions_test_"))
    print(f"Creating test project in: {test_dir}")
    
    # Create required directory structure
    # The agent runner looks for a directory with 'agent_io' as a child
    project_name = "TestAgent"
    project_dir = test_dir / project_name
    agent_io_dir = project_dir / "agent_io"
    staging_dir = agent_io_dir / "staging" 
    config_dir = test_dir / "agent_config"
    templates_dir = test_dir / "templates"
    defaults_dir = test_dir / "defaults"
    
    project_dir.mkdir(parents=True)
    agent_io_dir.mkdir(parents=True)
    staging_dir.mkdir(parents=True)
    config_dir.mkdir(parents=True)
    templates_dir.mkdir(parents=True)
    defaults_dir.mkdir(parents=True)
    
    # Create empty default config
    default_config = {"version": "1.0", "defaults": {}}
    with open(defaults_dir / "defaults.yml", "w") as f:
        yaml.dump(default_config, f)
    
    # Create simple test data
    test_data = {
        "message": "Hello, world!",
        "test_id": "artifact_test_001"
    }
    
    with open(staging_dir / "test_input.json", "w") as f:
        json.dump(test_data, f, indent=2)
    
    # Create a simple agent configuration that uses validation
    agent_config = {
        "TestAgent": [
            {
                "agent_type": "TestAgent",
                "model_vendor": "tool",  # Use tool vendor to avoid needing API keys
                "function_name": "simple_echo",  # Simple function that echoes input
                "interceptors": [
                    {
                        "type": "validation",
                        "config": {
                            "validator": "json_validator",
                            "on_failure": "continue",
                            "prompt_debug": True
                        }
                    }
                ]
            }
        ]
    }
    
    with open(config_dir / "TestAgent.yml", "w") as f:
        yaml.dump(agent_config, f, default_flow_style=False)
    
    # Create a simple tool function
    tools_dir = test_dir / "tools"
    tools_dir.mkdir()
    
    tool_code = '''
def simple_echo(data):
    """Simple echo function for testing."""
    import json
    if isinstance(data, str):
        try:
            parsed = json.loads(data)
            return {"echoed": parsed, "status": "success"}
        except:
            return {"echoed": data, "status": "success"}
    return {"echoed": data, "status": "success"}
'''
    
    with open(tools_dir / "test_tools.py", "w") as f:
        f.write(tool_code)
    
    return test_dir

def run_test_workflow(project_dir):
    """Run the test workflow and check for artifacts."""
    
    # Change to project directory
    original_cwd = os.getcwd()
    os.chdir(project_dir)
    
    try:
        # Import and run the workflow
        from agent_actions.workflow.agent_workflow import AgentWorkflow
        
        config_file = project_dir / "agent_config" / "TestAgent.yml"
        tools_dir = project_dir / "tools"
        
        print(f"\n🚀 Running test workflow...")
        print(f"Config file: {config_file}")
        print(f"Tools directory: {tools_dir}")
        
        # Create and run workflow
        workflow = AgentWorkflow(
            constructor_path=str(config_file),
            user_code_path=str(tools_dir),
            default_path=str(project_dir / "defaults" / "defaults.yml"),
            use_tools=True
        )
        
        print(f"Agent name: {workflow.agent_name}")
        print(f"Execution order: {workflow.execution_order}")
        
        # Run the workflow
        workflow.run()
        
        # Check for artifacts
        artifacts_dir = project_dir / "agent_io" / "artifacts"
        if artifacts_dir.exists():
            print(f"\n✅ Artifacts directory created: {artifacts_dir}")
            
            # List artifact files
            for artifact_file in artifacts_dir.glob("*.json"):
                print(f"   📄 {artifact_file.name} ({artifact_file.stat().st_size} bytes)")
                
                # Show content preview
                try:
                    with open(artifact_file) as f:
                        content = json.load(f)
                    print(f"      Preview: {str(content)[:200]}...")
                except Exception as e:
                    print(f"      Error reading: {e}")
            
            # Check run-specific artifacts
            runs_dir = artifacts_dir / "runs"
            if runs_dir.exists():
                run_dirs = list(runs_dir.glob("run_*"))
                if run_dirs:
                    latest_run = sorted(run_dirs)[-1]
                    print(f"\n   📁 Latest run directory: {latest_run.name}")
                    for run_file in latest_run.glob("*.json"):
                        print(f"      📄 {run_file.name}")
            
            return True
        else:
            print(f"\n❌ No artifacts directory found")
            return False
            
    except Exception as e:
        print(f"\n❌ Error running workflow: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        os.chdir(original_cwd)

def main():
    """Main test function."""
    print("🧪 Testing Agent Actions Artifact System Integration")
    print("=" * 60)
    
    # Create test project
    project_dir = create_test_project()
    
    try:
        # Run test workflow  
        success = run_test_workflow(project_dir)
        
        if success:
            print(f"\n🎉 Test PASSED! Artifacts were successfully generated.")
            print(f"📁 Test project preserved at: {project_dir}")
            print(f"   You can inspect the artifacts manually if needed.")
        else:
            print(f"\n❌ Test FAILED! Artifacts were not generated.")
            
    except Exception as e:
        print(f"\n💥 Test crashed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Preserve the test project for inspection
        print(f"\n📁 Test project preserved at: {project_dir}")
        print("   You can manually delete it if needed.")

if __name__ == "__main__":
    main()