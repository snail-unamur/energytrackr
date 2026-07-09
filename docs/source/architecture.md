# 🏗️ Pipeline Architecture

This document provides a deeper look at the internal architecture of the Energy Measurement Pipeline, explaining its stage-based design, execution flow, and extensibility mechanisms.

---

## ⚙️ Modular Stage Pipeline

The pipeline is implemented as a **pipe-and-filter** model composed of modular units called **stages**. Each stage performs a focused task and passes control to the next stage via a shared `context`.

Each stage implements the same interface:

```python
class PipelineStage(ABC):
    @abstractmethod
    def run(self, context: dict[str, Any]) -> None: ...
```

---

## 🧱 Stage Categories

Stages are grouped by when and how often they are executed:

| Stage Type        | Frequency                   | Example Tasks            |
| ----------------- | --------------------------- | ------------------------ |
| `Pre-Stages`      | Once per batch              | Check RAPL/perf access   |
| `Pre-Test Stages` | Once per unique commit      | Checkout, compile, setup |
| `Batch Stages`    | Repeated for every test run | Measure energy, cleanup  |

---

## 🔁 Execution Flow

```text
Pipeline (per batch)
├── Pre-Stages (1x)
│   └── e.g. VerifyPerfStage
├── Pre-Test Stages (1x per commit, parallelized)
│   ├── CheckoutStage
│   ├── BuildStage
│   └── JavaSetupStage
└── Batch Stages (N x per commit)
    ├── TemperatureCheckStage
    ├── MeasureEnergyStage
    └── PostTestStage
```

This model enables:

- ✅ Pre-building commits once and reusing them
- ✅ Concurrent stage execution where safe
- ✅ Fine-grained extensibility per stage group

---

## 🧠 Shared Context

All stages receive a `context: dict[str, Any]` which allows:

- Passing commit information
- Communicating control signals (`abort_pipeline`, `build_failed`, etc.)
- Sharing paths, results, and state between stages

Example usage:

```python
context["build_failed"] = True
context["abort_pipeline"] = True
```

---

## 🔌 Plugin System for Stages

Each stage is a self-contained Python class and can be loaded dynamically from user-defined files.

### Requirements for a Custom Stage

- Inherits from `PipelineStage`
- Implements `run(context: dict)` method
- Exposes `get_stage()` function (used for dynamic loading)

### Example

```python
# modules/python_env_stage.py
class PythonEnvStage(PipelineStage):
    def run(self, context: dict[str, Any]) -> None:
        os.system("pip install -r requirements.txt")


def get_stage():
    return PythonEnvStage()
```

Then include it in your config:

```json
"modules_enabled": ["python_env_stage.py"]
```

---

## 📁 Directory Layout

```text
.
├── main.py               # CLI entry point
├── pipeline/             # Pipeline engine and interfaces
│   ├── core_stages/      # Built-in stages (checkout, measure, etc.)
│   ├── pipeline.py       # Orchestrator for stages
│   └── stage_interface.py
├── modules/              # Optional user-defined custom stages
├── config/               # Config models (Pydantic)
├── plot.py               # Plotting results
├── sort.py               # Sort results by Git history
├── system_setup.sh       # System preparation script
```

---

## 🛠 Example Execution Flow (High-Level)

```text
main.py measure → load config → prepare repo
        ↓
   gather commits + batch them
        ↓
Run pre-stages (e.g. perf check)
        ↓
Run pre-test stages (in parallel):
    - Checkout → Build → JavaSetup
        ↓
For each commit:
    Repeat batch stages (MeasureEnergy, PostTest) N times
        ↓
Restore repo HEAD
```

---

## 💡 Design Principles

| Principle            | Implementation                             |
| -------------------- | ------------------------------------------ |
| **Modularity**       | Each stage is an isolated Python class     |
| **Extensibility**    | Users can add their own stages dynamically |
| **Separation**       | Config-driven behavior, no hardcoded logic |
| **Reproducibility**  | Deterministic commit batching + reuse      |
| **Minimal coupling** | Context dictionary avoids global state     |

---

## 🔄 Parallelism Strategy

- Pre-Test stages for different commits are executed in **parallel** using `ProcessPoolExecutor`
- Batch stages are run **sequentially per commit** to preserve measurement integrity

---

## 🚀 Optimization Ideas (Planned)

- [ ] Detect and skip already measured commits
- [ ] Smart batching based on CPU temperature
- [ ] Reuse compiled artifacts across sessions
- [ ] Live log dashboards
- [ ] Advanced scheduling policies

---

## 🔍 Related Files

| File                 | Role                             |
| -------------------- | -------------------------------- |
| `pipeline.py`        | Batching logic + stage execution |
| `stage_interface.py` | Defines the `PipelineStage` base |
| `main.py`            | CLI dispatcher for all commands  |
| `plot.py`            | Graphical analysis of results    |

---

Want to extend the pipeline with new features or support a new language? Just drop your custom logic in a stage file and plug it into the config!
