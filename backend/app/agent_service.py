"""The unified agricultural AI agent engine.

This is the reasoning layer that sits between the farmer's question and the
nine tools in :mod:`app.agent_tools`. It has four jobs:

1. **Route** — decide which tools the question actually needs, with the same
   weighted keyword matching the voice engine already uses
   (``app/voice_engine.classify_intent``). No LLM decides tool use, so a
   question can never make the agent read data it does not need, and a model
   can never widen its own access.
2. **Analyse** — turn the tool results into findings: what the farm/sensor/
   weather/model data says, where two sources disagree, what is missing and
   what is uncertain. Every statement is derived from a value a tool actually
   returned; nothing is estimated.
3. **Compose** — a short, farmer-friendly answer in the Situation /
   Observation / Recommendation / Reason / Warning shape. Sections are only
   emitted when there is something real to say.
4. **Explain (optional)** — when the existing RAG assistant is available it is
   handed *only* the values the tools returned, so it can add a grounded
   natural-language explanation in the farmer's language. The structured
   answer is always produced first and is never blocked or replaced by a
   failed explanation.

Hard rules
----------
* The LLM never calls tools and never touches the database. Only this module
  (deterministically) invokes :class:`~app.agent_tools.FarmTools`.
* Actual sensor readings are labelled as readings and ML results as model
  output; the two are never merged into one statement.
* A model result is described as a prediction, never as a guaranteed outcome.
* Missing data is reported as missing. No default, average or placeholder is
  ever substituted for it.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.agent_tools import TOOL_NAMES, FarmTools, ToolArgumentError
from app.ai_context import FARM_FIELDS, READING_FIELDS
from app.cache import TTLCache
from app.config import get_settings
# The crop moisture thresholds are *data*, not logic: reusing the same table
# keeps the agent's conflict check consistent with the decision engine instead
# of maintaining a second copy that could drift.
from app.decision_engine import _CROP_MOISTURE_THRESHOLDS as CROP_MOISTURE_THRESHOLDS
from app.rag_service import RagUnavailableError

logger = logging.getLogger("farmiq.agent")

# Freshness verdicts used by the aggregator (kept in step with
# app/farm_context_manager.py).
_FRESH = "fresh"
_STALE = "stale"
_OFFLINE = "offline"

# Weather (regional grid) vs in-field sensor. These gaps are large enough that
# they cannot be explained by microclimate alone, so the agent says the two
# sources disagree instead of silently picking one.
_TEMP_DIVERGENCE_C = 5.0
_HUMIDITY_DIVERGENCE_PP = 20.0

# A soil_moisture value above this is not a percentage (the irrigation model
# uses a 0–2000 raw scale), so it cannot be compared with percentage
# thresholds — the agent says so rather than guessing the unit.
_MAX_MOISTURE_PCT = 100.0


# ─────────────────────────────────────────────────────────────────────────
# Routing (deterministic)
# ─────────────────────────────────────────────────────────────────────────

# Tie-break order: specific intents first so a compound question such as
# "what fertilizer should I use on my wheat?" is not swallowed by the broad
# farm-status intent.
_AGENT_INTENTS: tuple[str, ...] = (
    "irrigation",
    "fertilizer",
    "crop_selection",
    "yield",
    "weather",
    "sensors",
    "history",
    "profile",
    "organic_farming",
    "drought_management",
    "farm_status",
)

# The tools each intent is allowed to call. Deliberately narrow: a weather
# question must not also read the sensor history, and a fertilizer question
# must not trigger the full daily plan.
#
# Irrigation and fertilizer include the farm profile because both are
# crop-specific: the profile supplies the crop (the moisture threshold and the
# advice differ per crop) and the Situation line. It is one farm row, not a
# history read.
_INTENT_TOOLS: dict[str, tuple[str, ...]] = {
    "irrigation": (
        "get_irrigation_prediction",
        "get_farm_profile",
        "get_sensor_readings",
        "get_weather_information",
    ),
    "fertilizer": (
        "get_fertilizer_prediction",
        "get_farm_profile",
        "get_sensor_readings",
    ),
    "crop_selection": (
        "get_crop_prediction",
        "get_farm_profile",
    ),
    "yield": (
        "get_yield_prediction",
        "get_farm_profile",
    ),
    "weather": ("get_weather_information",),
    "sensors": ("get_sensor_readings",),
    "history": ("get_farm_history",),
    "profile": ("get_farm_profile",),
    "farm_status": (
        "get_farm_profile",
        "get_sensor_readings",
        "get_weather_information",
        "get_available_farm_recommendations",
    ),
    # Organic farming: need farm profile (crop/soil) + saved guidance if any.
    "organic_farming": (
        "get_farm_profile",
        "get_organic_guidance",
    ),
    # Drought: need saved assessment + live sensor + weather for freshness check.
    "drought_management": (
        "get_drought_context",
        "get_sensor_readings",
        "get_weather_information",
        "get_farm_profile",
    ),
}

_INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "irrigation": (
        "irrigat", "should i water", "water my", "water the", "when to water",
        "needs water", "watering", "drip", "sprinkler",
        "पाणी द्यावे", "पाणी देणे", "शेताला पाणी", "सिंचन", "ड्रिप", "पाण्याची गरज",
    ),
    "fertilizer": (
        "fertilizer", "fertiliser", "fertilize", "manure", "nutrient", "npk",
        "urea", "dap", "potash",
        "खत", "खते", "पोषक", "खत द्यावे", "खत शिफारस",
    ),
    "crop_selection": (
        "which crop", "what crop", "what to plant", "suggest crop", "best crop",
        "crop recommendation", "suitable crop", "sowing", "seed",
        "पीक शिफारस", "कोणते पीक", "पीक निवड", "पेरणी", "योग्य पीक", "बियाणे",
    ),
    "yield": (
        "yield", "harvest", "production", "how much produce",
        "tonnes per hectare",
        "उत्पादन", "उत्पन्न", "किती टन", "कापणी",
    ),
    "weather": (
        "weather", "forecast", "rain", "rainfall", "will it rain",
        "हवामान", "पाऊस", "पावसाळा",
    ),
    "sensors": (
        "sensor", "soil moisture", "moisture level", "reading", "live data",
        "field data",
        "सेन्सर", "माती ओलावा", "ओलावा किती", "आर्द्रता किती", "वाचन",
    ),
    "history": (
        "history", "previous", "earlier", "last time", "past", "records",
        "इतिहास", "आधी", "मागील", "पूर्वी",
    ),
    "profile": (
        "farm details", "farm profile", "land area", "soil type",
        "irrigation type", "which crop am i", "my location", "farm size",
        "शेत माहिती", "मातीचा प्रकार", "माझे शेत",
    ),
    "organic_farming": (
        "organic", "organic farming", "organic method", "compost", "vermicompost",
        "green manure", "biofertilizer", "ipm", "integrated pest", "mulch",
        "crop rotation", "intercrop", "natural farming", "without chemicals",
        "reduce fertilizer", "reduce pesticide", "transition to organic",
        "सेंद्रिय", "सेंद्रिय शेती", "कंपोस्ट", "गांडूळ खत", "हिरवळीचे खत",
        "जैव खत", "एकात्मिक किड", "पीक रोटेशन", "नैसर्गिक शेती",
    ),
    "drought_management": (
        "drought", "water stress", "dry spell", "water shortage", "no rain",
        "low rainfall", "water scarcity", "less water", "save water",
        "dry season", "deficit", "drought risk", "drought management",
        "दुष्काळ", "पाणीटंचाई", "पाण्याची कमतरता", "पाऊस नाही",
        "कमी पाऊस", "पाणी वाचवा", "दुष्काळाचा धोका",
    ),
    "farm_status": (
        "what should i do", "what do i do", "need attention", "today", "status",
        "my farm", "farm plan", "advice", "recommend", "suggestion", "priority",
        "काय करावे", "काय करू", "शेत कसे", "आज", "सल्ला", "शिफारस", "लक्ष",
    ),
}

# Label shown for each intent in the response (and used by tests).
_INTENT_LABELS: dict[str, dict[str, str]] = {
    "irrigation": {"en": "irrigation", "mr": "सिंचन"},
    "fertilizer": {"en": "fertilizer", "mr": "खत"},
    "crop_selection": {"en": "crop choice", "mr": "पीक निवड"},
    "yield": {"en": "yield", "mr": "उत्पादन"},
    "weather": {"en": "weather", "mr": "हवामान"},
    "sensors": {"en": "sensor readings", "mr": "सेन्सर वाचन"},
    "history": {"en": "prediction history", "mr": "अंदाज इतिहास"},
    "profile": {"en": "farm profile", "mr": "शेत माहिती"},
    "farm_status": {"en": "farm plan", "mr": "शेत योजना"},
    "organic_farming": {"en": "organic farming", "mr": "सेंद्रिय शेती"},
    "drought_management": {"en": "drought management", "mr": "दुष्काळ व्यवस्थापन"},
    "unknown": {"en": "general", "mr": "सामान्य"},
}


def classify_intent(question: str) -> str:
    """Weighted keyword match, longest phrase wins. ``"unknown"`` when nothing matches."""
    low = (question or "").lower()
    scores: dict[str, float] = {intent: 0.0 for intent in _AGENT_INTENTS}
    for intent, keywords in _INTENT_KEYWORDS.items():
        for keyword in keywords:
            if keyword.lower() in low:
                # Length weighting, exactly as app/voice_engine.classify_intent
                # does, so "soil moisture" outranks "soil".
                scores[intent] += 1.0 + len(keyword.split()) * 0.5

    best_intent, best_score = "unknown", 0.0
    for intent in _AGENT_INTENTS:  # fixed order → deterministic tie-break
        if scores[intent] > best_score:
            best_intent, best_score = intent, scores[intent]
    return best_intent


def tools_for_intent(intent: str) -> tuple[str, ...]:
    """The tools an intent may call (empty for ``"unknown"``)."""
    return _INTENT_TOOLS.get(intent, ())


# ─────────────────────────────────────────────────────────────────────────
# Bilingual text
# ─────────────────────────────────────────────────────────────────────────

_LABELS: dict[str, dict[str, str]] = {
    "situation": {"en": "Situation", "mr": "परिस्थिती"},
    "observation": {"en": "Observation", "mr": "निरीक्षण"},
    "recommendation": {"en": "Recommendation", "mr": "शिफारस"},
    "reason": {"en": "Reason", "mr": "कारण"},
    "warning": {"en": "Warning", "mr": "सावधानता"},
}

_CHANNEL_LABELS: dict[str, dict[str, Any]] = {
    "soil_moisture": {"en": "Soil moisture", "mr": "माती ओलावा", "unit": "%"},
    "soil_temperature": {"en": "Soil temperature", "mr": "मातीचे तापमान", "unit": "°C"},
    "temperature": {"en": "Air temperature", "mr": "हवेचे तापमान", "unit": "°C"},
    "humidity": {"en": "Humidity", "mr": "आर्द्रता", "unit": "%"},
    "nitrogen": {"en": "Nitrogen (N)", "mr": "नायट्रोजन (N)", "unit": ""},
    "phosphorous": {"en": "Phosphorous (P)", "mr": "फॉस्फरस (P)", "unit": ""},
    "potassium": {"en": "Potassium (K)", "mr": "पोटॅशियम (K)", "unit": ""},
    "ph": {"en": "Soil pH", "mr": "मातीचा pH", "unit": ""},
    "pressure": {"en": "Air pressure", "mr": "हवेचा दाब", "unit": " hPa"},
}

_DOMAIN_LABELS: dict[str, dict[str, str]] = {
    "crop": {"en": "Crop recommendation", "mr": "पीक शिफारस"},
    "fertilizer": {"en": "Fertilizer recommendation", "mr": "खत शिफारस"},
    "yield": {"en": "Yield prediction", "mr": "उत्पादन अंदाज"},
    "irrigation": {"en": "Irrigation", "mr": "सिंचन"},
}

_TEXT: dict[str, dict[str, str]] = {
    # ── freshness ────────────────────────────────────────────────────
    "age_unknown": {"en": "time unknown", "mr": "वेळ माहीत नाही"},
    "age_just_now": {"en": "just now", "mr": "आत्ताच"},
    "age_hours": {"en": "{hours} h ago", "mr": "{hours} तासांपूर्वी"},
    "age_days": {"en": "{days} days ago", "mr": "{days} दिवसांपूर्वी"},
    # ── situation ────────────────────────────────────────────────────
    "sit_none": {
        "en": "No farm profile is saved yet, so I cannot describe your field.",
        "mr": "तुमची शेत माहिती अद्याप जतन केलेली नाही, त्यामुळे मी शेताचे वर्णन करू शकत नाही.",
    },
    "sit_crop_location": {
        "en": "You are growing {crop} in {location}.",
        "mr": "तुम्ही {location} येथे {crop} पीक घेत आहात.",
    },
    "sit_crop": {"en": "You are growing {crop}.", "mr": "तुम्ही {crop} पीक घेत आहात."},
    "sit_location": {"en": "Your farm is in {location}.", "mr": "तुमचे शेत {location} येथे आहे."},
    "sit_stage": {"en": "Growth stage: {stage}.", "mr": "वाढीचा टप्पा: {stage}."},
    # ── observation ──────────────────────────────────────────────────
    "obs_sensor_prefix": {"en": "Sensor reading ({age})", "mr": "सेन्सर वाचन ({age})"},
    "obs_weather_prefix": {"en": "Weather at {location} ({age})", "mr": "हवामान {location} ({age})"},
    "obs_weather_rain_7d": {"en": "rain next 7 days {value} mm", "mr": "पुढील ७ दिवसांत पाऊस {value} मिमी"},
    "obs_model": {"en": "{label} (model output)", "mr": "{label} (मॉडेल निकाल)"},
    "obs_history": {"en": "{count} saved predictions", "mr": "{count} जतन केलेले अंदाज"},
    "irrigate_yes": {"en": "irrigate", "mr": "पाणी द्या"},
    "irrigate_no": {"en": "no irrigation", "mr": "पाणी नको"},
    "crop_default": {"en": "default", "mr": "सामान्य"},
    # ── recommendations ──────────────────────────────────────────────
    "rec_irrigate_now": {
        "en": "Give water to your crop soon.",
        "mr": "तुमच्या पिकाला लवकर पाणी द्या.",
    },
    "rec_no_irrigation": {
        "en": "No irrigation is needed right now.",
        "mr": "आत्ता पाणी देण्याची गरज नाही.",
    },
    "rec_apply_fertilizer": {"en": "Apply {value} fertilizer.", "mr": "{value} खत द्या."},
    "rec_crop_model": {
        "en": "The crop model recommends {value}.",
        "mr": "पीक मॉडेल {value} ची शिफारस करते.",
    },
    "rec_fertilizer_model": {
        "en": "The fertilizer model recommends {value}.",
        "mr": "खत मॉडेल {value} ची शिफारस करते.",
    },
    "rec_yield_model": {
        "en": "The yield model estimates {value} tonnes per hectare.",
        "mr": "उत्पादन मॉडेल {value} टन/हेक्टर असा अंदाज देतो.",
    },
    "rec_irrigate_model": {
        "en": "The irrigation model recommends irrigating.",
        "mr": "सिंचन मॉडेल पाणी देण्याची शिफारस करते.",
    },
    "rec_no_irrigate_model": {
        "en": "The irrigation model indicates no irrigation is needed now.",
        "mr": "सिंचन मॉडेल आत्ता पाणी देण्याची गरज दर्शवत नाही.",
    },
    # ── reasons ──────────────────────────────────────────────────────
    "reason_model_only": {
        "en": "This is model output computed from the data FarmIQ has for your farm. "
              "It is a prediction, not a guaranteed outcome.",
        "mr": "हा मॉडेलचा निकाल आहे, जो FarmIQ कडे असलेल्या तुमच्या शेताच्या माहितीवर आधारित आहे. "
              "हा अंदाज आहे, हमी नाही.",
    },
    "reason_irrigation_rule": {
        "en": "Based on the current soil-moisture reading compared with this crop's requirement.",
        "mr": "सध्याचे माती ओलावा वाचन आणि या पिकाची गरज यांची तुलना करून.",
    },
    # ── uncertainty / warnings ───────────────────────────────────────
    "warn_stale_sensor": {
        "en": "The last sensor reading is {age}. Field conditions may have changed.",
        "mr": "शेवटचे सेन्सर वाचन {age} चे आहे. शेतातील परिस्थिती बदलली असू शकते.",
    },
    "warn_no_sensor": {
        "en": "No sensor readings have been received, so soil conditions are unknown.",
        "mr": "कोणतेही सेन्सर वाचन मिळालेले नाही, त्यामुळे मातीची स्थिती माहीत नाही.",
    },
    "warn_invalid_channels": {
        "en": "These readings are outside plausible sensor limits: {channels}.",
        "mr": "ही वाचने शक्य मर्यादेबाहेर आहेत: {channels}.",
    },
    "warn_demo": {
        "en": "This reading is simulated (DEMO), not from real hardware.",
        "mr": "हे वाचन कृत्रिम (DEMO) आहे, खऱ्या उपकरणाचे नाही.",
    },
    "warn_no_weather": {
        "en": "Weather data is not available right now, so rainfall is unknown.",
        "mr": "हवामान माहिती सध्या उपलब्ध नाही, त्यामुळे पावसाची माहिती माहीत नाही.",
    },
    "warn_insufficient": {
        "en": "There is not enough farm data to answer this yet.",
        "mr": "या प्रश्नाचे उत्तर देण्यासाठी पुरेशी शेत माहिती अद्याप नाही.",
    },
    "warn_insufficient_fields": {
        "en": "There is not enough farm data to answer this yet. Missing: {fields}.",
        "mr": "या प्रश्नाचे उत्तर देण्यासाठी पुरेशी शेत माहिती नाही. अनुपलब्ध: {fields}.",
    },
    "warn_irrigation_conflict": {
        "en": "The irrigation model and your current soil-moisture reading disagree "
              "(model: {ml}, reading: {moisture}%, {crop} threshold: {threshold}%). "
              "Check the sensor before irrigating.",
        "mr": "सिंचन मॉडेल आणि सध्याचे माती ओलावा वाचन यांच्यात फरक आहे "
              "(मॉडेल: {ml}, वाचन: {moisture}%, {crop} मर्यादा: {threshold}%). "
              "पाणी देण्यापूर्वी सेन्सर तपासा.",
    },
    "warn_ml_before_reading": {
        "en": "The {domain} result is older than your latest sensor reading, "
              "so it may not reflect current field conditions.",
        "mr": "{domain} निकाल तुमच्या शेवटच्या सेन्सर वाचनापेक्षा जुना आहे, "
              "त्यामुळे तो सध्याची स्थिती दर्शवत नसेल.",
    },
    "warn_source_divergence": {
        "en": "Your field sensor and the regional weather feed disagree on {channel} "
              "(sensor: {sensor}, weather: {weather}). Treat the sensor as the field value.",
        "mr": "तुमचा शेत सेन्सर आणि प्रादेशिक हवामान सेवा {channel} बाबत वेगळे सांगतात "
              "(सेन्सर: {sensor}, हवामान: {weather}). शेतासाठी सेन्सरचे मूल्य धरा.",
    },
    # ── unrelated / unavailable ──────────────────────────────────────
    "no_farm_intent": {
        "en": "I can help with your farm plan, irrigation, fertilizer, crop choice, "
              "yield, soil sensors, weather, organic farming, and drought management. "
              "Ask me about any of those.",
        "mr": "मी शेत योजना, सिंचन, खत, पीक निवड, उत्पादन, सेन्सर, हवामान, "
              "सेंद्रिय शेती आणि दुष्काळ व्यवस्थापन यांत मदत करू शकतो. "
              "यापैकी काहीही विचारा.",
    },
    # ── drought observations ─────────────────────────────────────────
    "obs_drought_prefix": {
        "en": "Drought assessment (saved {age})",
        "mr": "दुष्काळ मूल्यांकन ({age} पूर्वी जतन केले)",
    },
    "obs_drought_severity": {
        "en": "Risk level: {severity}",
        "mr": "धोका पातळी: {severity}",
    },
    "obs_drought_no_data": {
        "en": "No drought assessment has been saved yet. Run one in Drought Management.",
        "mr": "अद्याप कोणतेही दुष्काळ मूल्यांकन जतन केलेले नाही. दुष्काळ व्यवस्थापन वापरा.",
    },
    # ── organic farming observations ─────────────────────────────────
    "obs_organic_prefix": {
        "en": "Organic farming guidance (saved {age})",
        "mr": "सेंद्रिय शेती मार्गदर्शन ({age} पूर्वी जतन केले)",
    },
    "obs_organic_no_data": {
        "en": "No organic farming comparison has been saved yet. Use the Organic Farming Advisor.",
        "mr": "अद्याप कोणतीही सेंद्रिय शेती तुलना जतन केलेली नाही. सेंद्रिय शेती सल्लागार वापरा.",
    },
    # ── drought recommendations ──────────────────────────────────────
    "rec_drought_action": {
        "en": "Drought guidance: {action}",
        "mr": "दुष्काळ मार्गदर्शन: {action}",
    },
    "rec_drought_monitor": {
        "en": "Monitor soil moisture and check crop stress symptoms regularly.",
        "mr": "माती ओलावा तपासा आणि पीक ताण लक्षणे नियमितपणे पाहा.",
    },
    # ── organic recommendations ──────────────────────────────────────
    "rec_organic_summary": {
        "en": "Organic guidance: {summary}",
        "mr": "सेंद्रिय मार्गदर्शन: {summary}",
    },
    "rec_organic_alternative": {
        "en": "Consider: {name} — {what}",
        "mr": "विचार करा: {name} — {what}",
    },
}


def _t(lang: str, key: str, **kwargs: Any) -> str:
    entry = _TEXT.get(key, {})
    template = entry.get(lang) or entry.get("en") or key
    try:
        return template.format(**kwargs)
    except (KeyError, ValueError):
        return template


def _label(lang: str, key: str) -> str:
    return _LABELS.get(key, {}).get(lang) or key


def _age_label(lang: str, hours: Optional[float]) -> str:
    if hours is None:
        return _t(lang, "age_unknown")
    if hours < 1:
        return _t(lang, "age_just_now")
    if hours < 24:
        return _t(lang, "age_hours", hours=f"{hours:.1f}")
    return _t(lang, "age_days", days=f"{hours / 24:.1f}")


def _display(value: Any) -> str:
    """Render a tool value for a farmer. Never adds information."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)[:200]
    return str(value)


