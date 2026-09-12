# Technical Explanation

Read alongside [architecture.md](architecture.md). Each section states what is **built** in this
repo and what is **designed** for production. Code references are clickable.

---

## 1. Hybrid Intelligence — the Golden Bucket

**Built.** Six analyst trios in [`data/knowledge_base/`](../data/knowledge_base), retrieved by
[`src/tools/golden.py`](../src/tools/golden.py) and injected into the system prompt by
[`src/prompts/system_prompts.py`](../src/prompts/system_prompts.py).

### What a trio actually carries

The SQL is the least valuable third. The valuable part is the analyst's *interpretation* and the
house conventions embedded in it. From `04_regional_underspend.json`:

> Decompose revenue into customers × orders per customer × average item value and identify which of
> the three terms actually moved. **Never compare absolute revenue across regions of different
> size.**

That rule is not derivable from the schema and not something a model reliably invents. Without it,
"why is Texas underspending vs California" gets answered with a raw revenue gap that is really a
population difference — technically correct SQL, useless analysis. Each trio therefore ends with an
explicit **Convention** block, and the retrieved trios go into the system prompt under a heading the
model is instructed to treat as binding.

### Retrieval at query time

Rank fusion plus an explicit relevance gate, in [`golden.py:search`](../src/tools/golden.py).

**Ordering is Reciprocal Rank Fusion, not a weighted sum of raw scores.** Cosine similarity against
this corpus lives in a narrow band (~0.52–0.80) while lexical overlap spans 0–1, so the old
`0.75 · cosine + 0.25 · lexical` was dominated by whichever term happened to have more variance, not
by whichever was more informative. RRF fuses the two *rankings* instead, which needs no score
normalisation:

```
fused(trio) = 1/(K + rank_cosine) + 1/(K + rank_lexical)      K = 10
```

`K = 10` rather than the customary 60 because the corpus is six documents, not a search index —
at K = 60 every trio scores within 1% of every other and the fusion stops discriminating. A ranking
carries no vote when it has no signal: if lexical overlap is zero for every trio, `argsort` returns
mere index order, and folding that in would hand an arbitrary trio a full 1/(K+0) boost.

**Relevance is a separate gate, because RRF always ranks something.** Rank fusion has no notion of
"nothing here is relevant" — it will happily return a best-of-six for *what is the capital of
France?* Two absolute conditions decide whether the query is covered at all:

```
cosine.max() ≥ 0.60          and          cosine.max() − cosine.mean() ≥ 0.035
```

Both were calibrated, not guessed, against the six trios: six paraphrased questions that should each
hit a specific trio, and eleven that should hit nothing — seven out-of-domain (*capital of France*,
*reset my password*) and four in-domain but uncovered (*what data do we have*, *average delivery
time*). Measured separation:

| | relevant (n=6) | irrelevant (n=11) |
|---|---|---|
| top cosine | 0.628 – 0.799 | 0.518 – 0.670 |
| top − mean | **0.044 – 0.116** | **0.010 – 0.029** |

Top cosine alone cannot separate them — *what data do we have and what can I ask about?* scores
0.670, above the weakest genuine match at 0.628. The **spread** does, with a clean gap between 0.029
and 0.044. Spread is also the right statistic rather than top1−top2, which collapses toward zero
exactly when two trios are *both* apt and would reject a covered question; the four irrelevant
trios still drag the mean down, so spread survives that case.

Result on the calibration set: **6/6 relevant retrieved in the top 3 (5/6 ranked first), 11/11
irrelevant rejected.** The probes are the live tests in
[`tests/test_retrieval.py`](../tests/test_retrieval.py), so re-tuning a threshold breaks a test
rather than silently changing behaviour.

**Precedent-not-found is an explicit branch**, not an empty string. `search` returns `[]`, `render`
emits a paragraph instructing the model to work from the schema and say plainly that it has no
precedent, and the trace records the decision with the numbers behind it:
`golden_search  mode=hybrid  hits=[]  top=0.617  spread=0.02`.

