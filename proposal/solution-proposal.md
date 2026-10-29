# Proposed Solution: Small Language Model-based Multi-Agent System for Interactive Prompt Analytics

**Student:** Aidul  
**Supervisor:** Md Mahade Hasan
**Tampere University**

---

## 1. Summary

This document describes how I plan to address the research proposal *"Small Language Model-based Multi-Agent Systems for Interactive Prompt Analytics"*. The goal is a prototype that turns raw chatbot trace data into insight in two ways:

- a **dashboard** with predefined analytics views, and
- a **chat interface** where users ask questions about the data in natural language.

The chat is powered by a **multi-agent system (MAS) of small language models (SLMs)** that runs fully locally. To answer the research questions, the MAS will be compared with a **single-model baseline** on correctness, latency, resource use and maintainability.

The core idea of the solution is that the SLMs only do the parts that need language understanding. Everything that must be exact (filtering, counting, aggregating) is done by deterministic code. The agents communicate through a small, typed query format instead of free-form SQL. This should make small models reliable enough for analytics, and it makes every answer traceable.

## 2. Problem understanding

Companies running chatbots collect large volumes of trace data: prompts, responses, timestamps, applications, user roles, token usage and latency. Non-technical stakeholders want answers such as "Which topics do admins ask about most?" or "How many Finnish prompts got an off-topic answer yesterday?". Today this requires an analyst to write queries.

Large cloud LLMs could answer such questions, but they raise **privacy, cost and dependency** concerns, because trace data contains customer prompts. Small models (2–8B parameters) can run on a laptop or a modest server, but on their own they are known to be unreliable at complex tasks such as writing correct SQL. The proposal asks whether **splitting the task among specialised small agents** closes this gap.

### 2.1 The provided dataset

The provided dummy dataset is an export of 500 traces from an LLM observability tool. It comes from an AI help assistant embedded in Liana's marketing products (LianaMailer, LianaCMS, LianaPress, LianaAutomation, LianaMonitor, LianaAccount). Each row is one interaction and contains:

- **who and where:** user, session, organisation, application and user role (Admin or User);
- **content:** the conversation sent to the assistant (JSON message history, where the last user message is the prompt), the assistant's response, and the system instructions;
- **performance:** latency and input/output token counts. The cost fields are empty, so tokens serve as the cost measure.

Some properties of the data shape the solution:

- **Messy encoding.** Each CSV row is double-encoded, and the conversation and metadata are nested JSON.
- **Multilingual.** The prompts are in English and Finnish, so analytics must group the same question across languages.
- **Prompts and responses look randomly paired.** Many answers are off-topic or in another language than the question, which makes response-quality metrics meaningful to show.
- **Little variety.** There are only ten distinct prompts and every session has a single turn. The pipeline must therefore be designed for richer real data (multi-turn sessions, many topics) and validated on it later.
- **Constant monitoring fields.** Several columns (level, error counts, environment) are constant and can be ignored.

## 3. Proposed solution



### 3.1 Overall architecture

The system will have three layers:

1. **Data layer.** It ingests trace exports (CSV, JSON, JSONL or Excel) from file uploads or watched folders, then cleans and parses them, extracts features, and stores everything in an embedded analytical database (DuckDB). It keeps the analysis up to date as new traces arrive.
2. **Analytics layer.** It contains
  - a deterministic metrics library used by the dashboard, and
  - the multi-agent system (with the single-model baseline next to it) used by the chat.
3. **Presentation layer.** This is a web application with a dashboard page and a chat page.

The flow of a chat question through the MAS:

> User question → **Query Understanding Agent** → typed query spec → **Metrics Agent** (executes on the database) → **Visualization Planning Agent** → **Answer Generation Agent** → answer + table + chart

The **Data Processing Agent** prepares the data and its description beforehand.

### 3.2 Data processing and feature extraction

Real trace exports are messy. Fields such as the conversation history and the metadata are nested JSON inside CSV columns. The data is multilingual (for example English and Finnish), and some columns are empty or constant. The Data Processing Agent will:

- **Parse and clean the raw export.** It will extract the last user prompt and the conversation history, unpack the metadata (application, user role, organisation), normalise timestamps and remove duplicates.
- **Compute per-prompt features.** These are prompt and response length, language (prompt and response), token usage and latency.
- **Extract semantic features with SLMs**, run offline and cached so they are computed once per distinct text:
  - translate and normalise prompts to English, so the same question in different languages is grouped together;
  - classify the intent (how-to, troubleshooting, examples, etc.);
  - cluster topics using text embeddings, with an SLM writing a readable label for each cluster.
- **Assess response quality.** It will check whether the response language matches the prompt language, and whether the response is on-topic for the question. The on-topic check compares embeddings of prompt and response topics.
- **Reconstruct sessions** from multi-turn conversations.

The agent also produces a compact **data context** (schema, known values, time range) that the other agents use. This way the models only refer to values that actually exist.

#### Data sources and updates

A chatbot produces new traces every day, so the system cannot depend on one file copied into the project. Data will enter through a **data sources** component:

- **File upload** from the user interface, accepting the common export formats: CSV, JSON, JSONL and Excel. Each file is validated before it is accepted. Every trace needs an identifier, a timestamp and the user prompt, and the user sees how many of the traces are new.
- **Watched folders**, where exports are dropped automatically (for example a scheduled Langfuse export or a shared drive). Each folder has a sync interval (for example every 15 minutes, hourly or daily) and can also be synced on demand.

Updates will be **incremental from the user's point of view**:

- Imported files are kept, and traces are deduplicated by their identifier, so a newer export of the same trace replaces the older one.
- Because every SLM output is cached per distinct text, a sync only runs the language models on prompts and responses that have not been seen before. Adding a day of traces should therefore cost seconds rather than a full reprocessing.
- Topic clustering is recomputed over all prompts, so new kinds of questions can form new topics and repeated questions join existing ones.

Each sync is **all-or-nothing**. The new database is built next to the current one and swapped in only when it is complete. If something fails, for example the model runtime is unavailable, the current data stays in use and the error is reported. After a sync the data context is refreshed, so the dashboard and the agents work on the updated data, including its new date range (what "today" and "yesterday" mean). A sync history records when each update happened, what triggered it, and how many traces it added.

Direct connectors (for example the Langfuse API or a database) are left as an extension. They would plug into the same validation and sync steps.

### 3.3 Metrics and dashboard

A deterministic metrics library will compute the dashboard views:

- KPIs: prompts, sessions, users, average latency and tokens;
- volume over time;
- topic and language distributions;
- breakdowns by application and user role;
- latency and token statistics;
- response quality (on-topic rate, language-match rate);
- most frequent prompts and session statistics.

All views share filters (date range, application, user role, language, topic). The same library is reused by the Metrics Agent, so the chat and the dashboard always agree on the numbers.

### 3.4 The multi-agent system

The five agents from the proposal, with their planned responsibilities:


| Agent                      | Responsibility                                                                                 | Uses an SLM?                                     |
| -------------------------- | ---------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| **Data Processing**        | Prepares the cleaned data, features and data context                                           | Offline only (translation, intent, topic labels) |
| **Query Understanding**    | Turns the question and conversation history into a structured **query spec**                   | Yes                                              |
| **Metrics**                | Validates the spec, compiles it to SQL and executes it                                         | No (deterministic tool agent)                    |
| **Visualization Planning** | Builds a chart for the result, follows the user's chart requests, and links to the related dashboard view | Yes, with rule-based fallback                    |
| **Answer Generation**      | Writes a short natural-language answer grounded in the result table                            | Yes                                              |


**Typed query specification.** The central design decision is that the Query Understanding Agent will **not write SQL**. It fills in a small JSON structure:

- the kind of query (aggregate or list of prompts);
- metrics, group-by dimensions, filters and time range;
- ordering and limit.

The model's output is constrained to valid metric, dimension and field names through JSON-schema-constrained decoding, and it is validated in code. A compiler then turns the spec into parameterised SQL. This should remove a whole class of errors that small models make with free-form SQL, such as invented columns, wrong SQL dialect and syntax errors. It also prevents injection of user text into queries.

**Validation and normalisation.** Before execution, deterministic code will:

