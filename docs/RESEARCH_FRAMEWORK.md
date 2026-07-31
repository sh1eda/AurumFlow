# Research Framework Architecture

## Scope

TASK 001 establishes research infrastructure only. It does not define or test a
market concept, generate a signal, simulate a trade, optimize parameters, train
a model, or change the existing `xauusd_signal` package.

The framework implements the lifecycle and reporting rules in
`MASTER_RESEARCH_SPECIFICATION.md` and provides extension points for the
candidate inventory in `RESEARCH_CATALOG.md`.

## Repository layout

```text
.
├── aurumflow_research/           # Reusable research infrastructure
│   ├── config.py                 # Central TOML configuration and overrides
│   ├── data.py                   # Source-neutral market-data interface
│   ├── discovery.py              # Manifest-based object/experiment discovery
│   ├── models.py                 # Stable lifecycle and evidence contracts
│   ├── reporting.py              # Automatic Markdown and JSON artifacts
│   ├── runner.py                 # Isolated execution and provenance capture
│   ├── structured_logging.py     # Per-run JSON Lines logs
│   └── cli.py                    # Catalog and experiment commands
├── config/
│   └── research.toml             # Versioned central defaults and paths
├── research/
│   ├── HTF_BIAS/                 # Placeholder object + lifecycle manifest
│   ├── LIQUIDITY/
│   ├── DELIVERY_ARRAYS/
│   ├── SESSION_STRUCTURE/
│   ├── ENGINEERED_LIQUIDITY/
│   ├── SMT/
│   ├── OTE/
│   ├── ENTRY_VALIDATION/
│   └── _template/                # Object and experiment templates
├── research_outputs/             # Ignored, run-isolated generated artifacts
└── tests/test_research_framework.py
```

Existing research files remain untouched. Only directories containing
`object.toml` participate in the new catalog, and only files named
`experiment.toml` are executable experiment registrations.

## Architecture

```text
config/research.toml
        │
        ├── resolves paths and named data-source drivers
        │
research/**/object.toml
        │
        └── research/**/experiment.toml ── imports module:run
                                               │
                                               ▼
                                      ExperimentRunner
                                      ├── run-scoped config
                                      ├── seeded random generator
                                      ├── recording data access
                                      ├── JSONL logger
                                      └── isolated output directory
                                               │
                                               ▼
                               report.md + four JSON artifacts + log
```

The framework depends inward on generic contracts. Research modules depend on
the framework, but the framework never imports a market concept by name. A new
object is therefore data, not a core-code branch.

## Design decisions

### Separate package and output root

Research infrastructure lives in `aurumflow_research`, not
`xauusd_signal`. This enforces the master specification's production-separation
rule and avoids accidental changes to current strategy or execution behavior.
Generated runs use `research_outputs/<object>/<namespace>/<run-id>/`, which
prevents experiments and reruns from overwriting one another. The whole output
root is ignored by Git.

### Manifests instead of a central registry

`object.toml` and `experiment.toml` files are discovered recursively. A central
Python switch statement would require a framework edit for every concept. A
manifest keeps metadata, lifecycle, configuration, entry point, and output
namespace next to the experiment that owns them. Duplicate IDs and references
to unknown objects fail during discovery.

### Mandatory scientific metadata

An experiment cannot be discovered unless its manifest declares:

- a neutral hypothesis;
- a measurable definition;
- required data;
- success and failure criteria;
- a validation method;
- known limitations;
- a versioned entry point and output namespace.

The return contract always reports sample size, bootstrap confidence intervals,
robustness checks, sensitivity analysis, data exclusions, and limitations.
Accepted or rejected results are rejected by the framework if the primary
evidence fields are absent. Insufficient evidence can be reported as
`inconclusive`; execution failure is recorded as `failed` and never converted
into a scientific conclusion.

### Source-neutral data access

Experiments request a named source from `context.data`; they do not construct a
CSV reader, broker adapter, database client, or vendor SDK. Source drivers are
configured by `module:attribute` import path. Adding a Parquet, SQL, API, or
other source requires a new driver and one configuration entry, not an
experiment edit or framework branch.

The included CSV driver is deliberately narrow. It reads a file without market
interpretation and records SHA-256, file metadata, row count, columns, request,
and UTC load time. It does not normalize prices, label events, calculate market
features, or repair source data. Every dataset read through `context.data` is
automatically included in execution metadata.

### Central, reproducible configuration