The embedded document is question + tags + report, not the SQL — managers phrase questions in
business language, and matching against the analyst's prose is what surfaces the right precedent.
Stopwords and tokens of two characters or fewer are dropped before lexical scoring; without that,
*what is the capital of France?* scored 0.500 against a trio purely on `what/is/the/of`, and seven
of the eleven irrelevant probes now score exactly zero.

**Caching.** Vectors are cached to `.index.npz` keyed by a blake2b fingerprint of the corpus, so a
restart costs nothing and a trio edit invalidates automatically. The parsed corpus is held in
process against the knowledge base's newest mtime rather than an `lru_cache`, so editing a trio
takes effect on the next question instead of requiring a restart. Results are memoised per question
for 5 minutes, which is what stops the automatic `retrieve` node and a `search_precedents` tool call
on the same wording from embedding that question twice in one turn.

**If the embedding API is down, retrieval degrades to pure lexical rather than failing** — but
honestly: the gate is then unreliable. Measured lexical-only, *how do I reset my password?* scores
0.500 with a 0.361 spread, higher than most genuine matches, and only 3 of 6 relevant questions rank
their own trio first. The fallback keeps the agent answering; it is not a mode to run in, and the
trace labels it `mode=lexical` so it is never mistaken for the calibrated path.

### Updating the bucket over time

```
conversation → nightly scoring job → analyst review console → GCS → Eventarc → embed → pgvector
```

Candidate signals: the user gave a thumbs-up, the report was saved or shared, the SQL needed zero
repair attempts, and no correction ("no, I meant…") followed in the thread. High-scoring
conversations are queued for an analyst who edits the interpretation and approves.

**The human gate is not optional.** An auto-promoting loop is how the bucket poisons itself: one
confidently wrong report becomes the precedent that teaches the next ten answers the same error, and
retrieval means the error spreads to *similar* questions rather than staying contained. The write
path is deliberately slow; the read path is fast.

---

## 2. Safety & PII Masking — **built**

Four independent layers. Three of them are deterministic code, so **a fully prompt-injected model
still cannot emit PII**.

### Layer 1 — Intent guard (model, fails open)

[`agent.py:_guard`](../src/agent/agent.py) runs the fast path with structured output before anything else.
It blocks instruction-override attempts, requests for identifiable customer data, and off-topic use.

It deliberately **fails open** on API error. The guard defends scope, not PII — PII is defended by
layers 2–4, which cannot fail open because they are not models. Failing closed would turn a
transient model blip into a total outage for a well-behaved manager, in exchange for no real
security. That trade is only sound *because* the deterministic layers exist below it.

### Layer 2 — SQL policy engine (deterministic)

[`src/utils/pii.py:enforce`](../src/utils/pii.py) parses every query into a sqlglot AST — string
matching on SQL is not a control, it is a speed bump — and enforces:

| Control | Rejects |
|---|---|
| Statement type | anything that is not a single `SELECT`/`WITH` — no DML, DDL, multi-statement |
| Table allowlist | anything outside the four approved tables, including `INFORMATION_SCHEMA` |
| Column blocklist | `email`, `first_name`, `last_name`, `street_address`, `postal_code`, `latitude`, `longitude`, `user_geom` — **anywhere** in the tree, including inside a CTE that aliases them away |
| Star projection | `SELECT *` and `t.*` (which would smuggle blocked columns past a name check). `COUNT(*)` is allowed |
| Row cap | injects or clamps `LIMIT 500` |

Customer identifiers are **rewritten, not blocked** — the AST is edited to wrap them in
`SUBSTR(TO_HEX(SHA256(CONCAT(salt, …))), 1, 12)`:

```sql
-- the model wrote                        -- what BigQuery receives
SELECT user_id, SUM(sale_price) AS spend  SELECT SUBSTR(TO_HEX(SHA256(CONCAT('…',
FROM order_items                                  CAST(user_id AS STRING)))), 1, 12) AS user_id,
GROUP BY 1                                       SUM(sale_price) AS spend …
```

