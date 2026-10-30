"""The AI agent's tool layer.

Eleven read-only tools, each scoped to one authenticated farmer. Every tool

* reads through :mod:`app.db`, which filters on ``owner_id`` (defence in depth
  on top of RLS), so no tool can ever return another farmer's row;
* returns real values or an explicit ``available: False`` with a reason —
  it never substitutes a placeholder, a default or an estimate;
* carries ``as_of`` so the caller can state how old the data is.

Reused, not duplicated
----------------------
* ``app.farm_context_manager`` — farm / sensor / weather / ML sections, including
  the field whitelist and the freshness verdicts.
* ``app.decision_engine.build_plan`` — the existing rule engine, used for the
  irrigation baseline and the available recommendations. No agronomic rule is
  re-implemented here.
* ``app.db`` — owner-scoped reads; ``app.ai_context`` — the LLM field whitelist.

Reads are lazy and cached per instance: a question about the weather does not
also read the sensor history, and asking for two predictions does not re-read
the prediction table.

The two newest tools (``get_drought_context``, ``get_organic_guidance``) read
the latest *saved* assessment / comparison from the drought and farming modules.
They surface only the top-level summary fields — severity, recommendations,
method preference, resource availability — not the full nested recommendation
tree, which would exceed the context window and include field-level detail the
LLM should not rephrase.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app import db
from app import farm_context_manager as fcm
from app.ai_context import READING_FIELDS, build_farm_context
from app.decision_engine import build_plan

logger = logging.getLogger("farmiq.agent.tools")

# The exact set of tool names the agent is allowed to call.
TOOL_NAMES: tuple[str, ...] = (
    "get_farm_profile",
    "get_sensor_readings",
    "get_weather_information",
    "get_crop_prediction",
    "get_fertilizer_prediction",
    "get_irrigation_prediction",
    "get_yield_prediction",
    "get_farm_history",
    "get_available_farm_recommendations",
    # Phase 2 additions — organic farming and drought context
    "get_drought_context",
    "get_organic_guidance",
)

# The predictions table holds two vocabularies for the same domains: the
# prediction endpoints store "crop"/"fertilizer"/"yield"/"irrigation" while the
# voice assistant stores "crop_recommendation"/"fertilizer_recommendation"/
# "yield_prediction". Normalising here means a tool finds its row no matter
# which surface produced it.
_DOMAIN_ALIASES: dict[str, tuple[str, ...]] = {
    "crop": ("crop", "crop_recommendation"),
    "fertilizer": ("fertilizer", "fertilizer_recommendation"),
    "yield": ("yield", "yield_prediction"),
    "irrigation": ("irrigation",),
}
PREDICTION_DOMAINS: tuple[str, ...] = tuple(_DOMAIN_ALIASES)

_ALIAS_TO_DOMAIN: dict[str, str] = {
    alias: domain for domain, aliases in _DOMAIN_ALIASES.items() for alias in aliases
}

# One page of prediction history is enough for both "latest per domain" and the
# history tool; larger reads would only widen what could reach the LLM.
_HISTORY_SCAN = 50
_MAX_HISTORY_LIMIT = 20
_MAX_RECOMMENDATIONS = 5


class ToolArgumentError(ValueError):
    """A tool was called with an argument it cannot honour.

    Raised instead of silently ignoring the argument: an invalid request must
    not quietly succeed with different semantics.
    """


def _result(
    tool: str,
    available: bool,
    *,
    data: Any = None,
    as_of: Optional[str] = None,
    note: str = "",
) -> dict[str, Any]:
    return {"tool": tool, "available": bool(available), "data": data, "as_of": as_of, "note": note}


class FarmTools:
    """All nine tools bound to one farm and one owner."""

    def __init__(
        self,
        client: Any,
        owner_id: str,
        *,
        farm_id: Optional[str] = None,
        now: Optional[datetime] = None,
        weather_fetcher: Optional[Any] = None,
    ) -> None:
        if not owner_id or not str(owner_id).strip():
            raise ToolArgumentError("owner_id is required.")
        self._client = client
        self._owner_id = owner_id
        self._farm_id = farm_id
        self._now = now or datetime.now(timezone.utc)
        self._weather_fetcher = weather_fetcher
        self._cache: dict[str, Any] = {}
        self._loaded = False

    # ── Lazy readers ────────────────────────────────────────────────────

    def _ensure_farm(self) -> None:
        if not self._loaded:
            self._cache["farm_row"] = fcm.load_farm(self._client, self._owner_id, self._farm_id)
            self._loaded = True

    def _farm_row(self) -> Optional[dict]:
        self._ensure_farm()
        return self._cache["farm_row"]

    def _reading_row(self) -> Optional[dict]:
        if "reading_row" not in self._cache:
            section = fcm.sensor_section(
                self._client, self._owner_id, self._farm_row(), self._now
            )
            # The section carries ``observed_at``; ``created_at`` is the column
            # name the decision engine and the reading whitelist expect.
            self._cache["reading_row"] = (
                {**section, "created_at": section["observed_at"]} if section else None
            )
        return self._cache["reading_row"]

    def _prediction_rows(self) -> list[dict]:
        """Newest-first prediction rows with a normalised ``domain``."""
        if "prediction_rows" not in self._cache:
            rows: list[dict] = []
            try:
                found, _ = db.list_predictions(
                    self._client, self._owner_id, limit=_HISTORY_SCAN, offset=0
                )
                for row in found:
                    normalised = _ALIAS_TO_DOMAIN.get(str(row.get("domain") or "").strip())
                    rows.append({**row, "domain": normalised or row.get("domain")})
            except Exception as exc:  # noqa: BLE001 — history is best-effort
                logger.warning("Could not read prediction history: %s", exc)
            self._cache["prediction_rows"] = rows
        return self._cache["prediction_rows"]

    def _latest_prediction(self, domain: str) -> Optional[dict]:
        for row in self._prediction_rows():  # already newest-first
            if row.get("domain") == domain:
                return row
        return None

    def _weather_raw(self) -> Optional[dict]:
        if "weather_raw" not in self._cache:
            self._cache["weather_raw"] = fcm.weather_report(
                self._farm_row(), self._now, self._weather_fetcher
            )
        return self._cache["weather_raw"]

    def _latest_assessment(self) -> Optional[dict]:
        if "assessment" not in self._cache:
            row: Optional[dict] = None
            try:
                row = db.get_latest_drought_assessment(self._client, self._owner_id)
            except Exception as exc:  # noqa: BLE001 — optional context
                logger.warning("Could not read the latest drought assessment: %s", exc)
            self._cache["assessment"] = row
        return self._cache["assessment"]

    def _plan(self) -> dict[str, Any]:
        """The existing deterministic plan for this farm (cached)."""
        if "plan" not in self._cache:
            farm = self._farm_row() or {}
            readings = self._reading_row()
            ml_predictions = {
                domain: self._prediction_output(domain)
                for domain in ("irrigation", "fertilizer")
            }
            try:
                plan = build_plan(farm, readings, self._weather_raw(), ml_predictions)
            except Exception as exc:  # noqa: BLE001 — a bad stored row must not break the agent
                logger.warning("Could not build the farm plan: %s", exc)
                plan = {"actions": [], "summary": "", "action_count": 0}
            self._cache["plan"] = plan
        return self._cache["plan"]

    def _prediction_output(self, domain: str) -> Optional[dict[str, Any]]:
        row = self._latest_prediction(domain)
        if not row:
            return None
        output = row.get("output") or {}
        return {
            "prediction": output.get("prediction"),
            "label": output.get("label"),
            "source": row.get("source") or "model",
        }

    # ── Tools ───────────────────────────────────────────────────────────

    def get_farm_profile(self) -> dict[str, Any]:
        """Farm identity and agronomic profile (location, area, soil, crop)."""
        farm = self._farm_row()
        if not farm:
            return _result(
                "get_farm_profile",
                False,
                note="No farm is saved for this account yet.",
            )

        section = fcm.farm_section(farm) or {}
        data: dict[str, Any] = {k: v for k, v in section.items() if k != "meta"}

        # Growth stage is recorded on the saved drought assessment, not on the
        # farm row; it is only added when that assessment actually has one.
        assessment = self._latest_assessment()
        if assessment and assessment.get("growth_stage"):
            data["growth_stage"] = assessment["growth_stage"]
            data["growth_stage_source"] = "latest drought assessment"

        return _result(
            "get_farm_profile", True, data=data, as_of=farm.get("created_at")
        )

    def get_sensor_readings(self) -> dict[str, Any]:
        """The newest IoT reading, with its freshness and any bad channels."""
        section = fcm.sensor_section(
            self._client, self._owner_id, self._farm_row(), self._now
        )
        if not section:
            return _result(
                "get_sensor_readings",
                False,
                note="No sensor readings have been received for this account.",
            )

        present = {
            channel: section[channel]
            for channel in READING_FIELDS
            if section.get(channel) is not None
        }
        data = {
            **present,
            "observed_at": section.get("observed_at"),
            "age_hours": section.get("age_hours"),
            "freshness": section.get("freshness"),
            "missing_channels": section.get("missing_channels"),
            "invalid_channels": section.get("invalid_channels"),
            "is_demo": section.get("is_demo"),
            "devices": section.get("devices"),
        }
        return _result(
            "get_sensor_readings", True, data=data, as_of=section.get("observed_at")
        )

    def get_weather_information(self) -> dict[str, Any]:
        """Current weather and rainfall totals/forecast for the farm's location."""
        section, _warnings = fcm.weather_section(
            self._farm_row(), self._now, self._weather_fetcher
        )
        if not section:
            return _result(
                "get_weather_information",
                False,
                note="Weather is not available for this farm right now.",
            )
        data = {k: v for k, v in section.items() if k != "meta"}
        return _result(
            "get_weather_information", True, data=data, as_of=section.get("observed_at")
        )

    def _prediction_tool(self, tool: str, domain: str) -> dict[str, Any]:
        row = self._latest_prediction(domain)
        if not row:
            return _result(
                tool,
                False,
                note=f"No stored {domain} prediction is available for this account.",
            )
        output = row.get("output") or {}
        data = {
            "domain": row.get("domain"),
            "prediction": output.get("prediction"),
            "label": output.get("label"),
            "source": row.get("source"),
            "recommendations": output.get("recommendations"),
            "details": output.get("details"),
            "inputs_used": row.get("input"),
        }
        return _result(tool, True, data=data, as_of=row.get("created_at"))

    def get_crop_prediction(self) -> dict[str, Any]:
        """The most recent stored crop recommendation."""
        return self._prediction_tool("get_crop_prediction", "crop")

    def get_fertilizer_prediction(self) -> dict[str, Any]:
        """The most recent stored fertilizer recommendation."""
        return self._prediction_tool("get_fertilizer_prediction", "fertilizer")

    def get_yield_prediction(self) -> dict[str, Any]:
        """The most recent stored yield prediction."""
        return self._prediction_tool("get_yield_prediction", "yield")

    def get_irrigation_prediction(self) -> dict[str, Any]:
        """Irrigation advice: the stored ML result and the rule-based baseline.

        Both are reported separately and labelled, so a rule-based fallback can
        never be mistaken for a model output.
        """
        ml_row = self._latest_prediction("irrigation")
        ml_data: Optional[dict[str, Any]] = None
        if ml_row:
            output = ml_row.get("output") or {}
            ml_data = {
                "prediction": output.get("prediction"),
                "label": output.get("label"),
                "source": ml_row.get("source"),
                "as_of": ml_row.get("created_at"),
            }

        rule = None
        for action in self._plan().get("actions") or []:
            if action.get("category") == "irrigation":
                rule = {
                    "action": action.get("action"),
                    "reason": action.get("reason"),
                    "priority": action.get("priority"),
                    "supporting_data": action.get("supporting_data"),
                    "assumptions": action.get("assumptions"),
                }
                break

        if not ml_data and not rule:
            return _result(
                "get_irrigation_prediction",
                False,
                note=(
                    "No irrigation advice is available: there is no stored "
                    "irrigation prediction and no soil-moisture reading to base "
                    "one on."
                ),
            )

        as_of = (ml_data or {}).get("as_of") or (
            (self._reading_row() or {}).get("created_at")
        )
        return _result(
            "get_irrigation_prediction",
            True,
            data={"ml_prediction": ml_data, "rule_based_baseline": rule},
            as_of=as_of,
        )

    def get_farm_history(
        self, domain: Optional[str] = None, limit: int = 5
    ) -> dict[str, Any]:
        """Recent saved predictions, newest first (optionally one domain)."""
        if domain is not None:
            if not isinstance(domain, str) or domain.strip().lower() not in _ALIAS_TO_DOMAIN:
                raise ToolArgumentError(
                    f"Unknown domain '{domain}'. Expected one of {PREDICTION_DOMAINS}."
                )
            domain = _ALIAS_TO_DOMAIN[domain.strip().lower()]

        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ToolArgumentError("limit must be an integer.")
        if not 1 <= limit <= _MAX_HISTORY_LIMIT:
            raise ToolArgumentError(f"limit must be between 1 and {_MAX_HISTORY_LIMIT}.")

        rows = [r for r in self._prediction_rows() if domain is None or r.get("domain") == domain]
        if not rows:
            return _result(
                "get_farm_history",
                False,
                note="No saved predictions match this request.",
            )

        items = [
            {
                "domain": row.get("domain"),
                "prediction": (row.get("output") or {}).get("prediction"),
                "label": (row.get("output") or {}).get("label"),
                "source": row.get("source"),
                "created_at": row.get("created_at"),
            }
            for row in rows[:limit]
        ]
        return _result(
            "get_farm_history",
            True,
            data={"count": len(items), "items": items},
            as_of=items[0].get("created_at"),
        )

    def get_available_farm_recommendations(self) -> dict[str, Any]:
        """Actionable items the farm's own data currently supports."""
        plan = self._plan()
        actions = plan.get("actions") or []
        if not actions:
            return _result(
                "get_available_farm_recommendations",
                False,
                note=plan.get("summary") or "No recommendations can be derived from the current data.",
            )

        items = [
            {
                "category": action.get("category"),
                "action": action.get("action"),
                "reason": action.get("reason"),
                "priority": action.get("priority"),
                "supporting_data": action.get("supporting_data"),
                "assumptions": action.get("assumptions"),
            }
            for action in actions[:_MAX_RECOMMENDATIONS]
        ]
        return _result(
            "get_available_farm_recommendations",
            True,
            data={
                "summary": plan.get("summary"),
                "action_count": plan.get("action_count"),
                "actions": items,
            },
            as_of=plan.get("generated_at"),
        )

    def get_drought_context(self) -> dict[str, Any]:
        """The most recent saved drought assessment for this account.

        Only the top-level summary is returned — severity category, reason,
        location, crop, growth stage, and the first recommendation category
        that carried actionable items.  The full nested recommendation tree
        is omitted: it is too large for the context window and would require
        the LLM to paraphrase ICAR-attributed text, which is not its role.

        Returns ``available: False`` when no assessment has been saved yet.
        """
        row = self._latest_assessment()
        if not row:
            return _result(
                "get_drought_context",
                False,
                note=(
                    "No drought assessment has been saved for this account. "
                    "Use the Drought Management tool to run one."
                ),
            )

        result_payload = row.get("result") or {}
        # Pull the top-level summary fields only.
        data: dict[str, Any] = {
            "drought_severity": result_payload.get("drought_severity"),
            "drought_severity_reason": result_payload.get("drought_severity_reason"),
            "location": row.get("location") or result_payload.get("location"),
            "crop": row.get("crop") or result_payload.get("crop"),
            "growth_stage": result_payload.get("growth_stage"),
            "water_availability": (row.get("input") or {}).get("water_availability"),
            "irrigation_type": (row.get("input") or {}).get("irrigation_type"),
        }
        # Surface at most the first category of recommendations so the LLM has
        # enough to answer "what should I do about drought?" without the full
        # payload.
        categories = result_payload.get("categories") or []
        if categories:
            first = categories[0]
            data["top_category"] = first.get("category_label")
            data["top_category_urgency"] = first.get("urgency")
            top_items = [
                item.get("action") for item in (first.get("items") or [])[:3]
                if item.get("action")
            ]
            if top_items:
                data["top_recommendations"] = top_items
        # Weather snapshot from the time the assessment was run.
        weather_snap = row.get("weather_snapshot") or result_payload.get("weather") or {}
        if weather_snap.get("fetched"):
            data["weather_at_assessment"] = {
                k: weather_snap.get(k)
                for k in ("current_temp_c", "historical_rain_mm", "forecast_rain_7d_mm")
                if weather_snap.get(k) is not None
            }

        # Remove None values so the LLM context is compact.
        data = {k: v for k, v in data.items() if v is not None}
        return _result(
            "get_drought_context",
            True,
            data=data,
            as_of=row.get("created_at"),
        )

    def get_organic_guidance(self) -> dict[str, Any]:
        """The most recent saved organic farming comparison or transition plan.

        Returns the recommended farming method, the farmer's stated preference,
        the crop, and the top two organic alternatives identified for that crop.
        The full per-method comparison table and the transition phases are
        omitted for the same reason as in ``get_drought_context``.

        Returns ``available: False`` when no plan has been saved yet.
        """
        row: Optional[dict] = None
        try:
            rows, _ = db.list_farming_plans(
                self._client, self._owner_id, limit=1, offset=0
            )
            row = rows[0] if rows else None
        except Exception as exc:  # noqa: BLE001 — optional context
            logger.warning("Could not read farming plans for user %s: %s", self._owner_id, exc)

        if not row:
            return _result(
                "get_organic_guidance",
                False,
                note=(
                    "No organic farming comparison has been saved for this account. "
                    "Use the Organic Farming Advisor to run one."
                ),
            )

        result_payload = row.get("result") or {}
        kind = row.get("kind", "comparison")

        data: dict[str, Any] = {
            "kind": kind,
            "crop": result_payload.get("crop"),
            "preference": result_payload.get("preference") or (row.get("input") or {}).get("preference"),
        }

        # For a comparison, surface the recommended method summary.
        rec = result_payload.get("recommendation") or {}
        if rec.get("summary"):
            data["recommendation_summary"] = rec["summary"]
        if rec.get("next_step"):
            data["next_step"] = rec["next_step"]

        # Up to two organic alternatives.
        alternatives = result_payload.get("organic_alternatives") or []
        if alternatives:
            data["organic_alternatives"] = [
                {
                    "name": alt.get("name"),
                    "category": alt.get("category"),
                    "what_it_does": alt.get("what_it_does"),
                }
                for alt in alternatives[:2]
                if alt.get("name")
            ]

        # For a transition plan, surface the first phase.
        phases = result_payload.get("phases") or []
        if phases and kind == "transition_plan":
            first_phase = phases[0]
            data["first_transition_phase"] = {
                "title": first_phase.get("title"),
                "timeframe": first_phase.get("timeframe"),
                "steps": [s.get("text") for s in (first_phase.get("steps") or [])[:3] if s.get("text")],
            }

        # Warnings / cautions from the result.
        warnings = result_payload.get("warnings") or []
        if warnings:
            data["cautions"] = warnings[:3]

        data = {k: v for k, v in data.items() if v is not None}
        return _result(
            "get_organic_guidance",
            True,
            data=data,
            as_of=row.get("created_at"),
        )

    # ── Derived helpers ─────────────────────────────────────────────────

    def call(self, tool: str, **kwargs: Any) -> dict[str, Any]:
        """Invoke a tool by name; unknown names raise (they are never guessed)."""
        if tool not in TOOL_NAMES:
            raise ToolArgumentError(f"Unknown tool '{tool}'.")
        return getattr(self, tool)(**kwargs)

    def llm_context(self) -> Optional[dict]:
        """The audited farm/sensor facts for the LLM, or ``None`` when unknown.

        Built from the same whitelist every other AI entry point uses, so the
        agent cannot hand the model a field the chat assistant would not.
        """
        return build_farm_context(self._farm_row(), self._reading_row())

    def freshness_index(self) -> dict[str, Any]:
        """Per-source timestamps, for the "last updated" labels in the UI."""
        index: dict[str, Any] = {
            "generated_at": self._now.isoformat(),
            "farm": None,
            "sensors": None,
            "weather": None,
            "predictions": {},
        }
        farm = self._farm_row()
        if farm:
            index["farm"] = farm.get("created_at")
        reading = self._reading_row()
        if reading:
            index["sensors"] = reading.get("observed_at") or reading.get("created_at")
        report = self._weather_raw()
        if report:
            index["weather"] = report.get("fetched_at")
        for row in self._prediction_rows():
            domain = row.get("domain")
            if domain and domain not in index["predictions"]:
                index["predictions"][domain] = row.get("created_at")
        return index
