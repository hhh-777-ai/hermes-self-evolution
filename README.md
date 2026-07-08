# Hermes Self-Evolution Framework

> An autonomous self-improvement system for AI Agents — observe, diagnose, evolve, verify, learn.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

## What Is This?

A framework that lets your AI Agent **evolve itself**. Not just run tasks — but observe its own behavior, find patterns in its failures, generate fixes, apply them, and verify the results. A closed-loop autonomous improvement system.

Built on top of [Hermes Agent](https://github.com/NousResearch/hermes-agent), but the architecture is model-agnostic.

```
┌─────────────────────────────────────────────────────────┐
│                   Self-Evolution Loop                    │
│                                                         │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐         │
│   │ Observe  │───▶│ Diagnose │───▶│  Evolve  │         │
│   │ (scan)   │    │ (LLM)    │    │ (act)    │         │
│   └──────────┘    └──────────┘    └──────────┘         │
│        ▲                                │               │
│        │         ┌──────────┐           │               │
│        └─────────│  Verify  │◀──────────┘               │
│                  │ (test)   │                            │
│                  └──────────┘                            │
│                      │                                   │
│                  ┌──────────┐                            │
│                  │  Learn   │                            │
│                  │ (archive)│                            │
│                  └──────────┘                            │
└─────────────────────────────────────────────────────────┘
```

## Architecture

| Layer | Component | Role |
|-------|-----------|------|
| L0 | BGE Semantic Search + Entity Graph | Knowledge infrastructure — vector retrieval + structured relationships |
| L1 | Self-Evolve Engine | Scan pain points → LLM judgment → execute 1-3 actions → archive |
| L1.5 | Evolution Archive | Every evolution step is recorded with metadata for analysis |
| L2 | Dreaming Engine | Extract patterns from session history → inject into evolution candidates |
| L3 | Meta Agent | Self-referential: the agent examines its own evolution strategy and modifies its scripts |
| L3.5 | Cross-Domain Transfer | Extract patterns from archive → apply to cron/script domains |
| L4 | Self-Evaluation | ROI calculation + stagnation detection + weekly recommendations |

## Key Features

### 🔍 Autonomous Problem Detection
- Scans error logs, cron failures, tool usage patterns
- Builds a `pain_points.json` with confidence scores
- Filters noise (confidence threshold 0.6) to avoid false positives

### 🧠 Dreaming Engine
- Samples past sessions and extracts recurring patterns
- Generates evolution candidates (fix patterns, consolidate duplicates, archive stale items)
- Feeds candidates into the evolution pipeline

### 🔧 Rule-Based Fast Path
- High-determinism actions execute automatically without LLM:
  - Pause cron jobs with ≥10 consecutive failures
  - Mark timeout-prone scripts
  - Ignore duplicate topics (≥20 occurrences)
- LLM only invoked for novel situations (reduces cost by ~70%)

### 🤖 Meta Agent (Self-Referential Evolution)
- The agent examines its own evolution scripts
- Can modify whitelisted functions (add guards, improve resilience, consolidate)
- Every change is backed up, tested, and git-committed

### 📊 Self-Evaluation
- ROI calculation per evolution action
- Stagnation detection (no progress in 4 weeks → alert)
- Weekly report pushed to messaging platform

## Quick Start

```bash
# 1. Clone into your Hermes scripts directory
git clone https://github.com/YOUR_USERNAME/hermes-self-evolution ~/.hermes/scripts/self-evolution

# 2. Run the unified evolution pipeline
python3 ~/.hermes/scripts/unified_evolution.py

# 3. Or run individual components
python3 ~/.hermes/scripts/self_heal.py          # Self-repair scan
python3 ~/.hermes/scripts/dreaming_engine.py     # Pattern extraction
python3 ~/.hermes/scripts/evolution_archive.py   # View evolution history
```

## Components

### `unified_evolution.py` — Main Pipeline
Runs the complete evolution cycle in one script:
1. Dreaming (pattern extraction from sessions)
2. Deep Dream (memory distillation)
3. Self-Evolve (pain point scan + fix)
4. Archive (record evolution step)

Execution time: ~3 seconds (rule-based fast path, no LLM for common patterns)

### `self_heal.py` — Pain Point Scanner
Scans error logs, cron outputs, and tool usage to build a prioritized list of issues.

### `dreaming_engine.py` — Pattern Extractor
Samples N recent sessions, extracts recurring patterns, and generates evolution candidates.

### `hyperagents_meta_agent.py` — Meta Agent
Examines the evolution system itself. Can modify its own scripts within safety boundaries.

### `evolution_archive.py` — Evolution History
Every evolution step is recorded with:
- Action taken
- Target file/script
- Before/after state
- Success/failure
- Timestamp

### `evolution_self_eval.py` — Self-Evaluation
Weekly analysis of evolution effectiveness:
- Actionability rate (% of candidates that resulted in actual changes)
- ROI per action type
- Stagnation signals

## Safety Boundaries

The Meta Agent operates within strict safety rules:

```
✅ CAN: Add try/except guards to scripts
✅ CAN: Add deprecation warnings to unused scripts
✅ CAN: Consolidate duplicate code patterns
✅ CAN: Modify its own whitelist of safe actions
✅ CAN: Run regression tests before committing

❌ CANNOT: Delete files (backup first)
❌ CANNOT: Modify core system files (config.yaml, .env)
❌ CANNOT: Execute external network calls during evolution
❌ CANNOT: Override user-set configurations
❌ CANNOT: Modify other agents' scripts
```

## Configuration

```yaml
# In your Hermes config.yaml or cron setup
self_evolution:
  # Pain point confidence threshold (0-1, higher = fewer false positives)
  confidence_threshold: 0.6
  
  # Maximum actions per evolution cycle
  max_actions_per_cycle: 3
  
  # Auto-execute threshold (high+medium = auto, low = record only)
  auto_execute_levels: ["high", "medium"]
  
  # Dreaming engine: sessions to sample
  dreaming_sample_size: 20
  
  # Stagnation detection: weeks without progress before alert
  stagnation_threshold_weeks: 4
```

## Cron Integration

```bash
# Daily evolution pipeline (no_agent mode, ~3 seconds)
0 2 * * * python3 ~/.hermes/scripts/unified_evolution.py

# Weekly meta-agent review
0 14 * * 0 python3 ~/.hermes/scripts/hyperagents_meta_agent.py --apply

# Weekly self-evaluation report
0 14 * * 0 python3 ~/.hermes/scripts/evolution_self_eval.py
```

## Real-World Results

After 6 months of continuous operation (as of July 2026):

| Metric | Value |
|--------|-------|
| Evolution entries archived | 108+ |
| Autonomous fixes applied | 35+ |
| Cron jobs monitored | 44 |
| Pain points detected & resolved | 46+ |
| Self-modifications (Meta Agent) | 6 |
| Stagnation alerts | 0 |
| System uptime | 99.8% |

## Related Skills

This framework generates reusable skills during evolution:

- `autonomous-self-repair` — Self-repair workflow
- `passive-observation` — Threshold-triggered observation pattern
- `self-heal-evolve` — Evolution engine
- `memory-retrieval-observer` — Memory retrieval quality monitoring

## Contributing

This is an early-stage research project. Contributions welcome:

1. Fork the repo
2. Create a feature branch
3. Submit a PR with tests

## License

MIT

## Acknowledgments

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) — The runtime platform
- [BGE](https://github.com/FlagOpen/FlagEmbedding) — Semantic search backbone
- Inspired by: EEVEE Router-Prompt Co-Evolution, AlphaEvolve, MAGMA Multi-Graph Memory
