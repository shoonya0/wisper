---
name: optimized-app-research
description: >-
  Research and design methodology for building complex, high-performance applications where
  low latency and fast output matter. Use this whenever the user wants to research, architect,
  plan, or optimize an application for speed, throughput, latency, scalability, or "fast output" —
  even if they don't say the word "optimization." Triggers include: designing a system that must
  handle high load or return results quickly, choosing an architecture for performance, profiling
  and speeding up a slow app, planning a real-time/streaming/low-latency service, or producing a
  technical research/design document that weighs performance trade-offs. Prefer this skill over
  ad-hoc advice whenever the goal is "make it fast" or "make it scale."
---

# Optimized Application Research

A disciplined method for researching and designing complex applications whose success depends on
**speed**: low latency, high throughput, and fast, responsive output. The core idea is simple and
often ignored: **measure first, optimize what matters, and let real numbers — not intuition — drive
every decision.** Premature optimization wastes effort; unmeasured optimization is guessing.

Use this skill to produce a rigorous research/design artifact or to guide an optimization effort.
It works in two modes that share the same backbone:

- **Design mode** — the app doesn't exist yet. Research the domain, define performance targets, and
  design an architecture that can meet them.
- **Optimization mode** — the app exists but is too slow. Profile it, find the real bottlenecks, and
  fix them in impact order.

## The workflow

Work through these phases in order. Don't skip the early ones — most bad performance outcomes trace
back to skipping requirements or measurement, not to a lack of clever tricks.

### 1. Define what "fast" means (quantify the target)

Vague goals ("make it fast") can't be met or verified. Before anything else, pin down numbers:

- **Latency** — target and tail. Specify percentiles, not just averages: p50, p95, p99, p99.9. Tail
  latency is usually what users feel and what SLAs are written against. An app with a great average
  and a terrible p99 feels broken.
- **Throughput** — requests/sec, events/sec, or items processed per unit time at steady state.
- **Concurrency / load** — expected and peak concurrent users or in-flight requests.
- **Data scale** — dataset size now and projected; per-request payload sizes.
- **Resource / cost budget** — CPU, memory, network, and the money ceiling. "Fast at any cost" is
  rarely the real requirement.
- **Freshness vs. speed** — how stale can a cached/precomputed answer be? This single trade-off
  unlocks the most powerful optimizations (caching, precomputation, materialized views).

Write these down as explicit acceptance criteria. Everything later is judged against them.

### 2. Research the problem space

Don't design in a vacuum. Spend real effort understanding what already exists and what the
constraints are. If web access is available, use it — benchmarks, engineering blogs, and library
docs age fast, and current numbers beat remembered ones.

- **Prior art** — how do existing systems in this domain solve it? What architectures do the fast
  ones use? What are their published latency/throughput numbers?
- **Candidate technologies** — languages, runtimes, frameworks, databases, and libraries. Compare on
  the axes that matter *for this workload* (see `references/research-methodology.md` for a structured
  comparison approach and a scoring template).
- **Known bottleneck patterns** — most domains have a characteristic bottleneck (DB round-trips for
  CRUD apps, serialization for RPC-heavy systems, GC pauses for latency-sensitive JVM/Go services,
  cold starts for serverless). Identify the likely one early.
- **Constraints** — team expertise, existing stack, deployment environment, regulatory limits.

For the full research playbook — how to structure the investigation, spawn parallel research, and
build a defensible technology comparison — read `references/research-methodology.md`.

### 3. Design (or diagnose) with a performance model

Before choosing optimizations, build a rough mental model of where time and work go.

- **In design mode**: sketch the request path end to end and estimate the cost of each hop (network
  round-trips, DB queries, CPU-bound work, serialization). Back-of-envelope math catches infeasible
  designs before a line of code is written — if your latency budget is 100 ms and you've planned five
  sequential cross-region calls at 80 ms each, no amount of micro-optimization saves you.
- **In optimization mode**: **profile before you touch anything.** Intuition about bottlenecks is
  wrong far more often than people expect. Use a profiler, tracing, or metrics to find where the time
  actually goes, then attack the biggest contributor first (Amdahl's law: optimizing a component that
  costs 5% of total time can, at best, buy 5%).

