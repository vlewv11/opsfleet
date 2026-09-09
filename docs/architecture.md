# High-Level Design — Retail Analytics Chat Assistant

## 1. System context (production target)

```mermaid
graph TB
    subgraph clients["Client surfaces"]
        CLI["CLI REPL<br/><i>this prototype</i>"]
        SLACK["Slack bot"]
        WEB["Internal web chat"]
    end

    subgraph edge["Edge"]
        IAP["Identity-Aware Proxy<br/>Google Workspace SSO<br/><i>establishes user_id + role</i>"]
    end

    subgraph runtime["Agent runtime — Cloud Run (stateless, scale-to-zero)"]
        API["FastAPI<br/>/chat SSE stream"]
        GRAPH["LangGraph agent<br/><i>guard → retrieve → reason → act → redact</i>"]
        POLICY["SQL policy engine<br/><i>sqlglot AST enforcement</i>"]
    end

    subgraph state["State"]
        PG[("Cloud SQL Postgres<br/>· LangGraph checkpoints<br/>· pgvector golden index<br/>· audit log")]
        FS[("Firestore<br/>· user preferences<br/>· persona config")]
        GCSR[("GCS: saved reports<br/><i>object versioning + soft delete</i>")]
    end

    subgraph data["Data plane — read only"]
        AV["BigQuery authorized views<br/><i>PII columns absent from the view</i>"]
        RAW[("bigquery-public-data<br/>.thelook_ecommerce")]
    end

    subgraph golden["Golden Knowledge Bucket"]
        GCSG[("GCS: trio JSON<br/><i>source of truth</i>")]
        IDX["pgvector index"]
        REVIEW["Analyst review console<br/><i>human approval gate</i>"]
    end

    subgraph llm["Model layer"]
        PRO["Gemini 2.5 Pro<br/><i>planning, SQL, narrative</i>"]
        FLASH["Gemini 2.5 Flash<br/><i>guard, SQL repair, judge</i>"]
        EMB["gemini-embedding-001"]
    end

    subgraph obs["Observability"]
        OTEL["OpenTelemetry → Cloud Trace"]
        LOGS["Cloud Logging → BigQuery sink"]
        LS["Langfuse / LangSmith<br/><i>message-level replay</i>"]
    end

    CLI & SLACK & WEB --> IAP --> API --> GRAPH
    GRAPH --> POLICY --> AV --> RAW
    GRAPH <--> PG & FS & GCSR
    GRAPH --> PRO & FLASH
    GRAPH --> IDX
    IDX -.reindex.-> GCSG
    GCSG --> REVIEW
    EMB --> IDX
    GRAPH -.emits.-> OTEL & LOGS & LS

    classDef safety fill:#ffe9e9,stroke:#c0392b,stroke-width:2px
    class POLICY,AV,IAP safety
```

Red-bordered blocks are the deterministic safety boundary. Nothing in that boundary depends on
model behaviour — the model can be fully compromised by prompt injection and still cannot reach PII.

## 2. Agent graph

The compiled LangGraph (exported directly from the running prototype):

```mermaid
graph TD;
    __start__([__start__]):::first
    guard(guard)
    retrieve(retrieve)
    llm(llm)
    tools(tools)
    budget(budget)
    redact(redact)
    __end__([__end__]):::last
    __start__ --> guard;
    guard -. blocked .-> redact;
    guard -. allowed .-> retrieve;
    retrieve --> llm;
    llm -. tool_calls .-> tools;
    llm -. over budget .-> budget;
    llm -. final answer .-> redact;
    tools --> llm;
    budget --> llm;
    redact --> __end__;
    classDef default fill:#f2f0ff,line-height:1.2
    classDef first fill-opacity:0
    classDef last fill:#bfb6fc
```

| Node | Responsibility | Model |
|---|---|---|
| `guard` | Scope + prompt-injection screen. Fails **open** — see §3. | Flash, structured output |
| `retrieve` | Hybrid search of the Golden Bucket for the current question | Embedding + lexical |
| `llm` | Plan, choose tools, write SQL, narrate the answer | Pro |
| `tools` | `describe_data`, `search_precedents`, `query_data`, `save_report`, `remember_preference` | — |
| `budget` | Hard stop. Answers pending tool calls, unbinds tools, forces a final answer | — |
| `redact` | Output scrub + drops dangling tool calls so history stays valid | — |

**Termination is deterministic.** `redact` is the only edge to `END`, and once `exhausted` is set the
router can only reach `redact`. A misbehaving model cannot loop the graph, so the recursion limit is
never the thing that stops us — a bounded budget is.

## 3. The request path for one question