`config/research.toml` is the versioned default. Paths resolve relative to its
declared project root rather than the caller's current directory. A different
file can be passed with `--config` or selected with
`AURUMFLOW_RESEARCH_CONFIG`. Resolution order for experiment parameters is:

1. central `[experiment_defaults]`;
2. the experiment's `[parameters]` table;
3. explicit `--param key=value` overrides.

The resolved configuration is written to every run and hashed into execution
metadata. This makes parameter drift visible while allowing future
parameterization without hardcoded paths or values.

### Run-scoped state and structured logs

The runner supplies each experiment with a unique output directory, immutable
metadata, a deterministic `random.Random` instance seeded from central config,
a recording data facade, and a bound logger. It does not modify process-wide
random state or global logging handlers. Each log line is JSON with UTC time,
level, run ID, object ID, experiment ID, event, and structured fields.

### Framework-owned reports

Report generation is not optional experiment code. A completed or failed run
automatically receives:

| Artifact | Purpose |
| --- | --- |
| `report.md` | Human-readable hypothesis, result, evidence, configuration, and input provenance |
| `summary.json` | Machine-readable experiment and result summary |
| `execution_metadata.json` | Timestamps, duration, seed, configuration hash, runtime, Git state, and inputs |
| `research_status.json` | Explicit accepted, rejected, inconclusive, or failed status and rationale |
| `resolved_configuration.json` | Exact central and experiment configuration used |
| `run.log.jsonl` | Structured execution log |

Failure paths generate the same artifact set. This preserves negative and
operational outcomes and prevents silent, partial runs.

## Research-object lifecycle

Object manifests use one lifecycle value:

```text
candidate_definition
  -> objective_detection
  -> feature_engineering
  -> statistical_evaluation
  -> robustness_testing
  -> decided
```

The research decision is tracked separately as `not_evaluated`, `accepted`,
`rejected`, or `inconclusive`. Separation is intentional: progress through an
implementation lifecycle is not evidence of validity. Only a `decided` object
may be accepted or rejected.

All catalog objects created in TASK 001 remain `candidate_definition` and
`not_evaluated`.

## Add a research object without changing the framework

1. Copy `research/_template/object.toml.example` into
   `research/<OBJECT_ID>/object.toml`.
2. Fill in the catalog reference, neutral objective, layer, lifecycle, and
   decision.
3. Create `research/<OBJECT_ID>/experiments/<EXPERIMENT_ID>/`.
4. Copy the experiment manifest and module templates into that directory,
   removing the `.example` suffix.
5. Implement only the registered question in the module's `run(context)`
   function.
6. Add experiment-specific tests beside the module or under `tests/`.
7. Confirm discovery before execution:

```bash
aurumflow-research list-objects
aurumflow-research list-experiments
```

No file under `aurumflow_research/` changes in this workflow.

## Experiment entry-point contract

The manifest uses `module:callable` syntax. The callable receives one
`ExperimentContext` and must return `ExperimentResult`:

```python
from aurumflow_research import ExperimentResult, ResearchDecision


def run(context):
    data = context.data.load("local_csv", request)
    context.logger.info("data_loaded", "Input loaded", rows=len(data.frame))
    # The future experiment performs its isolated, preregistered analysis here.
    return ExperimentResult(
        summary="...",
        research_status=ResearchDecision.INCONCLUSIVE,
        status_rationale="...",
        sample_size=0,
        bootstrap_confidence_intervals={},
        robustness_checks=[],
        sensitivity_analysis=[],
        data_exclusions=[],
        limitations=["..."],
    )
```

`context.parameters` is the resolved experiment configuration;
`context.output_dir` is the only location where the experiment should write
additional artifacts; `context.random` is the seeded generator; and
`context.data` is the provenance-recording data interface.

## Commands

```bash
# From the repository or any descendant directory
python -m aurumflow_research list-objects
python -m aurumflow_research list-experiments

# Once a future experiment manifest and module exist
python -m aurumflow_research run EXPERIMENT_ID \
  --param bootstrap_resamples=20000 \
  --param filters.session='"new_york"'
```

The installed console command is `aurumflow-research`. `--param` values accept
JSON scalars, arrays, and objects; unquoted values that are not JSON are treated
as strings.

## Deliberate omissions

TASK 001 does not include a sample market experiment because even a convenient
example could be mistaken for an endorsed definition. Tests exercise the full
runner with a synthetic infrastructure-only callable instead. The framework
also omits schedulers, databases, distributed workers, notebooks, orchestration
services, and plugin frameworks until research volume demonstrates a need for
them.