The menu of optimization techniques — organized by layer (algorithmic, concurrency, I/O, memory,
caching, data, network, and delivery/"fast output") — lives in
`references/optimization-techniques.md`. Consult it once you know *which* layer your bottleneck is
in; applying techniques from the wrong layer is wasted effort.

### 4. Prototype and measure the risky parts

For the one or two decisions that carry the most performance risk, build a minimal benchmark or
spike rather than committing on faith. A 50-line benchmark that settles "can this database sustain
our write rate?" is worth more than pages of speculation. See `references/benchmarking.md` for how to
benchmark honestly (warm-up, percentiles, realistic data, avoiding common measurement traps).

### 5. Validate against the targets

Close the loop. Re-measure against the acceptance criteria from step 1 under realistic load. Report
actual numbers vs. targets. If a target is missed, return to step 3 with the new profile data — this
is a loop, not a straight line. Optimization is iterative by nature: measure, change one thing,
measure again, keep what helps.

## Guiding principles

These are the beliefs that make the workflow work. Internalize them; they matter more than any
individual trick.

- **Measure, don't guess.** Every optimization is justified by a number, before and after. If you
  can't measure the improvement, you can't claim it — and you might be making things worse.
- **Optimize the bottleneck, not the familiar.** People optimize the code they understand, not the
  code that's slow. Follow the profiler to the real cost, even into unfamiliar layers.
- **The fastest work is the work you don't do.** Caching, precomputation, laziness, batching, and
  cutting round-trips beat micro-optimizing work that shouldn't happen at all. Algorithmic and
  architectural wins (O(n²)→O(n log n), one query instead of N) dwarf constant-factor tuning.
- **Latency and throughput are different goals** and sometimes conflict. Batching raises throughput
  but adds latency; per-request threads cut latency but cap throughput. Know which one you're
  optimizing.
- **Tail latency is the real latency.** Optimize p99, not the average — a system is only as
  responsive as its slow requests, and those are what users remember.
- **Simplicity is a performance feature.** A simple design that's easy to reason about, cache, and
  parallelize usually beats a clever one you can't fully understand. Add complexity only where a
  measurement demands it.
- **"Fast output" is perceived, not just measured.** Streaming, incremental rendering, optimistic UI,
  and progress feedback make a system *feel* fast even when total time is unchanged. For anything
  user-facing, treat perceived latency as a first-class target.

## Producing the deliverable

Unless the user asks for something else, structure a research/design document with these sections.
Keep it evidence-driven — cite the numbers, benchmarks, and sources behind each recommendation
rather than asserting them.

```
# [Application] — Performance Research & Design

## 1. Performance goals
   Quantified targets: latency percentiles, throughput, load, data scale, cost budget, freshness.

## 2. Problem & constraints
   The workload, its characteristic bottleneck, and hard constraints (stack, team, environment).

## 3. Research findings
   Prior art, technology comparison (with the scoring table), and cited sources/benchmarks.

## 4. Proposed architecture
   The design, the request-path performance model, and the back-of-envelope latency/throughput math.

## 5. Optimization strategy
   Which techniques apply at which layer, in priority order, each tied to the bottleneck it addresses.

## 6. Risks & validation plan
   The riskiest assumptions, what to prototype/benchmark, and how each target will be verified.
```

Adapt the depth to the request: a quick "how should I make X fast?" needs a tight version of this,
while a full system design warrants the whole thing. When it helps the reader weigh trade-offs,
present technology or architecture comparisons as a table.

## Reference files

Read these as needed — they hold the depth that would bloat this file:

- `references/research-methodology.md` — how to research the domain and technologies, spawn parallel
  investigation, and build a defensible, scored technology comparison.
- `references/optimization-techniques.md` — the technique catalog, organized by layer (algorithmic,
  concurrency, I/O, memory, caching, data, network, delivery/fast-output), with when each applies.
- `references/benchmarking.md` — how to measure honestly: percentiles, warm-up, realistic load,
  profiling tools per ecosystem, and the measurement traps that produce lies.