- snap filter values to values that exist in the data (for example "finnish" → `fi`, typos fixed by fuzzy matching);
- resolve relative dates ("yesterday", "today");
- check that filters are grounded in the question, to catch filters the model invented.

**Dynamic visualizations.** Charts in the chat will be generated from each question rather than taken from a fixed set:

- The Visualization Planning Agent produces a typed **chart spec**: chart type, x axis, series and title. Code validates it against the result (for example, a line chart needs a time axis and a pie chart needs few categories) before rendering.
- **Explicit chart requests** such as "show this as a pie chart" or "plot it per day" are captured in the query spec and honoured.
- **Chart-only follow-ups** such as "make it a line chart" or "split it by language" re-plan only the chart on the existing result, without running a new query.
- Supported chart types: KPI number, bar (including grouped and stacked), line, pie, scatter, histogram, heatmap and table. Results with two dimensions (for example apps × languages) are reshaped into one series per category.
- The user can also switch the chart type or hide series directly in the UI.

**Orchestration and recovery.** A lightweight orchestrator in plain Python passes a shared context between agents. An agent framework is deliberately not used in the first version: the workflow is a fixed pipeline, plain code makes every millisecond and token attributable to a specific agent (important for the latency and maintainability comparison), and small models follow short, fully controlled prompts better than the long built-in prompts of frameworks such as CrewAI or AutoGen. Porting the orchestrator to a graph framework such as LangGraph is planned as a later extension (section 8). The orchestrator handles failures as follows:

- An invalid spec is sent back to the Query Understanding Agent with the error, for self-repair.
- An execution error triggers one re-plan.
- If the visualization agent fails, deterministic chart rules are used instead.
- Out-of-scope questions (for example "Write me a poem") are detected and politely refused.

**Conversation memory.** The last few turns (question and spec) are kept, so follow-up questions such as "And only for Finnish prompts?" modify the previous query. Conversations are stored persistently (section 3.6), so this memory is restored when a saved chat is reopened, even after a restart.

**Configurable models per agent.** A configuration file decides which model each agent uses. This makes it possible to study homogeneous setups (all agents use the same 2B or 3B model) and heterogeneous setups (a stronger model for query understanding, smaller ones elsewhere).

**Transparency.** Every agent step is logged with its model, latency, token counts and output. The chat UI will show this "agent trace" together with the executed SQL, so users and evaluators can see how an answer was produced.

### 3.5 Single-model baseline

As the comparison point, a baseline will use **one SLM** that writes SQL directly from the question, followed by a second call that writes the answer. To keep the comparison fair, the baseline gets:

- the same data context and answer instructions;
- one SQL repair attempt;
- the same chart rules.

The only differences are the agent decomposition and the typed query interface, which is exactly what the research questions are about.

### 3.6 User interface

- **Dashboard page** with the views described in section 3.3 and global filters.
- **Chat page** with three modes: *multi-agent*, *single model* and *compare*. Compare mode answers the same question with both systems side by side. Each answer will show:
  - the result table and a dynamically generated chart, with controls to change the chart type;
  - a link to the relevant dashboard section;
  - the expandable agent trace.
- **Saved chat sessions**, as in common chat applications:
  - every conversation is saved automatically;
  - a sidebar lists past chats grouped by date (today, yesterday, previous 7 days, …), with search, rename and delete;
  - each chat has its own link, so it can be reopened or shared with its answers, charts and traces;
  - chats are stored locally in a small embedded database (SQLite), consistent with the privacy goal.
- **Data sources page** for uploading exports (drag and drop), adding watched folders with their sync interval, starting a sync, and viewing the current dataset, the imported files and the sync history. The dashboard refreshes automatically after an update.
- A profile selector to switch between model configurations during demos.



### 3.7 Technology stack


| Part                | Technology                                                                                                            |
| ------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Local model runtime | Ollama                                                                                                                |
| Candidate models    | Llama 3.2 3B, Gemma 2 2B, Qwen 2.5 Coder 7B, Llama 3.1 8B (offline feature extraction), nomic-embed-text (embeddings) |
| Backend             | Python, FastAPI, DuckDB (analytics), SQLite (saved chats, data source registry), pandas, Pydantic, scikit-learn       |
| Agent orchestration | Plain Python orchestrator (first version); LangGraph considered for a later version                                   |
| Frontend            | React, TypeScript, Vite, Recharts, Tailwind CSS                                                                       |
| Evaluation          | Python scripts producing CSV/Markdown reports and plots                                                               |


