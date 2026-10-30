# FarmIQ — Unified Intelligent AI Agent
### Tech stack, what we built, and judge Q&A

---

## 1. The one-liner

FarmIQ turns a farmer's question into a grounded recommendation by combining **real ML predictions, real IoT sensor readings, live weather and the farmer's own profile** — and it never invents a number it did not read.

> "Should I irrigate my wheat?" → the agent checks the soil-moisture sensor, the irrigation model, the 48-hour rain forecast and the crop-specific moisture threshold for wheat, then answers with the actual values and says which of them came from a model versus a sensor.

---

## 2. Tech stack

| Layer | Technology | Notes |
|---|---|---|
| Frontend | React 19 + Vite (JSX, no TypeScript) | Tailwind CSS v4, custom palette (`#216B45`), glassmorphism (`backdrop-blur-md`) |
| Mobile | Capacitor (Android) | Emulator uses `http://10.0.2.2:8001` |
| Backend | FastAPI (Python), async endpoints | `run_in_threadpool` for the synchronous DB/ML calls |
| Database | Supabase PostgreSQL + Supabase Auth | `supabase-py` query builder |
| ML | Trained scikit-learn models (crop, fertilizer, irrigation, yield) | Served through a singleton adapter (`get_adapter()`), models warmed at startup |
| IoT | Existing sensor-ingestion endpoint + `sensor_readings` table | Channels: soil moisture, temperature, humidity, pH, N, P, K, soil temperature |
| Weather | Open-Meteo integration (`app/weather.py`) | Current + forecast + cumulative historical rainfall, cached |
| RAG / LLM | ChromaDB vector store + LLM via Groq / HF Inference Providers (`Llama-3.1-8B-Instruct`) | Relevance threshold 0.30; refuses below it |
| Auth / security | Supabase JWT → `get_current_user`, owner-scoped queries, RLS as a backstop | Service-role key never reaches the frontend |
| Tests | Pytest (backend), Vitest (frontend) | Fake Supabase client, no network in tests |

**Backend architecture at a glance**

```
Question (React chat)
   → POST /api/agent/chat            [auth, validated payload]
      → agent_service.classify_intent        (deterministic keyword router)
      → FarmTools.<only the needed tools>    (owner-scoped DB + ML + weather)
      → agent_service.analyse                (conflicts, staleness, uncertainty)
      → agent_service.compose                (Situation / Observation /
                                              Recommendation / Reason / Warning)
      → rag_service.answer_question          (optional plain-language explanation)
   → structured JSON + evidence + freshness
```

---

## 3. What we built (the AI agent layer)

Nothing was rebuilt. The agent is a new layer that **reuses** the existing ML adapter, DB access layer, weather module, RAG pipeline and design system.

| Piece | File | Role |
|---|---|---|
| Centralized data aggregator + context manager | `backend/app/farm_context_manager.py` | Builds one farm's complete context (profile, sensors, weather, ML) with freshness verdicts; strict per-owner isolation |
| TTL cache | `backend/app/cache.py` | Weather 15 min, context 60 s, agent answers 5 min |
| Tool layer (9 tools) | `backend/app/agent_tools.py` | Each tool returns `{tool, available, data, as_of, note}` — `available: false` + a reason instead of a made-up value |
| Agent engine | `backend/app/agent_service.py` | Intent routing → tool calls → evidence analysis → structured answer |
| HTTP surface | `backend/app/routers/agent.py` | `POST /api/agent/chat`, `GET /api/agent/context` |
| Request/response contracts | `backend/app/schemas.py` | `AgentChatRequest`, `AgentChatResponse`, `AgentContextResponse` |

### The 9 tools

`get_farm_profile()` · `get_sensor_readings()` · `get_weather_information()` · `get_crop_prediction()` · `get_fertilizer_prediction()` · `get_irrigation_prediction()` · `get_yield_prediction()` · `get_farm_history()` · `get_available_farm_recommendations()`