```mermaid
sequenceDiagram
    autonumber
    participant U as Manager
    participant G as guard (Flash)
    participant R as retrieve
    participant L as llm (Pro)
    participant P as policy engine
    participant BQ as BigQuery
    participant X as redact

    U->>G: "Why is Texas underspending vs California?"
    G-->>L: allowed
    R->>R: hybrid search → regional-spend-comparison precedent
    Note over R,L: precedent carries the house rule:<br/>never compare absolute revenue across regions
    L->>P: SELECT u.state, u.email, SUM(sale_price) ...
    P--xL: PolicyError: `email` is blocked
    Note over P,L: repair loop, Flash, no BigQuery cost
    L->>P: SELECT u.state, COUNT(DISTINCT u.id), ...
    P->>P: hash user ids · force LIMIT · block star
    P->>BQ: dry run (free) → 1.4 GB, under budget
    BQ-->>P: rows
    P-->>L: {"status":"ok", "rows":[...]}
    L->>L: decompose per precedent → orders/customer is the gap
    L->>X: narrative answer
    X-->>U: redacted, persona-styled answer
```

## 4. Golden Bucket lifecycle

```mermaid
graph LR
    subgraph write["Write path — how the bucket grows"]
        CONV["Agent conversation"] --> SCORE["Nightly Cloud Run job<br/>candidate scoring"]
        ANALYST["Analyst-authored trio"] --> REVIEW
        SCORE --> REVIEW["Analyst review console<br/><b>human approval gate</b>"]
        REVIEW --> GCS[("GCS trio JSON<br/>versioned")]
        GCS --> EV["Eventarc: object finalize"]
        EV --> EMBED["Embed + upsert"]
        EMBED --> IDX[("pgvector")]
    end

    subgraph read["Read path — query time"]
        Q["User question"] --> HY["Hybrid retrieval<br/>0.75 · cosine + 0.25 · lexical"]
        IDX --> HY
        HY --> TOPK["top-k trios → system prompt"]
    end

    SCORE -. signals .-> S1["thumbs up · report saved<br/>zero repair loops · no follow-up<br/>correction from the user"]
```

A trio never enters the bucket without human approval. An unreviewed write-back loop is how a
knowledge base poisons itself: one confidently wrong report becomes the precedent that teaches the
next ten answers to be wrong the same way.

## 5. Component choices and why

| Concern | Choice | Reasoning |
|---|---|---|
| Agent framework | **LangGraph** | The requirements are all control-flow requirements: a confirmation interrupt for deletes, a bounded repair loop, a guard that must run before anything else, resumable multi-turn state. LangGraph makes the control flow an explicit, inspectable, testable graph and ships durable checkpointing and `interrupt()` as primitives. A ReAct-only framework (plain LangChain agent, CrewAI) hides exactly the part we must be able to prove correct. |
| Compute | **Cloud Run** | Bursty, request-scoped, long-tailed (a multi-step analysis can take minutes). Cloud Run gives 60-minute request timeouts, per-instance concurrency, scale-to-zero between the exec team's working hours, and no cluster to operate. GKE buys nothing here. |
| Reasoning model | **Gemini 2.5 Pro** | Long context for schema + precedents + history, strong text-to-SQL, native structured output and tool use. |
| Utility model | **Gemini 2.5 Flash** | The guard, the SQL repair and the eval judge run on every turn and must not dominate cost or latency. Roughly an order of magnitude cheaper; the tasks are narrow and well-specified. |
| Conversation state | **Postgres checkpointer** (SQLite in the prototype) | LangGraph's `AsyncPostgresSaver` on Cloud SQL. Transactional, survives instance recycling, and the checkpoint tables double as an audit record of what the agent saw. |
| Preferences / persona | **Firestore** | Single-document reads keyed by user, sub-10 ms, trivially editable by an internal admin page. Relational modelling buys nothing for a preference blob. |
| Golden index | **pgvector on the existing Cloud SQL** | At the realistic scale of this bucket (thousands, not millions, of trios) a dedicated vector service is operational overhead for no gain. pgvector keeps vectors transactional with their metadata and lets hybrid search be one SQL statement. Move to Vertex AI Vector Search only past ~1M vectors. |
| Data access | **BigQuery authorized views + policy tags** | PII must be unreachable, not merely unrequested. The service account can read a view in which the sensitive columns do not exist. |
| Reports | **GCS with object versioning** | Soft delete and restore come free from the storage layer, which is what a "delete" of an executive's report should mean. |
| Tracing | **OpenTelemetry + Langfuse** | OTel for infrastructure spans, Langfuse for prompt/response/tool-call replay, joined on `trace_id`. |

## 6. Prototype scope vs production

| | Prototype (this repo) | Production |
|---|---|---|
| Interface | CLI REPL | Cloud Run + FastAPI, Slack, web |
| Checkpoints | SQLite file | Cloud SQL Postgres |
| Golden index | numpy in-process, cached to `.npz` | pgvector, Eventarc reindex |
| Preferences | `data/preferences.json` | Firestore |
| PII defence | sqlglot AST policy + output scrub | the same, **plus** authorized views and policy tags |
| Persona | `data/persona.md`, re-read every turn | GCS object + admin page, 60 s TTL |
| Reports | local JSON | GCS, versioned, soft delete |
| Traces | JSONL in `logs/` | Cloud Logging → BigQuery, Langfuse |
