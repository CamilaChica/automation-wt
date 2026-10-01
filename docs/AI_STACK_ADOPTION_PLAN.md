# AI Stack Adoption Plan

## Objective

Introduce hybrid search, GraphRAG, LangGraph, CrewAI, LoRA/QLoRA, quantization, and vLLM into the existing RFQ and document-assistance system without duplicating core workflow logic or committing to recurring GPU costs before there is evidence they are worthwhile.

This is a proposal only. No application code, dependencies, cloud resources, production data, or deployment settings are changed by this plan.

## Current Baseline

- The backend already has a deterministic `OrchestrationService`, specialized agents, a shadow-mode event runtime, and explicit compliance and human-review gates.
- The RAG pipeline already supports ingestion, source citations, prompt security, evaluation, OpenAI/Hugging Face embeddings, and interchangeable in-memory, SQLAlchemy, and Qdrant vector-store adapters.
- The SQLAlchemy vector adapter stores embeddings as JSONB and ranks them in Python; it is not a database-native vector index. The LLM router supports hosted providers, currently configured for OpenAI in Render.
- Render is the current application host. The deployment operations reference reports production readiness as HTTP 503. Treat production changes as blocked until the existing operational issue is resolved and explicitly validated.

## Recommended Order

| Order | Capability | Recommendation | Cost profile |
| --- | --- | --- | --- |
| 1 | Hybrid Search | Implement first behind the existing retrieval interface; start with PostgreSQL full-text search plus current vector retrieval and rank fusion. | Low to moderate; no GPU required. |
| 2 | LangGraph | Pilot as an optional workflow/state adapter around one bounded, non-critical RFQ path; do not replace deterministic business rules. | Low at pilot scale; framework adds maintenance, not GPU cost. |
| 3 | CrewAI | Keep as an experiment for a bounded, read-only research task only if role-based collaboration proves useful. Do not run CrewAI and LangGraph as competing orchestrators in the production critical path. | Variable model/API spend; can multiply calls. |
| 4 | GraphRAG | Add only if retrieval evaluations show repeated failures on questions requiring relationships or multi-hop evidence. Build a small, source-linked graph from existing records. | Moderate to high ingestion and operational complexity. |
| 5 | LoRA / QLoRA | Fine-tune only after collecting an approved, de-identified dataset and showing prompting or retrieval cannot meet a defined quality target. Prefer a short, rented GPU training run. | Time-bounded GPU cost plus dataset/evaluation work. |
| 6 | Quantization | Benchmark a compatible open model at BF16/FP16 and 8-bit/4-bit options; retain only a configuration that meets quality and latency gates. | Can lower serving memory/cost; quality and compatibility risk. |
| 7 | vLLM | Serve a selected open-weight model behind an OpenAI-compatible API only if measured request volume makes dedicated GPU hosting cheaper or a hard control requirement justifies it. | Highest recurring cost when GPU capacity remains provisioned. |

The ordering is intentional: establish retrieval and workflow quality first, then test whether specialized model training and self-hosting solve a demonstrated problem. Steps 2 and 3 are alternatives for the workflow-orchestration experiment, not a recommendation to adopt both in production.

## Step-by-Step Plan

### Step 0: Establish the baseline and operating limits

1. Resolve the production readiness failure before any production rollout; use the existing deployment runbook and approved operational process.
2. Freeze a representative, permissioned evaluation set for RFQ extraction, part-number lookup, documentation evidence, compliance blocks, and customer responses. Include negative cases and expected source citations.
3. Record current answer quality, retrieval recall at a fixed `k`, p50/p95 latency, token usage, provider/API spend, failure rate, and human-review rate.
4. Set a monthly experimental spend ceiling and an owner-approved threshold for per-request cost. Use synthetic or de-identified records for experiments; do not send restricted/export-controlled information to unapproved providers.
5. Preserve deterministic pricing, compliance decisions, inventory writes, quote approval, and external side effects outside LLM control.