# ─────────────────────────────────────────────────────────────────────────
# Evidence gathering
# ─────────────────────────────────────────────────────────────────────────

def _unavailable(tool: str, note: str) -> dict[str, Any]:
    return {"tool": tool, "available": False, "data": None, "as_of": None, "note": note}


def gather(
    tools: tuple[str, ...],
    *,
    client: Any,
    owner_id: str,
    farm_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Run the selected tools and collect their results.

    A tool that fails yields ``available: False`` with the reason; it never
    raises into the request, because the agent must still answer with whatever
    else is available.
    """
    bundle = FarmTools(client, owner_id, farm_id=farm_id, now=now)
    results: dict[str, dict[str, Any]] = {}
    for name in tools:
        if name not in TOOL_NAMES:
            results[name] = _unavailable(name, "Unknown tool.")
            continue
        try:
            results[name] = bundle.call(name)
        except ToolArgumentError as exc:
            logger.warning("Agent tool %s rejected its arguments: %s", name, exc)
            results[name] = _unavailable(name, str(exc))
        except Exception as exc:  # noqa: BLE001 — one failing tool must not fail the answer
            logger.exception("Agent tool %s failed", name)
            results[name] = _unavailable(name, f"{type(exc).__name__}: {exc}")

    return {"bundle": bundle, "results": results}


def _data(results: dict[str, dict], tool: str) -> Optional[Any]:
    """The payload of a tool result, or ``None`` when it was unavailable."""
    entry = results.get(tool) or {}
    return entry.get("data") if entry.get("available") else None


def _tool_as_of(results: dict[str, dict], tool: str) -> Optional[str]:
    return (results.get(tool) or {}).get("as_of")


# ─────────────────────────────────────────────────────────────────────────
# Analysis — findings, conflicts, uncertainty
# ─────────────────────────────────────────────────────────────────────────

def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _moisture_conflict(
    lang: str, farm: dict, sensors: Optional[dict], irrigation: Optional[dict]
) -> Optional[dict]:
    """ML irrigation vs the live soil-moisture reading.

    The irrigation model returns a class (irrigate / do not irrigate) on the
    dataset's raw 0–2000 scale, so it cannot be compared numerically with the
    percentage reading. The two are therefore compared as decisions, against
    the same crop threshold the decision engine uses.
    """
    if not sensors or not irrigation:
        return None
    ml = (irrigation.get("ml_prediction") or {}).get("prediction")
    moisture = sensors.get("soil_moisture")
    if ml is None or not isinstance(moisture, (int, float)):
        return None
    if not 0 <= float(moisture) <= _MAX_MOISTURE_PCT:
        return None  # not a percentage → comparison would be meaningless

    crop = str(farm.get("current_crop") or "").strip()
    thresholds = CROP_MOISTURE_THRESHOLDS.get(crop, CROP_MOISTURE_THRESHOLDS["_default"])
    rule_says_irrigate = float(moisture) < thresholds["irrigate_below"]
    ml_says_irrigate = int(ml) == 1
    if ml_says_irrigate == rule_says_irrigate:
        return None

    return {
        "kind": "ml_vs_sensor",
        "message": _t(
            lang,
            "warn_irrigation_conflict",
            ml=_t(lang, "irrigate_yes" if ml_says_irrigate else "irrigate_no"),
            moisture=f"{float(moisture):.0f}",
            crop=crop or _t(lang, "crop_default"),
            threshold=f"{thresholds['irrigate_below']:g}",
        ),
        "evidence": {
            "ml_prediction": int(ml),
            "soil_moisture": float(moisture),
            "threshold_pct": thresholds["irrigate_below"],
            "crop": crop or None,
        },
    }


def _source_divergences(sensors: Optional[dict], weather: Optional[dict]) -> list[dict]:
    """In-field sensor vs regional weather feed, where the gap is too large."""
    if not sensors or not weather:
        return []
    found: list[dict] = []
    pairs = (
        ("temperature", weather.get("temperature_c"), _TEMP_DIVERGENCE_C),
        ("humidity", weather.get("humidity_pct"), _HUMIDITY_DIVERGENCE_PP),
    )
    for channel, weather_value, tolerance in pairs:
        sensor_value = sensors.get(channel)
        if not isinstance(sensor_value, (int, float)) or not isinstance(weather_value, (int, float)):
            continue
        if abs(float(sensor_value) - float(weather_value)) <= tolerance:
            continue
        found.append(
            {
                "kind": "sensor_vs_weather",
                "channel": channel,
                "sensor_value": float(sensor_value),
                "weather_value": float(weather_value),
            }
        )
    return found


def _prediction_age_conflicts(results: dict[str, dict]) -> list[dict]:
    """Predictions computed before the newest sensor reading."""
    reading_at = _parse_ts((_data(results, "get_sensor_readings") or {}).get("observed_at"))
    if reading_at is None:
        return []
    found: list[dict] = []
    for tool in (
        "get_crop_prediction",
        "get_fertilizer_prediction",
        "get_yield_prediction",
        "get_irrigation_prediction",
    ):
        at = _parse_ts(_tool_as_of(results, tool))
        if at is not None and at < reading_at:
            found.append({"kind": "prediction_before_reading", "tool": tool})
    return found


def analyse(results: dict[str, dict], lang: str) -> dict[str, Any]:
    """Derive findings, conflicts, uncertainty and missing data from the results.

    ``missing`` and the data-gap warnings only cover sources the question
    actually needed: a question the agent did not route to the sensor tool must
    not be told "no sensor readings", because nothing was looked up.
    """
    requested = set(results)
    farm = _data(results, "get_farm_profile") or {}
    sensors = _data(results, "get_sensor_readings")
    weather = _data(results, "get_weather_information")
    irrigation = _data(results, "get_irrigation_prediction")

    conflicts: list[dict[str, Any]] = []
    uncertainty: list[str] = []
    missing: list[str] = []
    safety: list[str] = []

    # ── farm profile ─────────────────────────────────────────────────────
    if "get_farm_profile" in requested and not farm:
        missing.append("farm_profile")

    # ── sensors ──────────────────────────────────────────────────────────
    if "get_sensor_readings" in requested:
        if not sensors:
            missing.append("sensor_readings")
            safety.append(_t(lang, "warn_no_sensor"))
        else:
            freshness = sensors.get("freshness")
            age = sensors.get("age_hours")
            if freshness in (_STALE, _OFFLINE):
                note = _t(lang, "warn_stale_sensor", age=_age_label(lang, age))
                uncertainty.append(note)
                safety.append(note)
            invalid = sensors.get("invalid_channels") or []
            if invalid:
                note = _t(lang, "warn_invalid_channels", channels=", ".join(invalid))
                uncertainty.append(note)
                safety.append(note)
            if sensors.get("is_demo"):
                safety.append(_t(lang, "warn_demo"))
            for channel in sensors.get("missing_channels") or []:
                missing.append(f"sensor:{channel}")

    # ── weather ──────────────────────────────────────────────────────────
    if "get_weather_information" in requested and not weather:
        missing.append("weather")
        safety.append(_t(lang, "warn_no_weather"))

    # ── conflicts ────────────────────────────────────────────────────────
    moisture_conflict = _moisture_conflict(lang, farm, sensors, irrigation)
    if moisture_conflict:
        conflicts.append(moisture_conflict)

    for divergence in _source_divergences(sensors, weather):
        target = "mr" if lang == "mr" else "en"
        channel_label = _CHANNEL_LABELS[divergence["channel"]][target]
        sensor_text = f"{divergence['sensor_value']:g}{_CHANNEL_LABELS[divergence['channel']]['unit']}"
        weather_text = f"{divergence['weather_value']:g}{_CHANNEL_LABELS[divergence['channel']]['unit']}"
        divergence["message"] = _t(
            lang,
            "warn_source_divergence",
            channel=channel_label,
            sensor=sensor_text,
            weather=weather_text,
        )
        conflicts.append(divergence)

    for stale in _prediction_age_conflicts(results):
        target = "mr" if lang == "mr" else "en"
        conflict = {
            "kind": stale["kind"],
            "tool": stale["tool"],
            "message": _t(
                lang, "warn_ml_before_reading",
                domain=_DOMAIN_LABELS[_domain_of_tool(stale["tool"])][target],
            ),
        }
        conflicts.append(conflict)
        uncertainty.append(conflict["message"])

    # Irrigation falling back to the rule (not a model) is a caveat, not an error.
    if irrigation and not (irrigation.get("ml_prediction") or {}).get("prediction"):
        if irrigation.get("rule_based_baseline"):
            uncertainty.append(
                _t(lang, "reason_irrigation_rule")
            )

    for conflict in conflicts:
        if conflict.get("message"):
            safety.append(conflict["message"])

    return {
        "farm": farm,
        "sensors": sensors,
        "weather": weather,
        "conflicts": conflicts,
        "uncertainty": uncertainty,
        "missing": missing,
        "safety": safety,
    }


def _domain_of_tool(tool: str) -> str:
    return {
        "get_crop_prediction": "crop",
        "get_fertilizer_prediction": "fertilizer",
        "get_yield_prediction": "yield",
        "get_irrigation_prediction": "irrigation",
    }.get(tool, "irrigation")


# ─────────────────────────────────────────────────────────────────────────
# Composition
# ─────────────────────────────────────────────────────────────────────────

def _situation(lang: str, farm: dict) -> Optional[str]:
    if not farm:
        return None
    crop = farm.get("current_crop")
    location = farm.get("location")
    if crop and location:
        base = _t(lang, "sit_crop_location", crop=crop, location=location)
    elif crop:
        base = _t(lang, "sit_crop", crop=crop)
    elif location:
        base = _t(lang, "sit_location", location=location)
    else:
        return None

    stage = farm.get("growth_stage")
    if stage:
        base = f"{base} {_t(lang, 'sit_stage', stage=stage)}"
    return base


def _sensor_observation(lang: str, sensors: dict) -> str:
    target = "mr" if lang == "mr" else "en"
    parts = []
    for channel in READING_FIELDS:
        value = sensors.get(channel)
        if value in (None, ""):
            continue
        label = _CHANNEL_LABELS[channel][target]
        parts.append(f"{label} {_display(value)}{_CHANNEL_LABELS[channel]['unit']}")
    prefix = _t(lang, "obs_sensor_prefix", age=_age_label(lang, sensors.get("age_hours")))
    return f"{prefix}: " + "; ".join(parts)


def _weather_observation(lang: str, weather: dict) -> str:
    target = "mr" if lang == "mr" else "en"
    parts = []
    if weather.get("temperature_c") is not None:
        parts.append(f"{_CHANNEL_LABELS['temperature'][target]} {_display(weather['temperature_c'])}°C")
    if weather.get("humidity_pct") is not None:
        parts.append(f"{_CHANNEL_LABELS['humidity'][target]} {_display(weather['humidity_pct'])}%")
    if weather.get("forecast_rain_7d_mm") is not None:
        parts.append(_t(lang, "obs_weather_rain_7d", value=_display(weather["forecast_rain_7d_mm"])))
    prefix = _t(
        lang,
        "obs_weather_prefix",
        location=weather.get("location") or "—",
        age=_age_label(lang, weather.get("age_hours")),
    )
    return f"{prefix}: " + "; ".join(parts) if parts else prefix


def _model_observation(lang: str, domain: str, entry: dict) -> str:
    target = "mr" if lang == "mr" else "en"
    label = _DOMAIN_LABELS[domain][target]
    value = entry.get("label") or entry.get("prediction")
    return _t(lang, "obs_model", label=label) + f": {_display(value)}"


def _observations(lang: str, results: dict[str, dict]) -> list[str]:
    observations: list[str] = []

    sensors = _data(results, "get_sensor_readings")
    if sensors:
        observations.append(_sensor_observation(lang, sensors))

    weather = _data(results, "get_weather_information")
    if weather:
        observations.append(_weather_observation(lang, weather))

    for domain, tool in (
        ("crop", "get_crop_prediction"),
        ("fertilizer", "get_fertilizer_prediction"),
        ("yield", "get_yield_prediction"),
    ):
        entry = _data(results, tool)
        if entry and entry.get("prediction") is not None:
            observations.append(_model_observation(lang, domain, entry))

    irrigation = _data(results, "get_irrigation_prediction")
    if irrigation:
        ml = (irrigation.get("ml_prediction") or {})
        if ml.get("prediction") is not None:
            observations.append(_model_observation(lang, "irrigation", ml))

    history = _data(results, "get_farm_history")
    if history and history.get("count"):
        observations.append(_t(lang, "obs_history", count=history["count"]))

    # ── drought context ───────────────────────────────────────────────
    if "get_drought_context" in results:
        drought = _data(results, "get_drought_context")
        if drought:
            age_h = None
            as_of = (results.get("get_drought_context") or {}).get("as_of")
            if as_of:
                try:
                    from datetime import datetime, timezone as tz
                    parsed = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
                    now_utc = datetime.now(tz.utc)
                    age_h = round((now_utc - parsed).total_seconds() / 3600, 1)
                except Exception:
                    pass
            prefix = _t(lang, "obs_drought_prefix", age=_age_label(lang, age_h))
            severity = drought.get("drought_severity")
            if severity:
                observations.append(f"{prefix} — {_t(lang, 'obs_drought_severity', severity=severity)}")
            else:
                observations.append(prefix)
        else:
            observations.append(_t(lang, "obs_drought_no_data"))

    # ── organic guidance ──────────────────────────────────────────────
    if "get_organic_guidance" in results:
        organic = _data(results, "get_organic_guidance")
        if organic:
            age_h = None
            as_of = (results.get("get_organic_guidance") or {}).get("as_of")
            if as_of:
                try:
                    from datetime import datetime, timezone as tz
                    parsed = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
                    now_utc = datetime.now(tz.utc)
                    age_h = round((now_utc - parsed).total_seconds() / 3600, 1)
                except Exception:
                    pass
            prefix = _t(lang, "obs_organic_prefix", age=_age_label(lang, age_h))
            crop = organic.get("crop")
            if crop:
                observations.append(f"{prefix} ({crop})")
            else:
                observations.append(prefix)
        else:
            observations.append(_t(lang, "obs_organic_no_data"))

    return observations


def _action_text(lang: str, action: dict) -> str:
    category = action.get("category")
    if category == "irrigation":
        irrigate = action.get("priority") in ("critical", "high")
        return _t(lang, "rec_irrigate_now" if irrigate else "rec_no_irrigation")
    if category == "fertilizer":
        value = (action.get("supporting_data") or {}).get("recommended_fertilizer")
        if value:
            return _t(lang, "rec_apply_fertilizer", value=_display(value))
    # Soil/weather actions carry a specific, evidence-based sentence from the
    # decision engine; it is passed through unchanged rather than paraphrased.
    return str(action.get("action") or "").strip()


def _recommendations(lang: str, intent: str, results: dict[str, dict]) -> tuple[list[str], list[str]]:
    recommendations: list[str] = []
    reasons: list[str] = []

    plan = _data(results, "get_available_farm_recommendations")
    actions = [
        action
        for action in ((plan or {}).get("actions") or [])
        if action.get("category") != "data_quality"
    ]
    for action in actions[:3]:
        text = _action_text(lang, action)
        if text:
            recommendations.append(text)
        if action.get("reason"):
            reasons.append(action["reason"])

    if not actions:
        if intent == "crop_selection":
            entry = _data(results, "get_crop_prediction")
            if entry and entry.get("prediction") is not None:
                recommendations.append(_t(lang, "rec_crop_model", value=_display(entry.get("prediction"))))
                reasons.append(_t(lang, "reason_model_only"))
        elif intent == "yield":
            entry = _data(results, "get_yield_prediction")
            if entry and entry.get("prediction") is not None:
                recommendations.append(_t(lang, "rec_yield_model", value=_display(entry.get("prediction"))))
                reasons.append(_t(lang, "reason_model_only"))
        elif intent == "fertilizer":
            entry = _data(results, "get_fertilizer_prediction")
            if entry and entry.get("prediction") is not None:
                recommendations.append(
                    _t(lang, "rec_fertilizer_model", value=_display(entry.get("prediction")))
                )
                reasons.append(_t(lang, "reason_model_only"))
        elif intent == "irrigation":
            irrigation = _data(results, "get_irrigation_prediction") or {}
            ml = irrigation.get("ml_prediction") or {}
            if ml.get("prediction") is not None:
                key = "rec_irrigate_model" if int(ml["prediction"]) == 1 else "rec_no_irrigate_model"
                recommendations.append(_t(lang, key))
                reasons.append(_t(lang, "reason_model_only"))
            elif irrigation.get("rule_based_baseline"):
                baseline = irrigation["rule_based_baseline"]
                text = _action_text(lang, baseline)
                if text:
                    recommendations.append(text)
                reasons.append(_t(lang, "reason_irrigation_rule"))

    # ── drought recommendations ───────────────────────────────────────
    if intent == "drought_management":
        drought = _data(results, "get_drought_context")
        if drought:
            top_recs = drought.get("top_recommendations") or []
            for action_text in top_recs[:2]:
                recommendations.append(_t(lang, "rec_drought_action", action=action_text))
            if drought.get("drought_severity") in ("moderate", "severe", "extreme"):
                recommendations.append(_t(lang, "rec_drought_monitor"))
            severity_reason = drought.get("drought_severity_reason")
            if severity_reason:
                reasons.append(severity_reason)
        else:
            # No saved assessment — recommend running the tool.
            recommendations.append(_t(lang, "obs_drought_no_data"))

    # ── organic farming recommendations ───────────────────────────────
    if intent == "organic_farming":
        organic = _data(results, "get_organic_guidance")
        if organic:
            summary = organic.get("recommendation_summary")
            if summary:
                recommendations.append(_t(lang, "rec_organic_summary", summary=summary))
            alternatives = organic.get("organic_alternatives") or []
            for alt in alternatives[:2]:
                name = alt.get("name", "")
                what = alt.get("what_it_does", "")
                if name and what:
                    recommendations.append(_t(lang, "rec_organic_alternative", name=name, what=what[:80]))
            next_step = organic.get("next_step")
            if next_step:
                reasons.append(next_step)
        else:
            recommendations.append(_t(lang, "obs_organic_no_data"))

    return recommendations, reasons


def compose(
    intent: str,
    lang: str,
    results: dict[str, dict],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    """Build the structured answer sections from real evidence only."""
    farm = analysis.get("farm") or {}
    situation = _situation(lang, farm)
    if situation is None and not farm and "get_farm_profile" in results:
        # The profile was needed for this question and the account has none.
        situation = _t(lang, "sit_none")

    observation = _observations(lang, results)
    recommendation, reason = _recommendations(lang, intent, results)

    warning: list[str] = []
    for item in analysis.get("safety") or []:
        if item and item not in warning:
            warning.append(item)

    if intent != "unknown" and not observation and not recommendation:
        # The question was understood but the farm has no data to answer it.
        fields = ", ".join(analysis.get("missing") or [])
        warning.append(
            _t(lang, "warn_insufficient_fields", fields=fields)
            if fields
            else _t(lang, "warn_insufficient")
        )

    return {
        "situation": situation,
        "observation": observation,
        "recommendation": recommendation,
        "reason": reason[:3],
        "warning": warning,
    }


def render(sections: dict[str, Any], lang: str) -> str:
    """Render the sections into short, farmer-friendly text. Empty when nothing to say."""
    lines: list[str] = []
    if sections.get("situation"):
        lines.append(f"{_label(lang, 'situation')}: {sections['situation']}")
    if sections.get("observation"):
        lines.append(f"{_label(lang, 'observation')}:")
        lines.extend(f"- {item}" for item in sections["observation"])
    if sections.get("recommendation"):
        lines.append(f"{_label(lang, 'recommendation')}:")
        lines.extend(f"- {item}" for item in sections["recommendation"])
    if sections.get("reason"):
        lines.append(f"{_label(lang, 'reason')}:")
        lines.extend(f"- {item}" for item in sections["reason"])
    if sections.get("warning"):
        lines.append(f"{_label(lang, 'warning')}:")
        lines.extend(f"- {item}" for item in sections["warning"])
    return "\n".join(lines).strip()


def context_block(results: dict[str, dict]) -> dict[str, Any]:
    """The evidence the UI can show alongside the answer (only what was fetched)."""
    predictions: dict[str, Any] = {}
    for domain, tool in (
        ("crop", "get_crop_prediction"),
        ("fertilizer", "get_fertilizer_prediction"),
        ("yield", "get_yield_prediction"),
    ):
        entry = _data(results, tool)
        if entry and entry.get("prediction") is not None:
            predictions[domain] = {
                "prediction": entry.get("prediction"),
                "label": entry.get("label"),
                "source": entry.get("source"),
                "as_of": _tool_as_of(results, tool),
            }
    irrigation = _data(results, "get_irrigation_prediction")
    if irrigation:
        ml = irrigation.get("ml_prediction") or {}
        if ml.get("prediction") is not None:
            predictions["irrigation"] = {**ml, "as_of": ml.get("as_of") or _tool_as_of(results, "get_irrigation_prediction")}

    return {
        "farm": _data(results, "get_farm_profile"),
        "sensors": _data(results, "get_sensor_readings"),
        "weather": _data(results, "get_weather_information"),
        "predictions": predictions,
        "drought": _data(results, "get_drought_context"),
        "organic": _data(results, "get_organic_guidance"),
    }


def llm_context(results: dict[str, dict]) -> Optional[dict]:
    """Flatten the fetched evidence into the audited shape the assistant accepts.

    Uses the same whitelists as :mod:`app.ai_context`, so the agent cannot hand
    the model a field the chat assistant would not — and only sources the tools
    actually read are included.
    """
    context: dict[str, Any] = {}

    farm = _data(results, "get_farm_profile") or {}
    for key in FARM_FIELDS:
        value = farm.get(key)
        if value not in (None, ""):
            context[key] = value

    sensors = _data(results, "get_sensor_readings")
    if sensors:
        for key in READING_FIELDS:
            value = sensors.get(key)
            if value not in (None, ""):
                context[key] = value
        if context:
            context["latest_reading_source"] = "DEMO simulated" if sensors.get("is_demo") else "device"
            if sensors.get("observed_at"):
                context["latest_reading_at"] = sensors["observed_at"]

    weather = _data(results, "get_weather_information")
    if weather:
        for key, source in (
            ("weather_temperature_c", "temperature_c"),
            ("weather_humidity_pct", "humidity_pct"),
            ("weather_forecast_rain_7d_mm", "forecast_rain_7d_mm"),
            ("weather_observed_at", "observed_at"),
        ):
            value = weather.get(source)
            if value not in (None, ""):
                context[key] = value

    return context or None


def ml_results(results: dict[str, dict]) -> Optional[dict]:
    """ML outputs to hand the assistant so it explains the *real* numbers."""
    values: dict[str, Any] = {}

    crop = _data(results, "get_crop_prediction")
    if crop and crop.get("prediction") is not None:
        values["predicted_crop"] = crop["prediction"]
    fertilizer = _data(results, "get_fertilizer_prediction")
    if fertilizer and fertilizer.get("prediction") is not None:
        values["fertilizer_recommendation"] = fertilizer["prediction"]
    yield_entry = _data(results, "get_yield_prediction")
    if yield_entry and yield_entry.get("prediction") is not None:
        values["yield_prediction_tonnes_per_hectare"] = yield_entry["prediction"]
    irrigation = _data(results, "get_irrigation_prediction")
    if irrigation:
        ml = irrigation.get("ml_prediction") or {}
        if ml.get("prediction") is not None:
            values["irrigation_prediction"] = ml.get("label") or ml["prediction"]

    return values or None


# ─────────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────────

_CACHE: TTLCache = TTLCache(get_settings().agent_answer_cache_ttl_seconds, maxsize=512)
_MISS = object()


def reset_cache() -> None:
    """Drop cached answers (tests / after a data change)."""
    _CACHE.clear()


def _cache_key(
    owner_id: str,
    farm_id: Optional[str],
    language: str,
    question: str,
    results: dict[str, dict],
) -> str:
    """Identity of a request *plus* the data snapshot it was answered from.

    Including the timestamps means a new sensor reading naturally invalidates
    the cached answer instead of replaying yesterday's advice.
    """
    signature = json.dumps(
        {tool: entry.get("as_of") for tool, entry in sorted(results.items())},
        sort_keys=True,
        default=str,
    )
    return f"{owner_id}|{farm_id or '-'}|{language}|{question.strip().lower()}|{signature}"


def answer(
    question: str,
    *,
    client: Any,
    owner_id: str,
    farm_id: Optional[str] = None,
    language: str = "en",
    history: Optional[list[dict]] = None,
    now: Optional[datetime] = None,
    explain: bool = True,
) -> dict[str, Any]:
    """Answer one farm question end to end.

    ``explain=False`` skips the optional assistant explanation (used by tests
    and by callers that only want the structured, deterministic answer).
    """
    question = (question or "").strip()
    lang = language if language in ("mr", "en") else "en"
    now = now or datetime.now(timezone.utc)

    intent = classify_intent(question)
    tools = tools_for_intent(intent)

    gathered = gather(tools, client=client, owner_id=owner_id, farm_id=farm_id, now=now)
    results = gathered["results"]

    key = _cache_key(owner_id, farm_id, lang, question, results)
    cached = _CACHE.get(key, _MISS)
    if cached is not _MISS:
        return {**cached, "cached": True}

    analysis = analyse(results, lang)
    sections = compose(intent, lang, results, analysis)
    text = render(sections, lang)

    explanation: Optional[str] = None
    llm_used = False
    sources: list[dict] = []
    if explain and question:
        explanation, llm_used, sources = _explain(
            question=question,
            lang=lang,
            history=history,
            results=results,
        )

    # The structured answer is the primary reply. The assistant's prose is used
    # only when the routed agent had nothing structured to say: a general
    # agricultural question the keyword router could not map to a tool, or a
    # farm question with no data behind it. A failed explanation can therefore
    # never hide a real ML result or sensor reading.
    fallback = False
    if not text:
        if explanation:
            text = explanation
        else:
            text = _t(lang, "no_farm_intent")
            fallback = True

    payload = {
        "answer": text,
        "sections": sections,
        "explanation": explanation,
        "language": lang,
        "intent": intent,
        "intent_label": _INTENT_LABELS.get(intent, {}).get(lang),
        "tools_used": list(tools),
        "context": context_block(results),
        "conflicts": analysis["conflicts"],
        "uncertainty": analysis["uncertainty"],
        "missing": analysis["missing"],
        "freshness": {tool: entry.get("as_of") for tool, entry in results.items()},
        "llm_used": llm_used,
        "sources": sources,
        "fallback": fallback,
        "cached": False,
    }
    _CACHE.set(key, {k: v for k, v in payload.items() if k != "cached"})
    return payload


def _explain(
    *,
    question: str,
    lang: str,
    history: Optional[list[dict]],
    results: dict[str, dict],
) -> tuple[Optional[str], bool, list[dict]]:
    """Ask the LLM to generate a natural answer from gathered evidence.

    Strategy:
    1. Build a compact plain-text summary of the tool results (sensor
       readings, weather, ML predictions, farm profile).
    2. Call ``rag_service.direct_llm_answer`` — the LLM generates a reply
       using that context and its own agricultural knowledge.  This handles
       greetings, general questions, and farm-specific questions equally well
       because it does **not** require the knowledge base to contain
       relevant documents.
    3. Optionally attempt RAG retrieval and append any cited passages to
       the answer.  If the knowledge base is empty or the question does not
       match any document, this step is silently skipped — the direct answer
       stands on its own.

    Never raises: when the LLM is unavailable the caller still has the
    structured section answer.
    """
    from app import rag_service

    farm_ctx = llm_context(results)
    ml_ctx = ml_results(results)
    tool_summary = _tool_results_summary(results, lang)

    # ── Primary: direct LLM call ─────────────────────────────────────────
    direct = rag_service.direct_llm_answer(
        question,
        ml_results=ml_ctx,
        language=lang,
        history=history,
        farm_context=farm_ctx,
        tool_results_summary=tool_summary,
    )
    direct_text = str(direct.get("answer") or "").strip()
    direct_used = bool(direct.get("llm_used"))

    # ── Fallback: RAG answer_question ────────────────────────────────────
    # Used when direct_llm_answer is unavailable (LLM not configured, pipeline
    # not loaded) so that tests which mock only answer_question still work, and
    # so that documents in the knowledge base are surfaced when available.
    rag_text: str = ""
    rag_used: bool = False
    rag_sources: list[dict] = []
    try:
        rag_resp = rag_service.answer_question(
            question,
            ml_results=ml_ctx,
            language=lang,
            history=history,
            farm_context=farm_ctx,
        )
        status = rag_resp.get("retrieval_status", "")
        raw_answer = str(rag_resp.get("answer") or "").strip()
        # Use the RAG answer when:
        # (a) the direct call produced nothing, OR
        # (b) RAG found real documents (OK status) — append sources regardless.
        if status == "OK" and raw_answer:
            rag_text = raw_answer
            rag_used = bool(rag_resp.get("llm_used"))
            rag_sources = list(rag_resp.get("sources") or [])
        elif not direct_text and raw_answer and not _is_retrieval_error_message(raw_answer):
            # RAG returned something useful (e.g. a mocked answer in tests)
            rag_text = raw_answer
            rag_used = bool(rag_resp.get("llm_used"))
            rag_sources = list(rag_resp.get("sources") or [])
    except RagUnavailableError as exc:
        logger.info("Agent RAG fallback unavailable: %s", exc)
    except Exception as exc:  # noqa: BLE001 — the answer must survive this
        logger.warning("Agent RAG fallback failed: %s", type(exc).__name__)

    # ── Combine ──────────────────────────────────────────────────────────
    # Direct LLM answer takes precedence; RAG sources are always appended
    # when available.
    if direct_text:
        return direct_text, direct_used, rag_sources
    if rag_text:
        return rag_text, rag_used, rag_sources
    return None, False, []


def _tool_results_summary(results: dict[str, dict], lang: str) -> Optional[str]:
    """Build a compact text block of what the tools found, for the LLM prompt."""
    lines: list[str] = []

    farm = _data(results, "get_farm_profile") or {}
    if farm:
        parts = [v for k, v in farm.items()
                 if k in ("name", "location", "current_crop", "soil_type",
                          "area_value", "area_unit", "irrigation_type")
                 and v not in (None, "")]
        if parts:
            lines.append("Farm: " + " · ".join(str(p) for p in parts))
        stage = farm.get("growth_stage")
        if stage:
            lines.append(f"Growth stage: {stage}")

    sensors = _data(results, "get_sensor_readings")
    if sensors:
        sensor_parts = []
        for ch in ("soil_moisture", "soil_temperature", "temperature", "humidity"):
            v = sensors.get(ch)
            if v is not None:
                unit = "%" if ch in ("soil_moisture", "humidity") else "°C"
                sensor_parts.append(f"{ch.replace('_', ' ')} {v}{unit}")
        if sensor_parts:
            freshness = sensors.get("freshness", "")
            age = sensors.get("age_hours")
            age_str = f" ({age:.1f}h ago)" if age is not None else ""
            demo_flag = " [DEMO/simulated]" if sensors.get("is_demo") else ""
            lines.append(f"Sensor readings{age_str}{demo_flag}: " + ", ".join(sensor_parts))
        if sensors.get("freshness") in ("stale", "offline"):
            lines.append(f"  ⚠ Sensor data is {sensors['freshness']} — may not reflect current conditions.")

    weather = _data(results, "get_weather_information")
    if weather:
        w_parts = []
        if weather.get("temperature_c") is not None:
            w_parts.append(f"temp {weather['temperature_c']}°C")
        if weather.get("humidity_pct") is not None:
            w_parts.append(f"humidity {weather['humidity_pct']}%")
        if weather.get("forecast_rain_7d_mm") is not None:
            w_parts.append(f"7-day rain forecast {weather['forecast_rain_7d_mm']} mm (not confirmed)")
        if w_parts:
            loc = weather.get("location") or "farm location"
            lines.append(f"Weather at {loc}: " + ", ".join(w_parts))

    crop = _data(results, "get_crop_prediction")
    if crop and crop.get("prediction"):
        lines.append(f"Crop recommendation (ML model): {crop['prediction']}")

    fertilizer = _data(results, "get_fertilizer_prediction")
    if fertilizer and fertilizer.get("prediction"):
        lines.append(f"Fertilizer recommendation (ML model): {fertilizer['prediction']}")

    irrigation = _data(results, "get_irrigation_prediction")
    if irrigation:
        ml = irrigation.get("ml_prediction") or {}
        rule = irrigation.get("rule_based_baseline") or {}
        if ml.get("prediction") is not None:
            lines.append(f"Irrigation (ML model): {ml.get('label') or ml['prediction']}")
        elif rule.get("action"):
            lines.append(f"Irrigation (rule baseline): {rule['action']}")

    yield_pred = _data(results, "get_yield_prediction")
    if yield_pred and yield_pred.get("prediction") is not None:
        lines.append(f"Yield prediction (ML model): {yield_pred['prediction']} t/ha")

    drought = _data(results, "get_drought_context")
    if drought and drought.get("drought_severity"):
        lines.append(f"Drought assessment: severity = {drought['drought_severity']}")
        if drought.get("top_recommendations"):
            lines.append("  Top drought actions: " + "; ".join(drought["top_recommendations"][:2]))

    organic = _data(results, "get_organic_guidance")
    if organic and organic.get("recommendation_summary"):
        lines.append(f"Organic farming guidance: {organic['recommendation_summary']}")

    history_data = _data(results, "get_farm_history")
    if history_data and history_data.get("count", 0) > 0:
        lines.append(f"Saved predictions: {history_data['count']} in history")

    plan = _data(results, "get_available_farm_recommendations")
    if plan and plan.get("actions"):
        top_action = plan["actions"][0]
        lines.append(
            f"Top farm action ({top_action.get('priority', '')}): {top_action.get('action', '')}"
        )

    return "\n".join(lines) if lines else None