Everything runs locally, so no trace data leaves the machine.

## 4. Evaluation plan



### 4.1 Test set

A set of about **50 natural-language questions**, each with a **gold answer computed by hand-written SQL**, covering these categories:

- counts, aggregates and rankings (top-N);
- breakdowns and time-based questions (per day, yesterday, specific dates);
- quality questions (on-topic rate, language match);
- lists of prompts with filters;
- multilingual questions (asked in Finnish);
- multi-turn follow-ups;
- visualization requests (a specific chart type, or changing the chart of a previous answer);
- out-of-scope questions that should be refused.

Where several answers are acceptable (for example ties in a ranking), alternatives will be recorded.

### 4.2 Configurations

Both systems (MAS and baseline) will be run with several model profiles:

- **Tiny:** all components use a ~2B model (Gemma 2 2B).
- **Small:** all components use a ~3B model (Llama 3.2 3B).
- **Mixed:** a 7B code model for query understanding or SQL, and 2–3B models for visualization and answers.



### 4.3 Metrics


| Aspect                           | Measure                                                                                                                                              |
| -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| Correctness                      | Result accuracy (the returned table matches the gold answer) and answer accuracy (the correct value appears in the text)                             |
| Faithfulness                     | Share of numbers in the answer that are supported by the result (detects hallucinated numbers)                                                       |
| Visualization quality            | Whether the chart type and axes match an explicit request or a reference chart for the question; share of charts the validator rejected                                      |
| Robustness                       | Execution error rate, retry/repair rate, correct refusal of out-of-scope questions                                                                   |
| Latency                          | End-to-end time per question, per-agent time, and model loading time                                                                                 |
| Resource use                     | Number of LLM calls, tokens per question, peak memory of the model runtime                                                                           |
| Update cost                      | Time to integrate a new batch of traces, in relation to the number of new distinct texts; stability of topic labels across updates                     |
| Maintainability                  | Lines of code, number of functions and branches, prompt size per component; qualitative assessment of how easy it is to add a metric or swap a model |
| Usefulness and understandability | Human ratings of a sample of answers (template prepared for raters)                                                                                  |




### 4.4 Procedure

- Deterministic decoding (temperature 0, fixed seed) for reproducibility.
- Models are unloaded between configurations, and a warm-up question is excluded from timing.
- **Ablation studies.** Safeguards such as the filter grounding check can be switched off, to measure how much each one contributes.
- Results broken down by category, to show *where* each approach succeeds or fails.
- Iterative improvement: failures from a first evaluation round are analysed, the system is improved, and the evaluation is repeated. The changes and their effects are documented.



## 5. How the solution addresses the research questions


| Research question area                                             | How it is addressed                                                                                                                         |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------- |
| **RQ1** – Design of an SLM-based multi-agent architecture          | Five agents with clear roles, typed interfaces, an orchestrator and per-agent model configuration (section 3.4)                             |
| **RQ2** – Understanding and preparing chatbot trace data           | Data processing pipeline, data-quality profiling, multilingual feature extraction, topic/quality features, and data sources with incremental updates (section 3.2) |
| **RQ3** – Which analytics are valuable to present                  | Dashboard metrics and views, filters, and links between chat answers and dashboard sections (section 3.3)                                   |
| **RQ4** – Reliable translation of questions into data operations   | Typed query spec, constrained decoding, validation, normalisation, grounding and repair loops instead of free-form SQL (section 3.4)        |
| **RQ5** – Correctness and usefulness of answers                    | Gold-answer test set, accuracy and faithfulness metrics, human ratings (section 4)                                                          |
| **RQ6** – Efficiency of SLM-based agents (latency, resources)      | Per-agent timing, token and memory measurements across model profiles; the effect of model size and of switching between models (section 4) |
| **RQ7** – Multi-agent vs. single model (including maintainability) | Side-by-side comparison with the baseline on all metrics, plus code and prompt size analysis (sections 3.5 and 4)                           |


