# Design decisions and data findings

This records the choices made while building the prototype, together with the evidence behind them. It is meant as raw material for the thesis methodology chapter.

## 1. Data understanding (RQ2)

Profile of `dummy_chatbot_traces_500.csv`, from `uv run python -m app.data.pipeline`:

| Property | Value |
|---|---|
| Rows / sessions / users | 500 / 500 / 499 (every session has a single turn) |
| Time range | 2026-06-01 08:03 to 2026-06-03 02:15 UTC |
| Distinct prompts / responses | 10 / 10 |
| Prompt languages | English 359, Finnish 141 |
| Apps | 6 (LianaAutomation, LianaPress, LianaMailer, LianaMonitor, LianaAccount, LianaCMS) |
| User roles | User 266, Admin 234 |
| Constant columns | trace name, version, environment, level, error/warning counts, staff flag, costs (empty) |

The findings below shaped the features.

- **Rows are double-encoded.** Each CSV line is one quoted field containing another CSV line. The loader detects and unwraps this, and also accepts normal CSVs (covered by tests).
- **Responses are mostly unrelated to their prompt.** Prompts and responses look randomly paired in the dummy data, for example "How do I create a newsletter?" answered with a segmentation text. Measured response topic alignment is 17% on-topic. 46% of responses are in a different language than the prompt. Both became dashboard KPIs and a topic-alignment matrix, because a customer would want to know this.
- **Costs are empty**, so cost metrics are left out of the dashboard. Tokens serve as the cost proxy.
- **`metadata.resourceId` differs from `userId`** in the dummy data. `userId` is used as the user identity.
- **Multi-turn support.** Every session here has one turn, but the loader keeps `history_turns`/`history_messages` and the session table aggregates over turns, so real multi-turn data works without changes.

## 2. Feature extraction choices

### Language detection
langdetect labels "Can you help me design an email template?" as French. Detection therefore takes the most probable *expected* language (en, fi, sv) among the candidates, and falls back to the top candidate otherwise.

### Prompt normalisation and the choice of an 8B model
Topics should group the same question across languages, so prompts are first translated to English by an SLM. Comparison on the three Finnish prompts:

| Model | "Miten tuon tilaajat Excelistä?" (How do I import subscribers from Excel?) |
|---|---|
| llama3.2:3b | "How do customers use Excelist?" |
| gemma2:2b | "How do I get customers from Excel?" |
| qwen2.5-coder:7b | "How to import those customers from Excel?" |
| llama3.1:8b | "How to import subscribers from Excel?" |

Normalisation runs offline once per distinct text and is cached, so the higher latency of `llama3.1:8b` is affordable. It is set as `data_processing_model`.

### Topic clustering
Agglomerative clustering with cosine distance and average linkage runs over `nomic-embed-text` embeddings, using the task prefix `clustering:`. A threshold of 0.15 gave the 7 natural topics, with each English/Finnish pair merged. 0.20 merged "template design" with "best practices", and 0.25 or higher merged newsletters into them as well. The SLM writes the label for each cluster.

### Response relevance: embeddings instead of an SLM judge
The first design asked an SLM to judge whether each response answers its prompt. On six hand-labelled pairs:

| Judge | Correct |
|---|---|
| llama3.2:3b (3-way label) | 1/6 |
| llama3.1:8b (3-way label) | 4/6 |
| qwen2.5-coder:7b (3-way label) | 3/6 |
| llama3.1:8b / qwen2.5-coder:7b (binary on/off topic) | 4/6 |
| llama3.2:3b (binary) | 2/6 (labels everything off-topic) |

The final method translates responses to English, embeds them, and assigns each to the nearest prompt-topic centroid. It placed 9 of the 10 distinct responses in the correct topic; the Finnish segmentation text went to "best practices". This is deterministic given the cache, and it is cheaper.

