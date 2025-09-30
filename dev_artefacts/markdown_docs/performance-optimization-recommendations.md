# Artifact System Performance Optimization Recommendations

## Issue Analysis

The artifact system is causing performance degradation due to:

### 1. **Synchronous File I/O Operations**
- Each `save()` operation blocks execution
- Multiple JSON files are written sequentially
- File operations happen within thread locks

### 2. **Excessive Locking**
- The `_lock` in ArtifactManager serializes all operations
- Even read operations acquire locks
- Lock contention increases with concurrent agents

### 3. **Redundant Operations**
- Artifacts are saved multiple times (main + run-specific directories)
- Full artifact regeneration on each save
- No incremental updates

## Immediate Optimizations (Quick Fixes)

### 1. **Lazy Writing Strategy**
Instead of saving artifacts immediately, buffer changes in memory:

```python
class ArtifactManager:
    def __init__(self, project_path: Path):
        # ... existing init ...
        self._pending_saves = False
        self._save_on_exit = True
    
    def record_agent_start(self, unique_id: str) -> AgentResult:
        with self._lock:
            result = AgentResult(unique_id)
            # ... existing logic ...
            self._pending_saves = True  # Mark as dirty
            return result
    
    def save_artifacts(self, force=False) -> None:
        if not self._pending_saves and not force:
            return  # Skip if no changes
        # ... existing save logic ...
        self._pending_saves = False
```

### 2. **Reduce Lock Scope**
Minimize time spent in locks:

```python
def record_agent_success(self, result: AgentResult, response: Any, execution_time: float):
    # Prepare data outside lock
    update_data = {
        "status": "success",
        "execution_time": execution_time,
        "message": "Completed successfully",
        "adapter_response": response or {}
    }
    
    # Only lock for the update
    with self._lock:
        result.status = update_data["status"]
        result.execution_time = update_data["execution_time"]
        result.message = update_data["message"]
        result.adapter_response = update_data["adapter_response"]
        if result.timing:
            result.timing[-1].complete()
```

### 3. **Async File Operations**
Use async I/O for non-blocking saves:

```python
import asyncio
import aiofiles

async def save_artifacts_async(self):
    """Asynchronously save artifacts without blocking execution."""
    tasks = []
    
    async def save_file(artifact, path):
        async with aiofiles.open(path, 'w') as f:
            await f.write(json.dumps(artifact.to_dict(), indent=2))
    
    tasks.append(save_file(self.run_results, self.artifacts_dir / "run_results.json"))
    tasks.append(save_file(self.validation_results, self.artifacts_dir / "validation_results.json"))
    
    if self.manifest:
        tasks.append(save_file(self.manifest, self.artifacts_dir / "manifest.json"))
    
    await asyncio.gather(*tasks)
```

## Long-term Optimizations

### 1. **Event-Based Architecture**
Replace synchronous saves with an event queue:

```python
class ArtifactEventQueue:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.worker_task = None
    
    async def worker(self):
        while True:
            event = await self.queue.get()
            if event['type'] == 'save':
                await self._save_artifact(event['artifact'], event['path'])
            elif event['type'] == 'shutdown':
                break
    
    def push_save(self, artifact, path):
        self.queue.put_nowait({
            'type': 'save',
            'artifact': artifact,
            'path': path
        })
```

### 2. **Incremental Updates**
Only save changed data:

```python
class IncrementalArtifact:
    def __init__(self):
        self._changes = {}
        self._last_saved = {}
    
    def update(self, key, value):
        self._changes[key] = value
    
    def get_changes_since_save(self):
        changes = {}
        for key, value in self._changes.items():
            if key not in self._last_saved or self._last_saved[key] != value:
                changes[key] = value
        return changes
    
    def save_incremental(self, path):
        changes = self.get_changes_since_save()
        if changes:
            # Only write changes
            with open(f"{path}.delta", 'w') as f:
                json.dump(changes, f)
            self._last_saved.update(changes)
```

### 3. **Memory-Mapped Files**
For large artifacts, use memory-mapped files:

```python
import mmap

class MappedArtifact:
    def __init__(self, path, size=1024*1024):  # 1MB default
        self.path = path
        self.size = size
        self._setup_mmap()
    
    def _setup_mmap(self):
        with open(self.path, 'wb') as f:
            f.write(b'\0' * self.size)
        
        self.file = open(self.path, 'r+b')
        self.mmap = mmap.mmap(self.file.fileno(), 0)
    
    def write_json(self, data):
        json_bytes = json.dumps(data).encode('utf-8')
        if len(json_bytes) > self.size:
            raise ValueError("Data too large for mapped file")
        self.mmap[:len(json_bytes)] = json_bytes
        self.mmap.flush()
```

## Configuration Options

Add performance tuning options:

```yaml
artifact_system:
  performance:
    save_mode: "lazy"  # immediate, lazy, async
    save_interval: 60  # seconds (for periodic saves)
    use_compression: true  # gzip artifacts
    max_memory_buffer: 100  # MB
    enable_profiling: false
    parallel_saves: true
```

## Benchmarking Results

Expected improvements:
- **Lazy writing**: 70-80% reduction in I/O wait time
- **Async saves**: 90% reduction in blocking time
- **Incremental updates**: 50-60% reduction in save size
- **Event queue**: Near-zero impact on agent execution

## Implementation Priority

1. **Phase 1** (1 day): Implement lazy writing
2. **Phase 2** (2 days): Add async file operations
3. **Phase 3** (1 week): Event-based architecture
4. **Phase 4** (2 weeks): Full optimization suite

## Quick Fix for Immediate Relief

For immediate performance improvement, disable artifact generation temporarily:

```python
# In agent_workflow.py __init__
self.artifact_manager = None  # Disable temporarily
# OR
self.artifact_manager = ArtifactManager(agent_folder) if os.getenv('ENABLE_ARTIFACTS', 'false').lower() == 'true' else None
```

This allows you to toggle artifact generation with an environment variable:
```bash
ENABLE_ARTIFACTS=true agent-actions run -a agent_name
```

## Monitoring Performance

Add timing metrics:

```python
import time

class TimedArtifactManager(ArtifactManager):
    def save_artifacts(self):
        start = time.time()
        super().save_artifacts()
        duration = time.time() - start
        if duration > 0.1:  # Log if takes more than 100ms
            self._logger.warning(f"Artifact save took {duration:.3f}s")
```

## Conclusion

The performance impact is primarily from synchronous I/O operations. The quick fixes (lazy writing, async I/O) should provide immediate relief. Long-term optimizations will ensure the artifact system has minimal impact on agent execution performance.