*(The research question descriptions above are short summaries; the exact wording follows the original proposal.)*

## 6. Work plan


| Phase | Work                                                                      | Output                                                 |
| ----- | ------------------------------------------------------------------------- | ------------------------------------------------------ |
| 1     | Data understanding: profile the trace data, build the loader and cleaning | Data-quality report, clean dataset                     |
| 2     | Feature extraction (language, topics, intent, response quality, sessions); data sources with upload, watched folders and incremental sync | Feature database that stays up to date |
| 3     | Metrics library and dashboard                                             | Working dashboard                                      |
| 4     | Single-model baseline and chat interface with saved chat sessions         | Baseline chat with chat history                        |
| 5     | Multi-agent system: query spec, five agents, orchestrator, agent trace, dynamic visualizations | MAS chat with compare mode and dynamic charts |
| 6     | Evaluation: test set, runner, scoring, first evaluation round             | Results and failure analysis                           |
| 7     | Improvement round and ablations, second evaluation                        | Final results                                          |
| 8     | Documentation and thesis writing                                          | Architecture and design documentation, thesis chapters |


Phases 1–5 are expected to take the first half of the project and phases 6–8 the second half. They will be aligned with the timeline in the original proposal.

## 7. Risks and mitigations


| Risk                                                                               | Mitigation                                                                                                                                                        |
| ---------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Small models produce wrong or invented query parameters                            | Constrained decoding, validation, value snapping, grounding check, self-repair loop                                                                               |
| Small models hallucinate numbers in answers                                        | Answers are generated only from the result table, rates are pre-formatted, and faithfulness is measured                                                           |
| Multilingual data (Finnish/English) confuses language detection and topic grouping | Translation to English before clustering; detection restricted to expected languages                                                                              |
| Running several models increases latency or memory                                 | Deterministic agents where possible, skipping the visualization model for trivial results, measuring model loading, and comparing single-model and mixed profiles |
| The dummy data may differ from real traces                                         | Loader designed to handle multi-turn conversations and missing fields; validation on real data when it becomes available                                          |
| The test set may be biased towards the system's capabilities                       | Categories defined before tuning, few-shot examples kept separate from test questions, baseline allowed arbitrary SQL                                             |
| Users request charts the result cannot support (e.g. a pie chart of 50 categories)  | Chart specs are validated against the result; an explanation and a suitable alternative chart are shown instead                                                   |
| Uploaded exports are malformed or use a different format                           | Validation before import with a clear error per file; a tolerant loader for the common export layouts; failed syncs keep the current data                          |
| New data changes the topic clusters, so labels shift between updates               | Labels cached per cluster; stability of topics across updates measured; clustering threshold reviewed on real data                                                 |
| Stored chat history contains sensitive questions                                   | Chats are stored only locally, can be deleted by the user, and the storage location is configurable                                                               |




## 8. Expected outcomes

1. A working, locally running prototype with a dashboard and a chat interface over chatbot trace data.
2. A reusable multi-agent design for SLM-based analytics with a typed query interface.
3. An empirical comparison of the multi-agent system and a single-model baseline across several model sizes, covering correctness, latency, resource use and maintainability.
4. Documentation of design decisions and lessons learned, which forms the basis of the thesis.

### Possible extensions (later versions)

- **Agent framework comparison.** Port the orchestrator to LangGraph and compare it with the plain-Python version on code size, latency overhead and ease of change. This would add a further maintainability data point.
- Validation on real, anonymised trace data with multi-turn sessions and cost information.
- **Direct data connectors**, for example pulling new traces from the Langfuse API or reading from a database, on top of the same validation and sync steps.
- Exporting chat answers and charts (for example to a report) and pinning chat-generated charts to the dashboard.



## 9. Points to discuss

- Is real (anonymised) trace data available for a final validation, in addition to the dummy dataset?
- Are there specific questions or metrics the company considers most important for the dashboard and the test set?
- How will new traces reach the system in practice: manual exports, a scheduled export to a folder, or direct API access to the tracing platform? This decides which connector to prioritise.
- Is there a hardware target for deployment (for example a laptop versus a server with a GPU)? It affects which model sizes are realistic.
- Should the human usefulness ratings involve company stakeholders, or other students and researchers?