The question decides which tools run. A weather question **only** calls the weather tool — no sensor rows are read, nothing irrelevant is sent to the LLM.

### Response format

```
Situation:      one line on the current farm condition
Observation:    the real sensor / weather / ML findings (values + how old)
Recommendation: the practical action
Reason:         why
Warning:        only when it is actually needed
```

Sections are omitted when there is nothing to say, and a warning is never forced in. English and Marathi are supported through the existing language capability.

### Example (real output shape)

> **Situation:** You asked about irrigation for wheat on Green Valley Farm (drip irrigation).
> **Observation:** Soil moisture is 20% (sensor, 12 minutes ago). The irrigation model recommends irrigating. The 48-hour forecast shows 1 mm of rain.
> **Recommendation:** Irrigate now — soil moisture is below the 45% threshold for wheat.
> **Reason:** At 20% the soil is well under the wheat threshold and the forecast rain is not enough to close the gap.
> **Warning:** The ML irrigation result is a model output, not a guaranteed outcome. The sensor reading and the model agree here.

---

## 4. Why this is not "just a chatbot"

| Principle | How it is enforced |
|---|---|
| Real data only | Every value in the answer traces back to a tool result; missing input becomes `available: false`, never a placeholder |
| Sensors ≠ predictions | ML-sourced lines are labelled "(model output)"; sensor lines carry their own timestamp |
| Conflicts are surfaced | If the model says irrigate and the soil is wet, the disagreement is reported with both sides as evidence |
| Uncertainty is stated | Stale readings (sensor > 6 h, weather > 12 h), demo-flagged data, invalid channels (pH 0–14, moisture 0–100%) and prediction age are all called out |
| No unsafe advice | The agent repeats the model's recommendation and explains it; it does not invent agronomic doses |
| AI can't hide the ML result | The structured answer is built **first**; the LLM explanation is strictly additive and its failure never blocks the real prediction |
| No DB writes by the LLM | The tools are read-only. Consequential actions require explicit user authorisation |
| Owner isolation | Every query filters on `owner_id`; no endpoint accepts an `owner_id` from the client; a foreign `farm_id` simply returns nothing |

---

## 5. Performance & cost

- Async FastAPI endpoints; blocking Supabase/ML calls pushed to a threadpool so one slow lookup can't stall other farmers.
- Three TTL caches (weather 15 min, context 60 s, agent answers 5 min).
- The agent cache key includes each tool's `as_of` timestamp, so a **new sensor reading automatically invalidates** a cached answer — no stale replies.
- Repeating an identical question returns `cached: true` with zero LLM calls.
- ML inference stays completely separate from LLM reasoning.

---

## 6. Testing

- **449 backend tests pass** (was 344 before this work — **105 new, zero regressions**).
  - `tests/test_farm_context_manager.py` — 14
  - `tests/test_agent_tools.py` — 39
  - `tests/test_agent_service.py` — 47
  - `tests/test_agent_api.py` — 19
- Covered scenarios include: all models + sensors available; a missing ML prediction; IoT offline; weather API failure; stale readings; ML conflicting with sensors; an unrelated question; advice requested without enough data; and multiple farmers hitting the API concurrently.
- No network in tests — the weather provider, the LLM and Supabase are all stubbed.

---

## 7. Honest status

| Phase | Scope | Status |
|---|---|---|
| 1 | Data aggregator + farm context manager | ✅ Done |
| 2 | Tools + agent engine + `/api/agent/*` HTTP surface | ✅ Done |
| 3 | Event-based intelligence (thresholds, dedup, cooldown) | ⏳ Planned |
| 4 | Migration `0006_ai_agent.sql` (context snapshots, conversations, advisories, execution logs) | ⏳ Planned |
| 5 | Frontend chat integration in the existing AI Assistant | ⏳ Planned |
| 6 | Full end-to-end test pass | ⏳ Planned |

The irrigation model falls back to a **documented rule-based baseline** when the trained model is unavailable; the response marks which one produced the result (`model` vs `baseline`) rather than mixing them.