**Gate:** No feature proceeds without a repeatable baseline, approved test data, and a defined budget. Production work also requires readiness to pass.

### Step 1: Add hybrid search to the existing RAG path

1. Extend the `VectorStore`-adjacent retrieval contract so lexical and semantic search can return the same source IDs, metadata, and scores.
2. Pilot lexical retrieval with PostgreSQL full-text search over document chunks and metadata filters for document type, part number, and source. Keep the existing embedding provider and vector adapter for semantic candidates.
3. Merge lexical and vector candidates with Reciprocal Rank Fusion (RRF), initially without an LLM reranker. Preserve source IDs and citation validation through generation.
4. Compare hybrid retrieval with the current vector-only baseline on exact part-number queries, terminology variations, document references, and natural-language questions.
5. Track database query time and embedding/API cost. Avoid fetching and cosine-ranking the entire JSONB embedding table at growing scale; evaluate native PostgreSQL vector indexing only if measured corpus size or latency makes it necessary.

**Gate:** Hybrid search must improve retrieval recall or answer correctness without violating latency and budget limits. Keep a feature flag and the vector-only fallback.

### Step 2: Evaluate a single workflow orchestration framework

1. Select one low-risk workflow with clear state transitions and existing tests; retain `OrchestrationService` as the authoritative implementation during the pilot.
2. Prototype LangGraph first if the requirement is explicit state, retries, resumability, or human interrupts. Model typed state, bounded nodes, checkpointing, and interruption points; keep pricing/compliance/approval logic as deterministic application services.
3. Run the graph in shadow mode against recorded or synthetic events. Compare proposed transitions with the existing pipeline and verify idempotency, audit correlation IDs, timeout behavior, and safe resume.
4. Test CrewAI separately only for a read-only task where multiple focused workers may help (for example, supplier-document research). Enforce tool allowlists, step limits, timeouts, and a fixed model-call budget; never give an experimental crew permission to approve quotes, contact suppliers, or mutate production records.
5. Choose LangGraph, CrewAI for that isolated task, or neither based on measured reliability and maintainability. Do not nest one framework inside the other without a specific, tested need.

**Gate:** Adopt only if the pilot reduces failure/recovery cost or improves completion quality enough to justify the new operational surface. Existing deterministic behavior and audit history must remain intact.

### Step 3: Add GraphRAG only for a proven retrieval gap

1. Use Step 1 evaluation results to identify questions that require traversing relationships among parts, suppliers, certifications, trace records, and source documents.
2. If these failures are material, define a small graph schema with stable entity IDs and edges that always point back to authoritative source records.
3. Extract entities and relationships asynchronously from approved documents, validate uncertain links, and version graph data so it can be rebuilt. Do not treat model-extracted relationships as compliance evidence without source verification.
4. Retrieve graph neighborhoods only for eligible query types; combine the results with hybrid search and the existing citation/evidence contract.
5. Start with the current PostgreSQL deployment and simple relational tables or another already-funded store where feasible. Price any dedicated graph database before selecting it; avoid duplicating the entire document/vector corpus in a new paid service.

**Gate:** Graph retrieval must measurably improve multi-hop answer quality and traceability over hybrid search alone, within agreed ingestion and query-cost limits. Otherwise, stop at hybrid search.

### Step 4: Decide whether model adaptation is needed

1. Review production-like, de-identified examples and failure categories after retrieval and prompt improvements. Separate retrieval errors from generation/style errors.
2. If errors are mostly missing evidence, improve ingestion/search rather than fine-tuning. If errors are consistent output-format or domain-language behavior, test prompt changes and a small curated few-shot set first.
3. Only if those approaches fail, create a small train/validation/test split from approved examples, remove sensitive data, and document data rights and retention.
4. Run a time-boxed LoRA/QLoRA experiment using a compatible open-weight base model and PEFT-style adapters. QLoRA uses a quantized base during adapter training; it is not itself a production serving plan.
5. Compare against the hosted baseline on held-out quality, citation correctness, compliance negatives, latency, and total cost including engineering and GPU hours. Version the base model, adapter, tokenizer, data, and evaluation results.