This is why "who are our top customers" still works: the manager gets stable pseudonyms they can
track across queries and hand to CRM for resolution, and the agent never sees a real identity.
Rewriting only touches **output projections** — join keys inside CTEs stay raw, so joins still work.
An identifier that appears in a non-aggregate expression (`CAST(user_id AS STRING)`) is rejected
rather than silently passed, closing the obvious bypass; `COUNT(DISTINCT user_id)` is allowed
because an aggregate reveals nothing about an individual.

Unqualified `id` resolves to `users` whenever `users` is in scope — deliberately over-masking, since
over-hashing a product id is a cosmetic bug and under-hashing a customer id is a breach.

### Layer 3 — Output scrub (deterministic)

[`pii.py:scrub`](../src/utils/pii.py) runs on every tool result and on the final answer
([`agent.py:_redact`](../src/agent/agent.py)) — emails, phone numbers, card patterns, IPs. Tuned to
leave financial figures and ISO dates intact; `1,234,567.89` and `2023-01-01` survive, which naive
digit-run regexes destroy.

### Layer 4 — BigQuery authorized views (production)

The service account is granted `bigquery.dataViewer` on a view layer **from which the PII columns
are absent**, with Data Catalog policy tags on the underlying columns as defence in depth. At this
layer a leak is not blocked, it is impossible: there is no query the agent can construct that
returns an email, because the identity it runs as cannot see the column.

### Verification

[`tests/test_pii.py`](../tests/test_pii.py) — 16 tests including the CTE-aliasing bypass, `t.*`
smuggling, cross-project table access, multi-statement injection, and the `CAST` bypass.

---

## 3. High-Stakes Oversight — **implemented**

[`delete_reports` / `undo_delete`](../src/tools/registry.py) + [`src/tools/reports.py`](../src/tools/reports.py)
+ the resume loop in [`src/cli/chat.py`](../src/cli/chat.py).

```mermaid
sequenceDiagram
    participant U as Manager
    participant A as Agent
    participant R as Reports store
    U->>A: "Delete all reports mentioning Client X"
    A->>R: resolve selector → concrete id list (never a bulk predicate)
    R-->>A: 3 reports, all owned by this user
    A-->>U: names the 3 reports, dates, one-line previews
    Note over A: interrupt() — graph checkpoints and stops
    U->>A: "yes"
    A->>R: soft delete + audit row
    A-->>U: "Deleted 3. Say 'undo' within 30 days to restore."
```

**Resolve, then confirm, then act.** The natural-language selector is turned into an explicit list of
report ids in a read-only step. Confirmation is on that list, shown by title — never on the phrase.
`"delete all the reports we made in this conversation"` sets `only_this_conversation`, which matches
on the thread id stamped onto each report at save time, so it is exact rather than a fuzzy match.

**Mechanism.** LangGraph's `interrupt()`, called inside the `delete_reports` tool between resolving
and acting. `ToolNode` re-raises `GraphInterrupt` rather than swallowing it as a tool error, so no
separate delete node is needed: the graph checkpoints mid-tool and returns control, and
`Command(resume=…)` carries the manager's decision back into the same call. Because state is
durable, the confirmation survives an instance restart — the pending action is not held in memory.

**Authorisation is code, not prompt.** The ownership filter (`report.user_id == caller`) lives in the
tool, so "delete Manager B's reports" returns zero resolved ids regardless of what the model was
talked into — `reports.delete` intersects the requested ids with `listing(caller)` before touching
anything, and the audit row records both counts, so a cross-owner attempt is visible as
`requested: 2, ids: [one]`. Deletes are soft: the record keeps a `deleted_at` and a `delete_batch`
stamp and drops out of `listing()`; `undo_delete` restores the most recent batch within a 30-day
window. In production the tombstone is a versioned GCS object rather than a field on a local JSON
file; the flow above is unchanged.

