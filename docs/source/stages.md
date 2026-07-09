# ⚙️ Pipeline Stages

The Energy Pipeline is organized into **three types of stages**, each responsible for a part of the commit processing workflow.

Each stage operates on a shared **context dictionary** that allows reading and writing of state and data.

---

## 🧱 Stage Categories

| Stage Type      | Runs When?                              | Purpose                                       |
| --------------- | --------------------------------------- | --------------------------------------------- |
| Pre-Stages      | Once per batch (before any commits)     | Verify system setup before running any commit |
| Pre-Test Stages | Once per unique commit (in parallel)    | Prepare the environment and build the commit  |
| Batch Stages    | For every run of every commit (N times) | Run test and measure energy consumption       |

---

## 📦 Shared Context

Each stage receives a context object:

```python
context: dict[str, Any]
```

Common fields in context:

- `commit`: `git.Commit` object (or commit hash string in subprocesses)
- `repo_path`: path to local Git repo
- `build_failed`: `bool` flag set if a build fails
- `abort_pipeline`: `bool` flag to stop processing

---

## 🧩 Stage Interface

All stages implement the same interface via an abstract base class:

```python
class PipelineStage(ABC):
    @abstractmethod
    def run(self, context: dict[str, Any]) -> None: ...
```

---

## 🔍 Pre-Stages (run once per batch)

These are safety checks before anything is processed.

### ✅ `VerifyPerfStage`

- Verifies `perf` access permissions.
- Logs system state and capabilities.
- Aborts the pipeline if setup is incorrect.

---

## 🏗️ Pre-Test Stages (run once per commit, in parallel)

These prepare each commit for measurement. They run concurrently to speed up processing.

### 📁 `CopyDirectoryStage`

- Copies the repository to a fresh directory for this commit.
- Ensures isolation between batches.

### 🏷 `SetDirectoryStage`

- Sets the working directory in context to the correct copied repo path.

### 🌲 `CheckoutStage`

- Checks out the specified commit in the local copy of the repo.

### ☕ `JavaSetupStage`

- Detects Java version from Maven `pom.xml`.
- Sets environment variables to match that version.

### 🔨 `BuildStage`

- Builds the project using the test command.
- Marks the commit as `build_failed` in context if it fails.

---

## 🔁 Batch Stages (run for each execution of each commit)

These stages are run `num_runs * num_repeats` times per commit.

### 🌡️ `TemperatureCheckStage`

- Monitors CPU temperature.
- Waits or aborts if too hot (to avoid noise in energy readings).

### 📁 `SetDirectoryStage` *(again)*

- Redundant set for safety in parallel runs.

### ☕ `JavaSetupStage` *(again)*

- Re-applies Java settings to ensure consistent environment.

### ⚡ `MeasureEnergyStage`

- Runs the test command.
- Collects energy metrics from RAPL (e.g., `energy-pkg`, `energy-core`, `energy-gpu`).
- Saves them to a result file with the commit hash.

### 🧹 `PostTestStage`

- Cleans up temporary files or resets settings if needed.

---

## 🧠 Execution Flow Summary

```text
[Measure Command]
 └── Batches Commits (X batches of Y commits)
     └── For Each Batch:
         ├── Run Pre-Stages
         ├── For Each Unique Commit in Parallel:
         │   └── Pre-Test Stages (checkout, build, etc.)
         └── For Each Commit N times:
             └── Batch Stages (test, measure, etc.)
```

---

## ⚠️ Stage Aborts

Any stage can stop the pipeline by setting:

```python
context["abort_pipeline"] = True
```

Or, mark that a commit should be skipped due to a failed build:

```python
context["build_failed"] = True
```

---

## ✅ Adding New Stages

1. Create a new class implementing `PipelineStage`.
2. Add it to one of these lists in `main.py`:

    ```python
    pre_stages = [...]
    pre_test_stages = [...]
    batch_stages = [...]
    ```

3. The pipeline will pick it up automatically.

---

## 💡 Example: Writing a Custom Stage

```python
class LogCommitStage(PipelineStage):
    def run(self, context: dict[str, Any]) -> None:
        commit = context.get("commit")
        print(f"Processing commit: {commit}")
```

Then add to `batch_stages`:

```python
batch_stages = [
    TemperatureCheckStage(),
    LogCommitStage(),
    MeasureEnergyStage(),
]
```

---

## 📚 Related Files

| File                 | Purpose                               |
| -------------------- | ------------------------------------- |
| `stage_interface.py` | Defines the base class for all stages |
| `pipeline.py`        | Orchestrates the full pipeline logic  |
| `main.py`            | Entry point that registers all stages |

---

Need help writing your own custom stage? Just ask!
