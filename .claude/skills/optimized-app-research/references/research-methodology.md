# Research Methodology

How to research a problem space and technology choices for a performance-critical application, and
turn the findings into a decision you can defend.

## Table of contents
- [When to research vs. just build](#when-to-research-vs-just-build)
- [Framing the investigation](#framing-the-investigation)
- [Running the research efficiently](#running-the-research-efficiently)
- [Building a technology comparison](#building-a-technology-comparison)
- [Scoring template](#scoring-template)
- [Avoiding research pitfalls](#avoiding-research-pitfalls)

## When to research vs. just build

Research earns its cost when a decision is **expensive to reverse** or **carries real performance
risk**: the primary language/runtime, the database, the core architecture (monolith vs. services,
sync vs. event-driven), or a third-party dependency on the hot path. For easily-reversible choices,
skip the research and pick a sensible default — you can change it later cheaply.

## Framing the investigation

Start from the performance goals (from SKILL.md step 1) and the workload shape. The workload dictates
which properties matter, so classify it first:

- **Read-heavy vs. write-heavy** — changes the database and caching strategy entirely.
- **CPU-bound vs. I/O-bound** — CPU-bound wants parallelism and efficient algorithms/languages;
  I/O-bound wants concurrency, batching, and fewer round-trips.
- **Latency-sensitive vs. throughput-oriented** — real-time request/response vs. bulk/batch pipeline.
- **Steady vs. bursty** — bursty load needs elasticity, queues, and backpressure.
- **Small hot dataset vs. huge dataset** — determines whether you can hold data in memory, and
  whether caching or precomputation is viable.

Turn the classification into a short list of concrete questions the research must answer, e.g.
"Which datastore sustains 50k writes/sec with sub-10ms p99 on our budget?" A question with numbers in
it produces a usable answer; "which database is best?" does not.

## Running the research efficiently

- **Use current sources.** If web access is available, prefer it for anything version- or
  benchmark-sensitive — runtime performance, library maturity, and pricing change fast, and
  remembered numbers are often stale. Favor primary sources: official docs, the project's own
  benchmarks (read skeptically), and reputable engineering blogs with methodology.
- **Parallelize independent threads.** When several technologies or sub-questions are independent,
  investigate them concurrently. If subagents are available, spawn one research agent per candidate
  technology or per sub-question and have each return a structured summary; this is far faster than
  serial investigation and keeps each agent's context focused. Give each a crisp brief: the workload,
  the specific numbers to find, and the comparison axes below.
- **Timebox and converge.** Research can expand forever. Once you can fill the scoring table with
  reasonable confidence, stop and decide. Note remaining unknowns as risks to validate by
  benchmarking (SKILL.md step 4) rather than researching indefinitely.

## Building a technology comparison

Compare candidates on the axes that matter **for this workload**, not generic popularity. Typical
axes for a performance-critical choice:

- **Raw performance on this workload** — latency and throughput from credible benchmarks, ideally
  ones resembling your access pattern. A benchmark for a different workload is nearly meaningless.
- **Scalability** — how it grows: vertically, horizontally, and where the cliff is.
- **Concurrency model** — threads, async/event-loop, actors, goroutines; fit to CPU- vs. I/O-bound.
- **Operational maturity** — observability, tooling, stability, community, hiring pool.
- **Ecosystem fit** — how well it integrates with the existing stack and team expertise. A
  theoretically faster tool the team can't operate is slower in practice.
- **Cost** — infrastructure and licensing at the target scale.
- **Reversibility** — how locked-in you are if it turns out wrong.

## Scoring template

Make the comparison legible with a weighted table. Assign weights reflecting *this* project's
priorities (they must sum to 1.0), score each candidate 1–5 per axis, and compute weighted totals.
The point isn't false precision — it's forcing the trade-offs into the open and making the reasoning
auditable.

| Axis (weight)            | Option A | Option B | Option C |
|--------------------------|:--------:|:--------:|:--------:|
| Performance on workload (0.30) |    5     |    4     |    3     |
| Scalability (0.20)       |    4     |    5     |    3     |
| Operational maturity (0.20) |    3     |    5     |    4     |
| Ecosystem/team fit (0.15) |    3     |    4     |    5     |
| Cost (0.15)              |    4     |    3     |    5     |
| **Weighted total**       | **4.0**  | **4.3**  | **3.7**  |

Always accompany the table with prose: the numbers guide the decision but the narrative explains the
close calls, the deal-breakers a score can't capture, and your recommendation.

## Avoiding research pitfalls

- **Vendor benchmarks are marketing.** A project's own benchmarks are tuned to flatter it. Trust
  independent tests, or better, your own prototype (SKILL.md step 4).
- **Beware benchmark/workload mismatch.** "X does 1M ops/sec" means nothing if those ops don't
  resemble yours (payload size, read/write mix, concurrency, durability settings).
- **Don't over-index on raw speed.** The fastest option on paper often loses on operability,
  ecosystem, or team familiarity — all of which affect delivered performance and reliability.
- **Separate "popular" from "right."** Popularity is a proxy for maturity and hiring, not for fit to
  your workload. Weigh it, don't worship it.