**UX.** Only destructive actions confirm; saving, reading and listing never do. One confirmation
covers a batch. The preview is the point — a manager approves *"these three, from March"*, not
*"a delete operation"*.

---

## 4. Continuous Improvement

### 4.1 User level — **built**

[`src/agent/memory.py`](../src/agent/memory.py) + the `remember_preference` tool. Preferences are a
per-user document, re-read and injected into the system prompt **on every turn**, so a preference
stated mid-conversation applies to the next answer.

Seeded in [`data/preferences.json`](../data/preferences.json):

```json
"manager_a": {"format": "always a markdown table when comparing numbers", "depth": "headline plus three supporting bullets"},
"manager_b": {"format": "short bullet points, never tables",              "depth": "wants the reasoning and the caveats spelled out"}
```

Try it: `/user manager_a` then `/user manager_b`, same question. Preferences are *stated* (the user
says "always give me tables") rather than inferred from behaviour — inferred preferences are
unpredictable and impossible for a user to correct. In production the nightly job proposes
candidates ("Manager A has asked for a chart in 4 of 5 sessions") and the agent asks once before
storing.

### 4.2 System level — **designed**

Three loops, in increasing order of risk and decreasing order of automation:

| Loop | Signal | Change | Gate |
|---|---|---|---|
| Golden Bucket growth | thumbs-up, saved reports, zero-repair SQL | new trios | analyst review |
| Prompt / persona tuning | eval-suite regressions, repair-rate spikes | system prompt, persona | eval suite in CI |
| Failure mining | recurring `sql_rejected` reasons in the trace sink | new policy hints, schema notes, new trios | engineer |

Failure mining is the highest-value and lowest-risk of the three: the JSONL trace already records
every rejection reason, so `GROUP BY error` over a week's traces names the top-10 things the agent
consistently gets wrong. Most resolve to one sentence in the prompt or one new trio.

No unattended weight updates and no unattended prompt edits. Every automated proposal lands in a
human queue.

---

## 5. Resilience & Graceful Error Handling — **built**

### The repair loop

[`src/agent/executor.py:run_sql`](../src/agent/executor.py):

```
enforce (AST policy)  ──fail──┐
dry_run (BigQuery, free) ─────┤→  fast-path repair with the exact error  →  retry (max 3)
execute (capped) ─────────────┘                                       →  give up, tell the truth
```

**Repair is nearly free, by construction.** Validation happens against the sqlglot AST and a
BigQuery **dry run**, which returns the real parser and schema errors and is billed at zero bytes.
Repair itself runs on the fast path. A query is only executed once it is known to be valid, so the expensive
resource is touched once, not four times. This is what satisfies "self-correct without inflating
costs" — the retries are on the free path.

Policy violations feed the *same* loop: the model that selects `email` gets told exactly which rule
it broke and rewrites the query using permitted columns. Safety and resilience share one mechanism.

### Empty results are not errors

An empty result returns `status: "empty"` with explicit guidance not to re-run unchanged. Retrying
identical SQL cannot change an empty result — the fix is semantic (wrong filter value, wrong date
range), so the reasoning model handles it with a small probing query. Blindly repairing here is pure
cost with zero chance of success.

### Bounded everything

| Bound | Value | Failure mode it prevents |
|---|---|---|
| `MAX_SQL_REPAIRS` | 3 | infinite repair spend |
| `MAX_STEPS` | 12 | runaway tool loop |
| `MAX_BYTES_BILLED` | 2 GB | a `CROSS JOIN` costing real money |
| `ROW_LIMIT` | 500 | context blowout, bulk exfiltration |
| `query_timeout_s` | 120 s | a hung request holding an instance |