### Data updates: cached rebuild instead of appending rows
New exports could be appended to the existing tables, but the topic clusters are computed over all prompts: a new kind of question should form a new topic, and repeated questions should join an existing one. So each sync rebuilds the tables from every imported file. This stays cheap because all model outputs are cached per distinct text. In a test, six new traces with two new prompts took 8.3 s (one new topic, "Text Message Scheduling", with its English and Finnish variants merged), and removing them again took 0.1 s with identical labels. The trade-off: a large batch of new prompts can merge or split existing topics, so topic labels are stable only while the clusters are. The sync is all-or-nothing. SLM failures abort it instead of writing placeholder labels, and the old database stays live until the new one is complete.

## 3. Multi-agent design (RQ1, RQ4, RQ6)

- **No free-form SQL from the agents.** In early tests, 3B models confused metrics and columns. A typed `QuerySpec`, constrained by a JSON schema with enums, removes most of this error class. Normalisation then handles the rest: value snapping, wildcard removal, relative dates.
- **Deterministic where possible.** The Metrics Agent and the online part of the Data Processing Agent use no model, and the Visualization Planning Agent skips its model call for single values and lists. Only steps that need language understanding call an SLM. This keeps latency and token use down, and keeps the numbers exact.
- **A heterogeneous profile.** Query understanding is the hardest step, so the `mixed` profile gives it a code-tuned 7B model and uses 2 to 3B models for visualization and answers. The evaluation compares this against homogeneous 2B and 3B profiles.
- **Grounding the answer agent.** In smoke tests, the answer model (3B) hallucinated numbers when converting rates like `0.9492` into percentages. It also described charts it could not see and enumerated list rows inaccurately. The mitigations: rates are pre-formatted as percentages in the table given to the model, the prompt forbids describing charts or recounting rows, and lists are summarised rather than enumerated. The scorer's faithfulness metric measures what remains.
- **Few-shot examples and required fields.** With nullable `start`/`end` left optional in the JSON schema, constrained decoding let models omit them, so "yesterday" was ignored. Making them required (nullable) fixed this. The examples cover relative dates, shares, top-N, numeric filters, lists and out-of-scope questions, and they are sent as user/assistant turns. Inline `Q:`/`A:` examples in the system prompt made qwen2.5-coder sometimes copy the neighbouring example. The examples deliberately don't paraphrase evaluation questions.
- **The JSON schema must allow what the model wants to say.** Comparing constrained and free generation showed models wanted numeric filter values and a `date` filter. With string-only values and no `date` field, constrained decoding forced them into empty or arbitrary filters. Both are now accepted, and `normalise()` turns `date` filters into the time range. See [evaluation](evaluation.md#iterations) for the effect.
- **Filter grounding.** Models copied filters from examples or invented them, for example `weekday = Tuesday` for "June 2". A deterministic check drops filter values the conversation never mentions, using vocabulary derived from the data. It is configurable (`mas_options.ground_filters`, `MAS_GROUND_FILTERS=0`) so it can be ablated. With the fixed examples it changed no verdict but removed five hallucinated filters, with no false removals.
- **Model residency matters more than model size.** A heterogeneous profile has three models per question. On 16 GB, Ollama did not always keep them resident, and each swap cost about 3.7 s plus a lost prompt cache. The context window was reduced to 4096 tokens to lower memory per model.

## 4. Baseline fairness

The baseline gets the same data context and answer instructions as the MAS, and one SQL repair attempt, matching the MAS repair loop. It differs only in having no agent decomposition and no typed query interface. Its charts come from the same deterministic rules the visualization agent falls back to.

## 5. Known limitations

- The dummy data has only 10 distinct prompts, so topic and intent extraction is easy here. It needs re-validation on real traces.
- The evaluation set (53 questions) is hand-written by the system author, so it may favour question types the spec supports. The baseline can in principle answer arbitrary SQL questions that the spec cannot express (see failures in the evaluation report).
- Timings come from one Apple-silicon laptop running Ollama, so absolute numbers are hardware-specific; compare configurations relative to each other.
- Usefulness and understandability (RQ5) need human ratings. `ratings_template.csv` is produced for that.
