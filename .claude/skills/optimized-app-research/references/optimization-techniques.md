# Optimization Techniques

A catalog of performance techniques organized by layer. **Read this only after you know which layer
your bottleneck is in** — applying a network technique to a CPU bottleneck (or vice versa) wastes
effort. Within the right layer, prefer the techniques near the top: they tend to have the largest
impact-to-effort ratio.

The single most important rule spans every layer: **the fastest work is the work you never do.**
Eliminating or avoiding work beats speeding it up. Look for chances to cache, precompute, batch, skip,
or lazily defer before you look for chances to tune.

## Table of contents
- [Algorithmic & data-structure](#1-algorithmic--data-structure)
- [Caching & precomputation](#2-caching--precomputation)
- [Concurrency & parallelism](#3-concurrency--parallelism)
- [I/O & round-trips](#4-io--round-trips)
- [Data & database](#5-data--database)
- [Memory & allocation](#6-memory--allocation)
- [Network & payload](#7-network--payload)
- [Delivery & "fast output" (perceived speed)](#8-delivery--fast-output-perceived-speed)
- [When NOT to optimize](#when-not-to-optimize)

## 1. Algorithmic & data-structure

The highest-leverage layer. A better algorithm changes the *shape* of the cost curve; everything else
just shifts constants. Always check this layer first for anything compute- or data-scaling-bound.

- **Reduce complexity class.** O(n²)→O(n log n)→O(n)→O(1) beats any constant-factor tuning as n grows.
  A hash lookup instead of a linear scan, a sort-then-merge instead of nested loops.
- **Pick the right data structure.** Hash map for membership/lookup, heap for top-k, trie for prefix
  search, bitset for dense sets, balanced tree for ordered range queries. The structure often *is*
  the optimization.
- **Avoid repeated work.** Memoize pure results; hoist invariant computation out of loops;
  incrementalize (update a running result instead of recomputing from scratch).
- **Short-circuit and prune.** Exit early, filter before expensive operations, order cheap
  discriminating checks first.

## 2. Caching & precomputation

The purest form of "don't do the work." Enabled by the freshness/staleness budget from SKILL.md
step 1 — the more staleness you can tolerate, the more you can cache.

- **Cache layers**: in-process (fastest, per-instance), distributed (Redis/Memcached, shared),
  CDN/edge (closest to users). Pick by how shared and how fresh the data must be.
- **Precompute / materialize.** Compute expensive results ahead of time (materialized views,
  denormalized read models, precomputed aggregates) so requests just read.
- **Invalidation is the hard part.** Choose a strategy deliberately: TTL (simple, allows staleness),
  write-through/write-behind, or event-based invalidation. Cache correctness bugs are subtle — be
  explicit about what can go stale and for how long.
- **Watch the failure modes**: cache stampede (many misses at once — use request coalescing or
  probabilistic early refresh), and low hit rates (a cache that mostly misses adds latency for
  nothing — measure the hit rate).

## 3. Concurrency & parallelism

For I/O-bound work use **concurrency** (overlap waiting); for CPU-bound work use **parallelism** (use
more cores). Confusing the two is a common, costly mistake.

- **Async / non-blocking I/O** (event loop, async/await) lets one thread juggle thousands of waiting
  I/O operations — ideal for I/O-bound services with high concurrency.
- **Parallelism** (thread pools, worker processes, SIMD, GPU) divides CPU-bound work across cores.
  Beware Amdahl's law: the serial fraction caps your speedup.
- **Pipelining** overlaps stages so throughput is set by the slowest stage, not the sum.
- **Backpressure & bounded queues** prevent a fast producer from overwhelming a slow consumer and
  blowing up memory/latency. Essential for bursty load.
- **Beware the costs**: lock contention can make "parallel" code slower than serial; context-switch
  and coordination overhead; and false sharing on hot cache lines. Prefer lock-free or
  share-nothing/partitioned designs where possible.

## 4. I/O & round-trips

For most networked apps, round-trips dominate latency. Cutting their **number** usually beats
speeding each one up.

- **Batch** many small operations into one (bulk DB writes, multi-get, GraphQL/DataLoader batching).
- **Kill N+1 patterns** — the classic "one query per item in a loop." Fetch in a single query/join.
- **Parallelize independent I/O** instead of awaiting sequentially.
- **Connection pooling** avoids repeated connection setup cost.
- **Stream instead of buffering** large payloads so you start work before the whole thing arrives.
- **Move computation to the data** (server-side filtering/aggregation) instead of transferring raw
  data to compute elsewhere.

## 5. Data & database

Often the true bottleneck in CRUD and data-heavy apps.

- **Index for your query patterns.** A missing index turns a lookup into a full scan; the wrong
  indexes slow writes. Index deliberately for the queries you actually run.
- **Read the query plan.** Use EXPLAIN/ANALYZE to find scans, bad joins, and missing indexes. This is
  profiling for the database — don't guess.
- **Shape the schema for access.** Normalize for write integrity, denormalize for read speed; choose
  by the read/write ratio. Materialized views and read replicas offload heavy reads.
- **Partition / shard** large datasets to keep working sets and indexes small and enable horizontal
  scale.
- **Right storage engine for the access pattern** — OLTP row store, OLAP columnar, key-value,
  time-series, search index. Using one engine for an access pattern it's bad at is a common
  self-inflicted bottleneck.

## 6. Memory & allocation

Matters most for latency-sensitive, high-throughput, or memory-bound systems.

- **Reduce allocations** on the hot path; reuse buffers and object pools. In GC languages, allocation
  rate drives GC pause frequency — a major source of tail-latency spikes.
- **Data locality.** Contiguous, cache-friendly layouts (arrays/structs-of-arrays) beat
  pointer-chasing; a cache miss costs ~100× a hit. This often matters more than instruction count.
- **Right-size working sets** so hot data fits in cache/RAM and you avoid paging or thrashing.
- **Stream large data** rather than loading it all into memory.
- **Tune the GC / manage memory manually** only when profiling shows GC or allocation is the actual
  bottleneck.

## 7. Network & payload

- **Shrink the payload**: compression (gzip/brotli/zstd), efficient serialization (Protobuf/
  FlatBuffers/MessagePack over verbose JSON on hot paths), and returning only needed fields.
- **Cut latency with proximity**: CDN/edge, regional deployment, and keeping chatty services
  co-located. Physics sets a floor — cross-region round-trips cost tens of milliseconds each.
- **Modern protocols**: HTTP/2 or HTTP/3 multiplexing, connection reuse/keep-alive, TLS session
  resumption to avoid repeated handshakes.

## 8. Delivery & "fast output" (perceived speed)

Total time isn't the whole story — for anything a person waits on, **perceived** latency is a
first-class target. These techniques make output *feel* fast, sometimes with no change to total work.

- **Stream results** (server-sent events, chunked responses, token-by-token output) so the user sees
  progress immediately instead of waiting for the full result. Time-to-first-byte/token often matters
  more than total time.
- **Incremental / progressive rendering** — show a skeleton, then fill in; render above-the-fold
  first; lazy-load below.
- **Optimistic UI** — reflect the likely result instantly and reconcile when the server confirms.
- **Prefetch / preload** likely-next data during idle time so it's ready before it's asked for.
- **Debounce/throttle** high-frequency events (input, scroll, resize) to avoid redundant work.
- **Progress feedback** — even honest progress indication makes waiting feel shorter and prevents
  the perception of a hang.

## When NOT to optimize

Optimization has costs — complexity, bugs, and time — so spend it where it pays:

- **When it isn't the bottleneck.** Amdahl's law: speeding up 5% of the runtime buys at most 5%.
- **When you haven't measured.** Optimizing on a hunch usually adds complexity for no gain, and
  sometimes makes things slower.
- **When the target is already met.** If p99 is under budget, stop and ship. "Fast enough" is a real,
  legitimate finish line.
- **When simplicity is worth more.** A clear design that's slightly slower but easy to maintain,
  cache, and scale often wins over a clever brittle one. Optimize only where a measurement demands it.