The byte cap is enforced **twice, and the second one is the real control**. The dry run rejects an
over-budget query before it runs, which is what gives the model a repairable error message; but a
dry-run estimate is an estimate, so `maximum_bytes_billed` also rides on the execution job config
and BigQuery aborts server-side if the plan turns out larger. A cap that only exists in our own
process is advice, not a limit. The timeout is likewise enforced where it bills: `result(timeout=…)`
bounds the wait and the job is **cancelled** on expiry, so a runaway query stops accruing cost
instead of running on unobserved. A timed-out query is deliberately excluded from the retry
predicate — re-running a query that already blew its budget is the one retry that cannot help and
always costs.

The step budget is enforced *deterministically*: [`agent.py:_route`](../src/agent/agent.py) can only
reach `redact` once `exhausted` is set, so a model that keeps emitting tool calls after tools are
unbound still terminates. This was a real bug caught by
[`test_step_budget_forces_termination`](../tests/test_agent.py) — the first implementation relied on
the model respecting unbound tools and looped to the recursion limit.

### Third-party failure

| Failure | Behaviour |
|---|---|
| BigQuery 5xx / rate limit | `google.api_core.Retry`, exponential backoff to 45 s |
| BigQuery down | `QueryError` → the agent reports it in plain language, UI intact |
| Model down (deep path) | caught in `_llm` → "I could not reach the analysis model just now"; conversation state is preserved, the user just re-asks |
| Model down (guard) | fails open; deterministic PII layers still hold |
| Model down (repair) | loop exits immediately rather than burning its budget on a dead service |
| Embeddings down | hybrid retrieval degrades to lexical |
| Any tool raising | `ToolNode(handle_tool_errors=True)` returns the error as an observation for the model to reason about |
| Misconfiguration | caught by `preflight()` at startup with an actionable message, before the REPL opens |

**The CLI never shows a traceback.** Verified by
[`test_llm_outage_degrades_without_crashing`](../tests/test_agent.py).

---

## 6. Quality Assurance — **designed**

### Before deployment — offline suite in CI

| Layer | Method | Gate |
|---|---|---|
| Policy | 16 unit tests incl. known bypasses | 100%, blocking |
| Red team | ~50 injection / PII-extraction prompts | **zero leaks**, blocking |
| SQL executability | eval questions must produce runnable SQL | ≥ 98% |
| SQL correctness | result-set equivalence vs analyst reference SQL (set comparison, not string) | ≥ 90% |
| Groundedness | fast-path judge: every number in the report must appear in a tool result | ≥ 95%, blocking |
| Convention adherence | judge scores the answer against the retrieved trio's Convention block | ≥ 85% |
| Cost / latency | p95 tokens and seconds per question | regression alert |

### Does the report answer the user's *intent*?

Executability and groundedness do not catch the real failure — a correct answer to the wrong
question. Three checks:

1. **Intent restatement.** The judge is given the question and the report and must state what
   question the report actually answers. A human reviews the diffs. This surfaces silent scope
   drift ("last month" answered as "last 30 days") that no numeric check finds.
2. **Claim decomposition.** Each claim is extracted and traced to a tool result. Unsupported claim
   rate is the headline quality metric.
3. **Ambiguity handling.** A held-out set of deliberately ambiguous questions where the *correct*
   behaviour is to ask a clarifying question. Confidently answering an ambiguous question is a
   failure, and it is the failure mode LLM judges are most likely to reward.

### UX evaluation

Offline proxies do not measure UX. In production:

- **Thumbs up/down** with an optional reason — the only direct signal, so make it one keystroke.
- **Correction rate** — turns where the next message is a correction ("no, I meant"). The strongest
  automatic signal that an answer missed.
- **Follow-up depth** — a healthy discussion is 3–5 turns. One turn then abandonment means the first
  answer failed; fifteen turns means the agent is not converging.
- **Report save rate** — did the output justify keeping.
- **Time to first answer**, p50 and p95. Managers abandon past ~30 s with no output, which is why
  the interface streams tool activity rather than blocking on a spinner.
- **Quarterly moderated sessions** with 5–6 managers. Small-n qualitative work catches what metrics
  cannot: the answer was right and they did not trust it.