---

## 8. Judge Q&A

**Q: What actually makes this an "agent" and not a wrapper around ChatGPT?**
A: The agent owns a tool layer and a reasoning layer. It classifies the farmer's intent, decides which of the nine tools to call, reads only those, then reasons over the results — detecting conflicts, staleness and uncertainty — and only then optionally asks the LLM to phrase the explanation. The LLM never produces the numbers; the tools do.

**Q: How do you stop the LLM from hallucinating an irrigation value?**
A: The LLM is never asked for values. It receives a context block containing only values the tools returned and is used purely for plain-language phrasing. If it fails or returns nothing, the deterministic structured answer is still returned to the farmer.

**Q: Why not use native LLM function calling?**
A: Deliberate engineering choice. The existing system prompt explicitly forbids the model from inventing predictions, and the routing decision is testable and deterministic. A keyword/intent router means the same question always calls the same tools — which is what makes the 449 tests meaningful. It also removes a whole class of prompt-injection risk, since the model cannot choose to read another farmer's data.

**Q: How is multi-tenant privacy guaranteed?**
A: Three layers. The endpoint derives the user from the JWT — the client cannot submit an `owner_id`. Every DB read goes through `db.py`, which filters on `owner_id`. And Supabase RLS policies are the backstop. We explicitly test that farmer B cannot read farmer A's farm, even by passing A's `farm_id`.

**Q: What happens when a sensor is offline or the weather API is down?**
A: The tool returns `available: false` with a reason, the field appears in the `missing` array, and the answer says so directly. The agent narrows the recommendation to what it can actually support instead of guessing.

**Q: What if the ML model and the sensor disagree?**
A: We surface it. The conflict is reported with both pieces of evidence and the agent takes the conservative path — it never silently picks a side. There is also a guard so we never numerically compare the irrigation model's class output with a percentage moisture reading.

**Q: How do you handle stale data?**
A: Every tool result carries `as_of`. Sensor readings older than 6 hours and weather older than 12 hours are flagged, demo-flagged data is disclosed, and physical-range violations (e.g. pH outside 0–14) are marked invalid rather than used.

**Q: Does this cost a lot in LLM calls?**
A: No. Only relevant tools run, results are cached for 5 minutes keyed on data freshness, duplicate questions hit the cache with zero LLM calls, and ML inference is fully separate from LLM reasoning. The advisory event engine (Phase 3) adds dedup + cooldown so a single sensor spike can't spam the farmer or the model.

**Q: What happens with an unrelated question like "what's the weather in Delhi"?**
A: The router classifies it as out-of-domain, no farm tools are called, and the farmer gets a short "here's what I can help with" message with a `fallback` flag — no wasteful data reads and no fabricated farm answer.

**Q: Can the agent change my data or place actions?**
A: No. The tool layer is read-only by design. Any consequential action would require explicit authorisation, and the LLM has no ability to execute database modifications at all.

**Q: How do you know the responses are actually grounded?**
A: Because the answer is assembled from tool results before the LLM is involved, and a test asserts that the assistant receives only values the tools returned. If a value is not in the context, it cannot appear in the answer.

**Q: What about Indian farmers who don't read English?**
A: The response composer has localised labels and supports Marathi through the existing language capability, chosen per request (`language: "en" | "mr"`).

**Q: What's the biggest limitation you'd flag?**
A: The quality ceiling is the ML models and the sensor fleet, not the agent. If the sensor is offline or the trained model is unavailable, the best we can honestly do is say so — and we do. The rule-based irrigation baseline is a documented fallback, clearly labelled as such, not a substitute model.

**Q: What's next?**
A: Event-driven advisories (soil-moisture and temperature thresholds, significant weather changes, new predictions) with duplicate suppression and a cooldown, structured persistence for context snapshots / conversations / advisories / execution logs, and wiring the existing AI Assistant chat UI to the new endpoint — all without touching what already works.

---

*Verify important farming decisions with an expert. FarmIQ can make mistakes.*
