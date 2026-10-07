# Benchmarking & Measurement

You can't optimize what you don't measure, and a dishonest measurement is worse than none — it sends
you optimizing the wrong thing with confidence. This file covers how to measure truthfully.

## Table of contents
- [Profile before optimizing](#profile-before-optimizing)
- [How to benchmark honestly](#how-to-benchmark-honestly)
- [Report percentiles, not averages](#report-percentiles-not-averages)
- [Load testing](#load-testing)
- [Tooling by ecosystem](#tooling-by-ecosystem)
- [Common measurement traps](#common-measurement-traps)

## Profile before optimizing

Before changing anything, find where time and resources actually go. Intuition about bottlenecks is
wrong more often than not — the slow part is rarely the part you suspect.

- **CPU profiler** — flame graphs show where CPU time is spent; the widest frames are your targets.
- **Distributed tracing** (OpenTelemetry, etc.) — for services, shows which hop in the request path
  dominates latency. Usually reveals that one DB query or downstream call owns most of the time.
- **Memory/allocation profiler** — for GC pauses, leaks, and allocation hot spots.
- **Metrics** — RED (Rate, Errors, Duration) per endpoint; resource saturation (CPU, memory, I/O,
  network) to spot which resource is the ceiling.

Attack the biggest contributor first. Re-profile after each change — fixing one bottleneck just
promotes the next one, and the profile shifts under you.

## How to benchmark honestly

A benchmark is a small experiment, and experimental hygiene applies:

- **Warm up first.** Discard initial iterations. JITs compile hot paths, caches fill, connection
  pools populate — cold numbers measure startup, not steady state.
- **Use realistic data and access patterns.** Payload sizes, cardinality, read/write mix, and key
  distribution must resemble production. A benchmark over uniform random keys lies about a system
  facing skewed/hot keys.
- **Isolate what you're measuring.** Change one variable at a time. Control for background load,
  thermal throttling, and noisy neighbors.
- **Run enough iterations** to get past noise, and report the distribution, not one lucky run.
- **Measure the right boundary.** Include (or deliberately exclude) serialization, network, and
  connection setup consciously — know what's inside your measurement and what isn't.

## Report percentiles, not averages

**Averages hide the pain.** A 20 ms average can conceal a 2-second p99 that affects thousands of
users. Report p50, p95, p99, and p99.9 — and optimize the tail, because tail latency is what users
feel and what SLAs are written against.

Also note: percentiles don't average or add across services. If service A calls B and C, A's p99
isn't B's p99 plus C's p99 — fan-out makes tail latency *worse* than any single dependency, because a
request is slow if *any* dependency is slow. Measure end-to-end, not just per-component.

## Load testing

Benchmarks measure a component in isolation; load tests measure the system under realistic
concurrent pressure — which is where queueing, contention, and saturation effects appear.

- **Ramp up** load gradually to find the point where latency starts climbing (the knee of the
  curve) — that's your practical capacity.
- **Test at and beyond peak** to see how the system degrades: gracefully (steady latency, shed load)
  or catastrophically (latency explodes, cascading failures)?
- **Sustain load** long enough to expose leaks, GC accumulation, and connection exhaustion that a
  short test misses.
- Tools: k6, Gatling, Locust, wrk, JMeter, Vegeta.

## Tooling by ecosystem

Reach for the standard profiler/benchmark tools rather than hand-rolling timers:

- **General / services** — OpenTelemetry tracing; Prometheus + Grafana for metrics; `perf` and
  flame graphs on Linux.
- **JVM** — async-profiler, JMH (microbenchmarks — respects warm-up/JIT), JFR.
- **Go** — built-in `pprof` and `testing.B` benchmarks; the race detector for concurrency bugs.
- **Python** — `cProfile`/`py-spy` for CPU, `scalene`/`memray` for memory; `pytest-benchmark`.
- **Node.js** — `--prof`/`--cpu-prof`, clinic.js, `0x` flame graphs.
- **Rust/C/C++** — `perf`, Valgrind/Callgrind, Criterion (Rust) for statistically sound benchmarks.
- **Databases** — `EXPLAIN ANALYZE` and the query planner; slow-query logs; `pg_stat_statements`.
- **Web frontend** — Lighthouse, Chrome DevTools Performance panel, Web Vitals (LCP/INP/CLS) for
  perceived/delivery speed.

## Common measurement traps

- **Measuring cold-start as steady-state** — the warm-up mistake; inflates numbers with one-time costs.
- **Benchmarking the benchmark harness** — the dominant cost is your timing loop or logging, not the
  code under test.
- **Dead-code elimination** — the optimizer removes the work whose result you never use, so you
  measure nothing. Consume the result (return it, sum it) to keep it alive.
- **Unrealistic caches** — a warm cache over the same key every iteration shows a 100% hit rate you'll
  never see in production; a cold cache every time is equally unrealistic.
- **Single-machine, single-thread numbers** projected to a distributed, concurrent world — coordination,
  contention, and network costs don't extrapolate linearly.
- **Averaging away the tail** — see above; the whole point is usually the p99.
- **Testing on hardware unlike production** — laptop SSD/CPU numbers don't transfer to a throttled
  cloud instance or vice versa.