---

## 7. Observability — **partly built**

[`src/utils/logger.py`](../src/utils/logger.py) writes a structured JSONL event stream with a
`trace_id` per turn, surfaced in the CLI and replayable with `/trace`.

```json
{"ts": 1757, "trace": "a1b2c3", "event": "sql_rejected", "attempt": 0, "kind": "PolicyError", "error": "Column `email` is …"}
{"ts": 1758, "trace": "a1b2c3", "event": "sql_repaired", "before": "SELECT u.email …", "after": "SELECT u.state …"}
{"ts": 1760, "trace": "a1b2c3", "event": "sql_ok", "seconds": 2.1, "repairs": 1, "gb_scanned": 1.4, "cache_hit": false, "rows": 12}
```

Instrumented today, twenty-one events: `guard`, `guard_unavailable`, `golden_search`,
`golden_lexical_fallback`, `embed_failed`, `sql_rejected`, `sql_repaired`, `sql_ok`, `sql_empty`,
`sql_gave_up`, `repair_unavailable`, `bq_execute`, `llm_unavailable`, `budget_exhausted`,
`output_redacted`, `dangling_tool_calls_dropped`, `preference_saved`, `reports_deleted`,
`reports_restored`, `chart_created`, `answer`.

### Metrics at the agent level

| Class | Metric | Why it earns a dashboard slot |
|---|---|---|
| **Correctness** | unsupported-claim rate | the failure that damages trust |
| | SQL repair rate, repairs per query | rising = schema drift or prompt rot |
| | give-up rate (`sql_gave_up`) | questions the agent cannot serve |
| | empty-result rate | usually a filter-value or date-range misunderstanding |
| **Safety** | policy rejections by rule | a spike on one rule = a new bypass being probed |
| | guard block rate + `guard_unavailable` | attack volume, and how long we ran fail-open |
| | **PII leak rate** | must be 0; anything else pages |
| **Cost** | tokens and $ per answered question | the number that decides whether this scales |
| | GB scanned per question, cache-hit rate | BigQuery is the cost floor |
| | budget-exhaustion rate | agent not converging |
| **Latency** | p50/p95 end-to-end, per node | isolates whether the model, BigQuery or retrieval is slow |
| **Quality** | thumbs-up rate, correction rate, save rate | §6 |
| **Availability** | error rate by dependency | which third party is degrading |

### Deep-dive debugging

Every surface carries the same `trace_id`: CLI output, JSONL events, OTel spans, Langfuse traces,
and the BigQuery job labels. From a complaint, the path is: `trace_id` → full message correspondence
(system prompt including the retrieved trios and the persona version, every tool call and result,
every repair attempt with its error) → the exact BigQuery job with its bytes and duration.

The three questions this must answer without guesswork: *what did the model see* (which trios, which
persona version, which preferences), *what did it try* (every SQL attempt, not just the successful
one), *where did it go wrong* (which node, which dependency).

Alerting: PII leak > 0 (page), give-up rate > 5% over 1 h, p95 latency > 60 s, cost per question 2×
its 7-day baseline, guard unavailable > 5 min.

---

## 8. Agility (Persona Management) — **built**

[`data/persona.md`](../data/persona.md) is plain markdown, read **on every turn** by
[`system_prompts.build`](../src/prompts/system_prompts.py). Edit the file, send the next message,
the tone changes. No restart, no redeploy, no code.

It is deliberately separated from the operational instructions: `ROLE` holds the rules that keep the
agent correct and safe, `persona.md` holds only voice, tone, structure and length. The CEO can
rewrite the persona weekly without any possibility of disabling the PII policy or the query
discipline — the persona is not in a position to override anything that matters.

**Production.** The file becomes a GCS object edited through a small internal admin page with a
preview-before-publish step, versioning, and one-click rollback. Cached in-process for 60 s. Every
trace records the persona version, so "reports got worse this week" is answerable by diffing
persona versions against the quality metrics from §6.