**Gate:** Do not train without sufficient authorized examples and a measurable target. Keep the adapter only if held-out results improve materially without weakening safety or evidence behavior.

### Step 5: Benchmark quantization and serving economics

1. Select only models that passed Step 4 evaluation, or use an existing open model if training is not warranted.
2. Benchmark unquantized and supported 8-bit/4-bit formats on representative prompts, structured JSON output, citations, and worst-case context sizes. Record memory, tokens/second, p95 latency, and quality deltas.
3. Test vLLM in an isolated development/staging environment on a short-lived GPU instance, using its OpenAI-compatible API through a dedicated provider adapter. Do not route production traffic to it during the benchmark.
4. Estimate monthly total cost from observed traffic, including GPU uptime/minimum billing, storage, network, monitoring, spare capacity, and on-call effort. Compare with the existing hosted API at actual input/output token volumes.
5. Keep vLLM only if its measured cost or a documented control/latency requirement beats the hosted option. Use autoscaling or scheduled shutdown where the platform supports it; if the GPU cannot scale to zero, include idle hours in the comparison.

**Gate:** Required model quality, citation/compliance tests, latency, availability, and a documented break-even volume must all pass before any production-serving proposal.

### Step 6: Gradual rollout and operations

1. Keep each capability independently configurable: hybrid retrieval, graph retrieval, workflow adapter, model provider, quantized model, and vLLM endpoint.
2. Release to internal users or a small shadow cohort first; do not change production defaults until results are reviewed.
3. Monitor search quality, unsupported claims, source-citation validity, workflow retries, human escalations, cost per completed RFQ, latency, and provider/GPU availability.
4. Define a one-step rollback for every flag: vector-only retrieval, existing orchestration, hosted model provider, and no graph lookup.
5. Revisit cost and quality after a fixed evaluation period. Remove experiments that add recurring cost without measured benefit.

## Cost Controls

- Reuse the current PostgreSQL and provider interfaces before adding paid data services or another always-on service.
- Begin with lexical full-text plus the existing embeddings; defer rerankers, graph extraction, and GPU inference until evaluations identify a gap.
- Batch and deduplicate document embedding work; cache only where retention and data-isolation policies permit it.
- Bound prompt context, top-k candidates, CrewAI task/agent loops, retries, and model output tokens.
- Use hosted API pricing as the baseline; use temporary GPU rental for training and benchmarking, and include idle GPU time in any serving comparison.
- Do not assume quantization or self-hosting is automatically cheaper. Include operations, redundancy, and engineering time in total cost of ownership.
- Apply hard monthly alerts and an automatic experiment shutoff where available; keep experiments off the production critical path.

## Acceptance Criteria

- Existing backend and RAG tests remain green; new tests cover lexical-only, vector-only, fused ranking, source citation, and no-evidence behavior.
- Critical negative paths still block compliance violations and require human approval where the current workflow does.
- Any graph or fine-tuned-model output is traceable to approved source records and passes the same evidence contract.
- Each adopted component has recorded quality, p95 latency, availability, and per-request/monthly cost against the baseline.
- Production rollout is blocked until readiness is healthy, feature flags and rollback paths are verified, and the owner approves the cost ceiling.

## Explicit Non-Goals

- Replacing the existing RFQ pipeline with two overlapping agent frameworks.
- Giving an LLM authority over price calculation, export-control decisions, inventory truth, quote approval, or external side effects.
- Training on production customer data without an explicit data-use approval and sanitization plan.
- Keeping an always-on GPU service before a measured workload and break-even analysis support it.
- Adding a graph database, vector database, or other paid service solely to use a named technology.