---

## 9. Extensibility — **demonstrated**

The brief asks for a system "easily extendable for new capabilities (generating graphs, sending
reports via mail, searching the web for trends)". That is easy to assert and cheap to prove, so
[`create_chart`](../src/tools/registry.py) was added as the worked example — and the interesting
part is what did *not* have to change.

**Adding a capability is one function and one list entry.** `create_chart` is a `@tool`-decorated
function plus a line in `TOOLS`. The graph in [`agent.py:build`](../src/agent/agent.py) is
untouched: `ToolNode(TOOLS)` binds whatever is in the list, `_route` already loops `llm → tools →
llm` for any tool, and the step budget already bounds it. No node, no edge, no router change.

Everything crosscutting applies for free, because it is attached to the pipeline rather than to each
tool:

| the new tool inherits | from |
|---|---|
| PII scrubbing of every title and label | `scrub()` in [`charts.py`](../src/tools/charts.py), the same function `save_report` uses |
| the intent guard running before it | the `guard` node, which precedes every tool call |
| step-budget termination | `_route` and the `budget` node |
| an audit row with user, path and shape | `event("chart_created", …)` into the same trace as every SQL job |
| per-manager preference control | `remember_preference` — no chart-specific plumbing |

That last row is the one worth watching in the recording. Requirement 4.1 asks the agent to learn
"do they prefer charts or text"; there is no code path connecting preferences to charts, yet:

```
manager_a › From now on I prefer charts over tables whenever the numbers allow it.
  → remember_preference {"key": "charts", "value": "prefer charts over tables …"}

manager_a › How do the top 5 product categories compare on net revenue?
  → create_chart {"kind": "barh", …}          ← unprompted
```

The preference is injected into the system prompt on the next turn and the model reaches for the new
tool by itself. A capability added on Tuesday is governed by a preference stated on Monday, with no
code joining them.

**What a tool must not do.** `create_chart` takes numbers, never SQL. Letting it query would fork a
second execution path around the policy engine in [`pii.py`](../src/utils/pii.py), and the PII
guarantee rests on there being exactly one way to reach BigQuery. New capabilities compose with
`query_data`; they do not re-implement it. Validation lives in `charts.render` and raises
`ValueError`; the tool converts that into a sentence the model can act on, so bad arguments become a
retry rather than a crashed turn — the same contract `query_data` has with `QueryError`.

**The other two examples in the brief** land the same way. *Sending a report by mail* is a tool that
reads from the existing report store and calls an SMTP or SendGrid client — and because it is
outbound and hard to retract, it would reuse the `interrupt()` confirmation that `delete_reports`
already established rather than inventing its own. *Searching the web for trends* is a tool wrapping
a search API whose results are untrusted text, so it would return quoted context the model must
attribute, never instructions. **New data sources** are the one case that is not just a tool: a
second warehouse needs its own entry in the table allow-list and its own PII policy, which is why
that allow-list is derived from `BQ_DATASET` in `pii.py` rather than hardcoded.

---

## Data flow summary

| Data | At rest | In transit | Retention |
|---|---|---|---|
| Raw transactions | BigQuery, Google-managed encryption | never leaves BigQuery unaggregated | source-owned |
| PII columns | in BigQuery only | **never** — absent from views, blocked by the AST policy, hashed on output | n/a |
| Conversation state | Postgres checkpoints (SQLite in prototype) | TLS | 90 days |
| Preferences | Firestore (JSON in prototype) | TLS | until the user clears them |
| Saved reports | GCS, versioned (JSON in prototype) | TLS | soft delete + 30-day tombstone |
| Golden trios | GCS + pgvector | TLS | versioned indefinitely |
| Traces | Cloud Logging → BigQuery (JSONL in prototype) | TLS | 30 days hot, 400 days archived |

Query results reaching the model are already aggregated, row-capped and pseudonymised. The model
never receives a raw transaction log row.
