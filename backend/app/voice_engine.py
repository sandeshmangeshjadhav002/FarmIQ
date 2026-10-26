"""Deterministic voice-assistant intent engine for FarmIQ.

No LLM is required. Intent classification uses keyword matching over a curated
bilingual (Marathi + English) vocabulary, followed by slot extraction from the
recognised text.

All text responses are pre-composed in both languages. The engine calls the
*existing* ML adapter functions directly — no ML logic is duplicated here.

Design principles:
  * No hardcoded predictions or fabricated agricultural data.
  * A prediction question ALWAYS runs the model. Any input the farmer did not
    state is filled from the latest sensor reading, then the farm profile, then
    the average/mode of the raw training dataset (see ml/defaults.py), and
    every assumed value is listed back to the farmer.
  * A follow-up question is only asked when a value could not be resolved at
    all (e.g. the raw dataset used for averages is unavailable).
  * Farm questions with no dedicated model (soil health, pests, …) are routed
    to the closest ML model instead of being rejected.
  * Questions this vocabulary cannot classify at all are handed to the RAG
    assistant by the router (see routers/voice.py), so an unfamiliar Marathi
    question still gets an answer instead of "I did not understand".
  * If a model call fails, the exact error is surfaced clearly.
  * Sensor readings are fetched from the real DB; never invented.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger("farmiq.voice")

# ─────────────────────────────────────────────────────────────────────────
# Response templates (Marathi + English)
# ─────────────────────────────────────────────────────────────────────────

_RESPONSES: dict[str, dict[str, str]] = {
    # ── crop recommendation ───────────────────────────────────────────
    "crop_ask_all": {
        "mr": (
            "नक्की. तुमच्या शेतासाठी योग्य पीक सुचवण्यासाठी मला खालील माहिती हवी आहे:\n"
            "नायट्रोजन (N), फॉस्फरस (P), पोटॅशियम (K), तापमान, आर्द्रता, मातीचा pH आणि पाऊस.\n"
            "कृपया ही माहिती द्या."
        ),
        "en": (
            "Sure. To recommend the right crop for your field I need:\n"
            "Nitrogen (N), Phosphorus (P), Potassium (K), temperature, humidity, soil pH, and rainfall.\n"
            "Please provide these values."
        ),
    },
    "crop_ask_missing": {
        "mr": "पुढील माहिती अजून मिळाली नाही: {fields}. कृपया ती द्या.",
        "en": "I still need the following values: {fields}. Please provide them.",
    },
    "crop_result": {
        "mr": "तुमच्या शेतासाठी **{crop}** हे पीक योग्य आहे.",
        "en": "The recommended crop for your field is **{crop}**.",
    },
    "crop_result_top": {
        "mr": "शीर्ष ३ पिके: {top}. सर्वात योग्य पीक **{crop}** आहे.",
        "en": "Top 3 crops: {top}. The best match is **{crop}**.",
    },
    # ── fertilizer ────────────────────────────────────────────────────
    "fert_ask_all": {
        "mr": (
            "खत शिफारशीसाठी मला हे हवे आहे:\n"
            "तापमान, आर्द्रता, मातीची ओलावा, नायट्रोजन, पोटॅशियम, फॉस्फरस, मातीचा प्रकार आणि पिकाचा प्रकार.\n"
            "कृपया माहिती द्या."
        ),
        "en": (
            "For fertilizer recommendation I need:\n"
            "temperature, humidity, moisture, nitrogen, potassium, phosphorous, soil type, and crop type.\n"
            "Please provide these values."
        ),
    },
    "fert_ask_missing": {
        "mr": "अजून मिळालेली माहिती: {fields}. कृपया ती द्या.",
        "en": "Still missing: {fields}. Please provide them.",
    },
    "fert_result": {
        "mr": "तुमच्या {crop_type} पिकासाठी **{fertilizer}** हे खत वापरण्याची शिफारस आहे.",
        "en": "The recommended fertilizer for your {crop_type} crop is **{fertilizer}**.",
    },
    # ── irrigation ────────────────────────────────────────────────────
    "irr_ask_all": {
        "mr": (
            "सिंचन नियोजनासाठी मला मातीची ओलावा, मातीचे तापमान, हवेचे तापमान, "
            "आर्द्रता, पेरणीपासूनचे दिवस आणि पिकाचा प्रकार हवे आहे."
        ),
        "en": (
            "For irrigation planning I need soil moisture, soil temperature, air temperature, "
            "humidity, days since planting, and crop type."
        ),
    },
    "irr_ask_missing": {
        "mr": "सिंचनासाठी अजून हवे: {fields}. कृपया माहिती द्या.",
        "en": "For irrigation I still need: {fields}. Please provide them.",
    },
    "irr_irrigate": {
        "mr": (
            "सध्याच्या {soil_moisture} मातीच्या ओलाव्यानुसार तुमच्या {crop_type} शेताला "
            "आज पाणी देणे आवश्यक आहे."
        ),
        "en": (
            "Based on current soil moisture {soil_moisture}, your {crop_type} field "
            "needs irrigation today."
        ),
    },
    "irr_no_irrigate": {
        "mr": (
            "सध्याच्या {soil_moisture} मातीच्या ओलाव्यानुसार आज पाणी देण्याची "
            "आवश्यकता नाही."
        ),
        "en": (
            "Based on current soil moisture {soil_moisture}, no irrigation is needed today."
        ),
    },
    "irr_baseline": {
        "mr": "नियमानुसार: माती ओलावा ३० पेक्षा कमी असल्यास पाणी द्या.",
        "en": "Baseline rule: irrigate when soil moisture falls below 30.",
    },
    # ── yield ─────────────────────────────────────────────────────────
    "yield_ask_all": {
        "mr": (
            "उत्पादन अंदाजासाठी मला हे हवे: राज्य, हंगाम, पिकाचे नाव, वर्ष, "
            "क्षेत्र (हेक्टर), वार्षिक पाऊस, खत (किलो) आणि कीटकनाशक (किलो)."
        ),
        "en": (
            "For yield prediction I need: state, season, crop name, year, "
            "area (hectares), annual rainfall, fertilizer (kg), and pesticide (kg)."
        ),
    },
    "yield_ask_missing": {
        "mr": "उत्पादन अंदाजासाठी अजून हवे: {fields}. कृपया माहिती द्या.",
        "en": "For yield prediction I still need: {fields}. Please provide them.",
    },
    "yield_result": {
        "mr": (
            "{state} मधील {crop} पिकाचा अंदाजित उत्पादन दर "
            "**{yield_tha:.2f} टन/हेक्टर** आहे."
        ),
        "en": (
            "The estimated yield for {crop} in {state} is "
            "**{yield_tha:.2f} tonnes per hectare**."
        ),
    },
    # ── sensors ───────────────────────────────────────────────────────
    "sensor_no_data": {
        "mr": (
            "तुमच्या खात्याशी सध्या कोणतेही सेन्सर जोडलेले नाहीत किंवा "
            "अद्याप कोणतेही वाचन उपलब्ध नाही."
        ),
        "en": "No sensors are connected to your account or no readings are available yet.",
    },
    "sensor_data": {
        "mr": (
            "शेवटचे वाचन ({time}): "
            "माती ओलावा {moisture}, तापमान {temp}, आर्द्रता {humidity}."
        ),
        "en": (
            "Latest reading ({time}): "
            "soil moisture {moisture}, temperature {temp}, humidity {humidity}."
        ),
    },
    # ── navigation / help ─────────────────────────────────────────────
    "nav_help": {
        "mr": (
            "FarmIQ मध्ये खालील सुविधा आहेत:\n"
            "• पीक शिफारस – तुमच्या जमिनीसाठी योग्य पीक\n"
            "• खत शिफारस – योग्य खताची निवड\n"
            "• सिंचन नियोजन – केव्हा पाणी द्यावे\n"
            "• उत्पादन अंदाज – अपेक्षित उत्पादन\n"
            "• सेन्सर माहिती – लाइव्ह शेत डेटा\n"
            "कोणती मदत हवी आहे?"
        ),
        "en": (
            "FarmIQ offers these features:\n"
            "• Crop recommendation – find the right crop for your soil\n"
            "• Fertilizer recommendation – choose the right fertilizer\n"
            "• Irrigation planning – when to water your crops\n"
            "• Yield prediction – expected harvest\n"
            "• Sensor data – live field readings\n"
            "Which one would you like help with?"
        ),
    },
    # ── transparency / routing ────────────────────────────────────────
    "assumed_note": {
        "mr": "गृहीत धरलेली माहिती (तुम्ही दिली नाही): {fields}.",
        "en": "Assumed inputs (not provided by you): {fields}.",
    },
    "routed_prefix": {
        "mr": (
            "या प्रश्नासाठी स्वतंत्र मॉडेल नाही, म्हणून मी सर्वात जवळचे विश्लेषण "
            "({topic}) वापरले:"
        ),
        "en": (
            "There is no dedicated model for that question, so I used the closest "
            "FarmIQ analysis ({topic}):"
        ),
    },
    # ── generic errors ────────────────────────────────────────────────
    "model_error": {
        "mr": "माफ करा, मॉडेल सध्या उपलब्ध नाही: {error}",
        "en": "Sorry, the model is currently unavailable: {error}",
    },
    "unknown": {
        "mr": (
            "मला तुमची विनंती समजली नाही. कृपया पीक शिफारस, खत, सिंचन, "
            "उत्पादन अंदाज किंवा सेन्सर माहितीबद्दल विचारा."
        ),
        "en": (
            "I did not understand your request. Please ask about crop recommendation, "
            "fertilizer, irrigation, yield prediction, or sensor data."
        ),
    },
}


def t(key: str, lang: str, **kwargs) -> str:
    """Look up a response template and format it. Falls back to English."""
    template = _RESPONSES.get(key, {}).get(lang) or _RESPONSES.get(key, {}).get("en", key)
    try:
        return template.format(**kwargs)
    except (KeyError, ValueError):
        return template


# ─────────────────────────────────────────────────────────────────────────
# Intent classification (deterministic keyword matching)
# ─────────────────────────────────────────────────────────────────────────

_INTENT_KEYWORDS: dict[str, list[str]] = {
    "crop_recommendation": [
        # Marathi — specific crop-selection phrases
        "पीक शिफारस", "कोणते पीक", "पीक निवड", "पीक सुचवा", "शेतासाठी पीक",
        "पेरणी", "कोणते पिक", "पीक निवडण", "योग्य पीक",
        # English — specific to avoid matching "my crops" in irrigation
        "crop recommendation", "which crop", "suggest crop", "what to plant",
        "best crop to grow", "recommend a crop", "suitable crop",
    ],
    "fertilizer_recommendation": [
        # Marathi
        "खत", "खते", "खत शिफारस", "कोणते खत", "खत द्यावे", "पोषक",
        # English
        "fertilizer", "fertiliser", "which fertilizer", "fertilizer advice",
        "manure", "npk", "urea", "dap",
    ],
    "irrigation": [
        # Marathi — explicit water-giving phrases
        "पाणी द्यावे", "पाण्याची गरज", "पाणी देणे", "शेताला पाणी",
        "सिंचन", "ड्रिप",
        # English — avoid "water" alone (too ambiguous)
        "irrigat", "watering my crops", "drip irrigation", "when to water", "sprinkler",
        "should i water", "need to water",
    ],
    "yield_prediction": [
        # Marathi
        "उत्पादन", "उत्पन्न", "किती उत्पादन", "अंदाज", "उत्पादन अंदाज",
        "किती टन", "हेक्टर",
        # English
        "yield", "production", "harvest", "how much produce",
        "tonnes per hectare", "predict yield",
    ],
    "sensor_query": [
        # Marathi
        "सेन्सर", "माती ओलावा", "आर्द्रता किती", "लाइव्ह डेटा",
        "शेत डेटा", "वाचन", "मापन", "ओलावा किती",
        # English — specific multi-word phrases to avoid false matches
        "sensor data", "soil moisture", "humidity level", "temperature reading",
        "live sensor", "what is the moisture", "how much moisture", "sensor reading",
        "soil reading",
    ],
    "navigation_help": [
        # Marathi
        "मदत", "काय करता", "काय आहे", "सुविधा", "कार्य", "कशासाठी",
        # English
        "help", "what can", "features", "options", "how to use",
        "what do you do", "farmiq",
    ],
}


def classify_intent(text: str) -> str:
    """Weighted keyword matching — longer phrases score higher to reduce ambiguity."""
    low = text.lower()
    scores: dict[str, float] = {intent: 0.0 for intent in _INTENT_KEYWORDS}
    for intent, kws in _INTENT_KEYWORDS.items():
        for kw in kws:
            if kw.lower() in low:
                # Weight by phrase length so "soil moisture" > "soil"
                scores[intent] += 1.0 + len(kw.split()) * 0.5
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "unknown"


# Devanagari codepoints — Marathi (and Hindi) questions are written in them.
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")


def detect_language(text: str, fallback: str = "en") -> str:
    """Return "mr" when *text* contains Devanagari, otherwise *fallback*.

    The client sends the app's display language, but farmers often type or
    dictate Marathi while the app is in English. Following the language of the
    question itself avoids answering a Marathi question in English, and the
    reverse.
    """
    return "mr" if _DEVANAGARI_RE.search(text or "") else fallback


# Farm questions that have no dedicated model. Rather than answering
# "I did not understand", the closest ML model is run and the answer says so.
# Ordered most-specific first; only consulted when classify_intent() is unsure,
# so genuinely off-topic questions ("capital of India") stay unknown.
_TOPIC_ROUTES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("yield_prediction", (
        "harvest", "production", "profit", "income", "market price", "sell",
        "उत्पादन", "उत्पन्न", "नफा", "महसूल", "बाजार भाव", "टन",
    )),
    ("irrigation", (
        "water", "irrigat", "drip", "sprinkler", "borewell", "well",
        "पाणी", "सिंचन", "विहीर", "पाऊस",
    )),
    ("fertilizer_recommendation", (
        "soil", "माती", "मृदा", "nutrient", "पोषक", "compost", "कंपोस्ट",
        "manure", "खत", "npk", "urea", "dap",
    )),
    ("crop_recommendation", (
        "crop", "पीक", "पिक", "plant", "seed", "बियाणे", "pest", "कीटक",
        "insect", "disease", "रोग", "फवारणी", "pesticide", "कीटकनाशक", "मावा",
    )),
)

_TOPIC_LABELS: dict[str, dict[str, str]] = {
    "crop_recommendation": {"mr": "पीक शिफारस", "en": "crop recommendation"},
    "fertilizer_recommendation": {"mr": "खत शिफारस", "en": "fertilizer recommendation"},
    "irrigation": {"mr": "सिंचन नियोजन", "en": "irrigation planning"},
    "yield_prediction": {"mr": "उत्पादन अंदाज", "en": "yield prediction"},
}


def route_topic(text: str) -> Optional[str]:
    """Map an unmatched farm question to the closest ML domain (or None)."""
    low = text.lower()
    for intent, keywords in _TOPIC_ROUTES:
        if any(kw in low for kw in keywords):
            return intent
    return None


# ─────────────────────────────────────────────────────────────────────────
# Number extraction helper (Devanagari + ASCII)
# ─────────────────────────────────────────────────────────────────────────

_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

_MARATHI_NUMBER_WORDS: dict[str, float] = {
    "एक": 1, "दोन": 2, "तीन": 3, "चार": 4, "पाच": 5,
    "सहा": 6, "सात": 7, "आठ": 8, "नऊ": 9, "दहा": 10,
    "वीस": 20, "तीस": 30, "चाळीस": 40, "पन्नास": 50,
    "साठ": 60, "सत्तर": 70, "ऐंशी": 80, "नव्वद": 90,
    "शंभर": 100,
}


def _extract_marathi_number_word(text: str) -> Optional[float]:
    """Match Marathi number words at word boundaries only (not inside longer words)."""
    for word, val in _MARATHI_NUMBER_WORDS.items():
        # Use spaces or string boundaries to avoid matching inside larger words
        # e.g. "साठ" inside "शेतासाठी" must NOT match
        pattern = r"(?<![^\s।,;])" + re.escape(word) + r"(?![^\s।,;])"
        if re.search(pattern, text):
            return val
    return None


def extract_number(text: str, key: str) -> Optional[float]:
    """Try to extract a numeric value associated with a slot key from text.

    Handles ASCII digits, Devanagari digits, and common Marathi number words.
    Returns None when no number is found.
    """
    # Normalise Devanagari digits to ASCII
    normalised = text.translate(_DEVANAGARI_DIGITS)

    # Patterns like "N=90", "nitrogen 90", "नायट्रोजन 90"
    patterns = [
        rf"{re.escape(key)}[=:\s]*([0-9]+(?:\.[0-9]+)?)",
        rf"([0-9]+(?:\.[0-9]+)?)\s*{re.escape(key)}",
    ]
    for pat in patterns:
        m = re.search(pat, normalised, re.IGNORECASE)
        if m:
            return float(m.group(1))

    # Marathi word numbers (word-boundary safe)
    return _extract_marathi_number_word(text)


# ─────────────────────────────────────────────────────────────────────────
# Slot definitions per intent
# ─────────────────────────────────────────────────────────────────────────

_CROP_SLOTS = {
    "N":           {"mr": "नायट्रोजन (N kg/ha)",      "en": "Nitrogen (N kg/ha)"},
    "P":           {"mr": "फॉस्फरस (P kg/ha)",        "en": "Phosphorus (P kg/ha)"},
    "K":           {"mr": "पोटॅशियम (K kg/ha)",       "en": "Potassium (K kg/ha)"},
    "temperature": {"mr": "तापमान (°C)",              "en": "Temperature (°C)"},
    "humidity":    {"mr": "आर्द्रता (%)",             "en": "Humidity (%)"},
    "ph":          {"mr": "मातीचा pH",                "en": "Soil pH"},
    "rainfall":    {"mr": "पाऊस (mm)",               "en": "Rainfall (mm)"},
}
_CROP_ALIASES = {"n": "N", "p": "P", "k": "K", "ph": "ph", "paus": "rainfall",
                 "rain": "rainfall", "temp": "temperature", "humi": "humidity"}

_FERT_NUMERIC_SLOTS = {
    "temparature": {"mr": "तापमान (°C)", "en": "Temperature (°C)"},   # typo retained
    "humidity":    {"mr": "आर्द्रता (%)", "en": "Humidity (%)"},
    "moisture":    {"mr": "मातीची ओलावा (%)", "en": "Soil moisture (%)"},
    "nitrogen":    {"mr": "नायट्रोजन (kg/ha)", "en": "Nitrogen (kg/ha)"},
    "potassium":   {"mr": "पोटॅशियम (kg/ha)", "en": "Potassium (kg/ha)"},
    "phosphorous": {"mr": "फॉस्फरस (kg/ha)", "en": "Phosphorous (kg/ha)"},
}
_FERT_CAT_SLOTS = {
    "soil_type": {"mr": "मातीचा प्रकार", "en": "Soil type"},
    "crop_type": {"mr": "पिकाचा प्रकार", "en": "Crop type"},
}

_IRR_SLOTS = {
    "soil_moisture":    {"mr": "मातीची ओलावा (0–2000)", "en": "Soil moisture (0–2000)"},
    "soil_temperature": {"mr": "मातीचे तापमान (°C)", "en": "Soil temperature (°C)"},
    "temperature":      {"mr": "हवेचे तापमान (°C)", "en": "Air temperature (°C)"},
    "humidity":         {"mr": "आर्द्रता (%)", "en": "Humidity (%)"},
    "crop_days":        {"mr": "पेरणीपासूनचे दिवस", "en": "Days since planting"},
    "crop_type":        {"mr": "पिकाचा प्रकार", "en": "Crop type"},
}

_YIELD_TEXT_SLOTS = {
    "state_name": {"mr": "राज्याचे नाव", "en": "State name"},
    "season":     {"mr": "हंगाम (खरीप/रब्बी)", "en": "Season (Kharif/Rabi)"},
    "crop":       {"mr": "पिकाचे नाव", "en": "Crop name"},
}
_YIELD_NUMERIC_SLOTS = {
    "crop_year":       {"mr": "वर्ष", "en": "Year"},
    "area":            {"mr": "क्षेत्र (हेक्टर)", "en": "Area (hectares)"},
    "annual_rainfall": {"mr": "वार्षिक पाऊस (mm)", "en": "Annual rainfall (mm)"},
    "fertilizer":      {"mr": "खत (किलो)", "en": "Fertilizer (kg)"},
    "pesticide":       {"mr": "कीटकनाशक (किलो)", "en": "Pesticide (kg)"},
}

# Where an assumed value came from — shown to the farmer for transparency.
_SOURCE_LABELS: dict[str, dict[str, str]] = {
    "live sensor":     {"mr": "थेट सेन्सर", "en": "live sensor"},
    "farm profile":    {"mr": "शेत माहिती", "en": "farm profile"},
    "dataset average": {"mr": "डेटासेट सरासरी", "en": "dataset average"},
    "app default":     {"mr": "ॲप डीफॉल्ट", "en": "app default"},
}


def _slot_label(slot_key: str, lang: str, slot_defs: dict) -> str:
    return slot_defs.get(slot_key, {}).get(lang) or slot_key


def _slots_label_list(missing: list[str], lang: str, defs: dict) -> str:
    return ", ".join(_slot_label(s, lang, defs) for s in missing)


def _format_value(value: Any) -> str:
    try:
        return f"{round(float(value), 2):g}"
    except (TypeError, ValueError):
        return str(value)


def _assumed_note(assumed: list[tuple[str, Any, str]], lang: str, defs: dict) -> str:
    """"Assumed inputs: …" sentence appended to every auto-filled answer."""
    if not assumed:
        return ""
    parts = [
        f"{_slot_label(slot, lang, defs)} = {_format_value(value)} ({source})"
        for slot, value, source in assumed
    ]
    return "\n\n" + t("assumed_note", lang, fields="; ".join(parts))


# ─────────────────────────────────────────────────────────────────────────
# Slot extraction from transcript
# ─────────────────────────────────────────────────────────────────────────

_SOIL_TYPE_MAP = {
    "वाळू": "Sandy", "sandy": "Sandy", "loamy": "Loamy", "चिकण": "Loamy",
    "काळी": "Black", "black": "Black", "लाल": "Red", "red": "Red",
    "clayey": "Clayey", "clay": "Clayey",
}
_CROP_TYPE_MAP = {
    "गहू": "Wheat", "wheat": "Wheat", "धान": "Paddy", "paddy": "Paddy",
    "rice": "Paddy", "तांदूळ": "Paddy", "मका": "Maize", "maize": "Maize",
    "कपास": "Cotton", "cotton": "Cotton", "ऊस": "Sugarcane",
    "sugarcane": "Sugarcane", "soybean": "Wheat",
}
_SEASON_MAP = {
    "खरीप": "Kharif", "kharif": "Kharif", "रब्बी": "Rabi", "rabi": "Rabi",
    "rabi": "Rabi", "उन्हाळी": "Summer", "summer": "Summer",
}
_IRRCROP_MAP = {**_CROP_TYPE_MAP, "paddy": "Paddy", "ground nuts": "Ground Nuts",
               "भुईमूग": "Ground Nuts"}


def _extract_categorical(text: str, mapping: dict) -> Optional[str]:
    low = text.lower()
    for k, v in mapping.items():
        if k.lower() in low:
            return v
    return None


def extract_crop_slots(text: str, ctx: dict) -> tuple[dict, list[str]]:
    slots = dict(ctx or {})
    for key in _CROP_SLOTS:
        if key not in slots:
            v = extract_number(text, key)
            if v is not None:
                slots[key] = v
    # Also try aliases
    for alias, real in _CROP_ALIASES.items():
        if real not in slots:
            v = extract_number(text, alias)
            if v is not None:
                slots[real] = v
    missing = [k for k in _CROP_SLOTS if k not in slots]
    return slots, missing


def extract_fert_slots(text: str, ctx: dict) -> tuple[dict, list[str]]:
    slots = dict(ctx or {})
    for key in _FERT_NUMERIC_SLOTS:
        if key not in slots:
            v = extract_number(text, key)
            if v is not None:
                slots[key] = v
    if "soil_type" not in slots:
        v = _extract_categorical(text, _SOIL_TYPE_MAP)
        if v:
            slots["soil_type"] = v
    if "crop_type" not in slots:
        v = _extract_categorical(text, _CROP_TYPE_MAP)
        if v:
            slots["crop_type"] = v
    all_slots = list(_FERT_NUMERIC_SLOTS) + list(_FERT_CAT_SLOTS)
    missing = [k for k in all_slots if k not in slots]
    return slots, missing


def extract_irr_slots(text: str, ctx: dict) -> tuple[dict, list[str]]:
    slots = dict(ctx or {})
    for key in _IRR_SLOTS:
        if key not in slots:
            if key == "crop_type":
                v = _extract_categorical(text, _IRRCROP_MAP)
                if v:
                    slots[key] = v
            else:
                v = extract_number(text, key)
                if v is not None:
                    slots[key] = v
    missing = [k for k in _IRR_SLOTS if k not in slots]
    return slots, missing


def extract_yield_slots(text: str, ctx: dict) -> tuple[dict, list[str]]:
    slots = dict(ctx or {})
    for key in _YIELD_NUMERIC_SLOTS:
        if key not in slots:
            v = extract_number(text, key)
            if v is not None:
                slots[key] = v
    if "season" not in slots:
        v = _extract_categorical(text, _SEASON_MAP)
        if v:
            slots["season"] = v
    if "crop" not in slots:
        v = _extract_categorical(text, _CROP_TYPE_MAP)
        if v:
            slots["crop"] = v
    if "state_name" not in slots:
        # simple heuristic: try common state names
        states = ["maharashtra", "punjab", "karnataka", "gujarat", "andhra",
                  "तेलंगणा", "महाराष्ट्र", "पंजाब", "गुजरात"]
        low = text.lower()
        for s in states:
            if s.lower() in low:
                slots["state_name"] = s.title()
                break
    all_slots = (list(_YIELD_TEXT_SLOTS) + ["crop_year", "area",
                  "annual_rainfall", "fertilizer", "pesticide"])
    missing = [k for k in all_slots if k not in slots]
    return slots, missing


# ─────────────────────────────────────────────────────────────────────────
# Missing-input completion
# ─────────────────────────────────────────────────────────────────────────

def _complete(
    domain: str,
    slots: dict[str, Any],
    missing: list[str],
    farm: Optional[dict],
    latest_sensor: Optional[dict],
    lang: str,
    defs: dict,
) -> tuple[dict[str, Any], list[str], str]:
    """Fill missing model inputs and describe every assumed value.

    Returns ``(slots, unresolved, assumed_note)``. ``unresolved`` is empty in
    the normal case; it is non-empty only when no source at all could supply a
    value (e.g. the raw dataset behind the averages is missing).
    """
    if not missing:
        return slots, [], ""

    from app.errors import ModelNotAvailableError
    from ml import defaults as ml_defaults

    try:
        filled, sources = ml_defaults.fill_missing_slots(
            domain, slots, missing, farm, latest_sensor
        )
    except ModelNotAvailableError as exc:
        logger.warning("Cannot derive defaults for '%s': %s", domain, exc.detail)
        return slots, list(missing), ""

    unresolved = [slot for slot in missing if slot not in filled]
    assumed = [
        (slot, filled[slot], _SOURCE_LABELS.get(sources.get(slot, ""), {}).get(lang, ""))
        for slot in missing
        if slot in filled
    ]
    return filled, unresolved, _assumed_note(assumed, lang, defs)


# ─────────────────────────────────────────────────────────────────────────
# Main dispatch
# ─────────────────────────────────────────────────────────────────────────

def process(
    message: str,
    language: str,
    context: Optional[dict],
    latest_sensor: Optional[dict],
    ml_adapter,  # ml.adapter.MLAdapter instance
    farm: Optional[dict] = None,
) -> dict[str, Any]:
    """Classify intent, run the matching ML model, and return a response dict.

    A prediction question always runs its model: inputs the farmer did not
    state are completed from the sensor reading, the farm profile and the raw
    dataset averages, and listed back in the answer.
    """
    intent = classify_intent(message)
    # Follow the language of the question, not only the app's display language:
    # farmers often type or dictate Marathi while the app is in English.
    client_lang = language if language in ("mr", "en") else "en"
    lang = detect_language(message, client_lang)

    # Farm questions with no dedicated model → closest model (never "I did not
    # understand"), while genuinely off-topic questions stay unknown.
    routed = False
    if intent == "unknown":
        target = route_topic(message)
        if target:
            intent, routed = target, True

    result = _dispatch(intent, message, lang, context, latest_sensor, ml_adapter, farm)

    if routed and not result.get("follow_up"):
        topic = _TOPIC_LABELS.get(intent, {}).get(lang, intent)
        prefix = t("routed_prefix", lang, topic=topic)
        result["response_text"] = f"{prefix}\n\n{result.get('response_text', '')}"

    return result


def _dispatch(
    intent: str,
    message: str,
    lang: str,
    context: Optional[dict],
    latest_sensor: Optional[dict],
    ml_adapter,
    farm: Optional[dict],
) -> dict[str, Any]:
    # ── crop recommendation ───────────────────────────────────────────
    if intent == "crop_recommendation":
        slots, missing = extract_crop_slots(message, context or {})
        slots, unresolved, note = _complete(
            "crop", slots, missing, farm, latest_sensor, lang, _CROP_SLOTS
        )
        if unresolved:
            first_time = not (context or {})
            key = "crop_ask_all" if first_time else "crop_ask_missing"
            return {
                "response_text": t(key, lang, fields=_slots_label_list(unresolved, lang, _CROP_SLOTS)),
                "language": lang, "intent": intent, "follow_up": True,
                "missing_slots": unresolved, "prediction": None,
                "context": slots,
            }
        try:
            result = ml_adapter.predict_crop(slots)
            crop = result["prediction"]
            tops = result.get("details", {}).get("top", [])
            if tops:
                top_str = ", ".join(f"{x['crop']} ({x['probability']*100:.0f}%)" for x in tops)
                text = t("crop_result_top", lang, crop=crop, top=top_str)
            else:
                text = t("crop_result", lang, crop=crop)
            return {"response_text": text + note, "language": lang, "intent": intent,
                    "follow_up": False, "missing_slots": [], "prediction": result}
        except Exception as exc:
            return _error_response(str(exc), lang, intent)

    # ── fertilizer recommendation ─────────────────────────────────────
    if intent == "fertilizer_recommendation":
        slots, missing = extract_fert_slots(message, context or {})
        all_defs = {**_FERT_NUMERIC_SLOTS, **_FERT_CAT_SLOTS}
        slots, unresolved, note = _complete(
            "fertilizer", slots, missing, farm, latest_sensor, lang, all_defs
        )
        if unresolved:
            first_time = not (context or {})
            key = "fert_ask_all" if first_time else "fert_ask_missing"
            return {
                "response_text": t(key, lang, fields=_slots_label_list(unresolved, lang, all_defs)),
                "language": lang, "intent": intent, "follow_up": True,
                "missing_slots": unresolved, "prediction": None,
                "context": slots,
            }
        try:
            result = ml_adapter.predict_fertilizer(slots)
            text = t("fert_result", lang,
                     fertilizer=result["prediction"],
                     crop_type=slots.get("crop_type", ""))
            return {"response_text": text + note, "language": lang, "intent": intent,
                    "follow_up": False, "missing_slots": [], "prediction": result}
        except Exception as exc:
            return _error_response(str(exc), lang, intent)

    # ── irrigation ────────────────────────────────────────────────────
    if intent == "irrigation":
        slots, missing = extract_irr_slots(message, context or {})
        slots, unresolved, note = _complete(
            "irrigation", slots, missing, farm, latest_sensor, lang, _IRR_SLOTS
        )
        if unresolved:
            return {
                "response_text": t("irr_ask_missing", lang,
                                   fields=_slots_label_list(unresolved, lang, _IRR_SLOTS)),
                "language": lang, "intent": intent, "follow_up": True,
                "missing_slots": unresolved, "prediction": None,
                "context": slots,
            }
        try:
            result = ml_adapter.predict_irrigation(slots)
            source = result.get("source", "model")
            m = str(slots.get("soil_moisture", "—"))
            ct = _irrigation_crop_label(slots.get("crop_type"))
            key = "irr_irrigate" if result["prediction"] == 1 else "irr_no_irrigate"
            text = t(key, lang, soil_moisture=m, crop_type=ct)
            if source == "baseline":
                text += "\n" + t("irr_baseline", lang)
            return {"response_text": text + note, "language": lang, "intent": intent,
                    "follow_up": False, "missing_slots": [], "prediction": result}
        except Exception as exc:
            return _error_response(str(exc), lang, intent)

    # ── yield prediction ──────────────────────────────────────────────
    if intent == "yield_prediction":
        slots, missing = extract_yield_slots(message, context or {})
        all_defs = {**_YIELD_TEXT_SLOTS, **_YIELD_NUMERIC_SLOTS}
        slots, unresolved, note = _complete(
            "yield", slots, missing, farm, latest_sensor, lang, all_defs
        )
        if unresolved:
            first_time = not (context or {})
            key = "yield_ask_all" if first_time else "yield_ask_missing"
            return {
                "response_text": t(key, lang, fields=_slots_label_list(unresolved, lang, all_defs)),
                "language": lang, "intent": intent, "follow_up": True,
                "missing_slots": unresolved, "prediction": None,
                "context": slots,
            }
        try:
            result = ml_adapter.predict_yield(slots)
            text = t("yield_result", lang,
                     crop=slots.get("crop", "—"),
                     state=slots.get("state_name", "—"),
                     yield_tha=float(result["prediction"]))
            return {"response_text": text + note, "language": lang, "intent": intent,
                    "follow_up": False, "missing_slots": [], "prediction": result}
        except Exception as exc:
            return _error_response(str(exc), lang, intent)

    # ── sensor query ──────────────────────────────────────────────────
    if intent == "sensor_query":
        if not latest_sensor:
            return {"response_text": t("sensor_no_data", lang), "language": lang,
                    "intent": intent, "follow_up": False, "missing_slots": [],
                    "prediction": None}
        ts = latest_sensor.get("created_at", "")
        try:
            from datetime import datetime
            ts = datetime.fromisoformat(ts).strftime("%d %b %H:%M") if ts else "—"
        except Exception:
            ts = "—"
        text = t("sensor_data", lang,
                 time=ts,
                 moisture=f"{latest_sensor.get('soil_moisture', '—')}%",
                 temp=f"{latest_sensor.get('temperature', '—')}°C",
                 humidity=f"{latest_sensor.get('humidity', '—')}%")
        return {"response_text": text, "language": lang, "intent": intent,
                "follow_up": False, "missing_slots": [], "prediction": None}

    # ── navigation / help ─────────────────────────────────────────────
    if intent == "navigation_help":
        return {"response_text": t("nav_help", lang), "language": lang,
                "intent": intent, "follow_up": False, "missing_slots": [],
                "prediction": None}

    # ── unknown ───────────────────────────────────────────────────────
    return {"response_text": t("unknown", lang), "language": lang,
            "intent": "unknown", "follow_up": False, "missing_slots": [],
            "prediction": None}


def _irrigation_crop_label(crop_type: Any) -> str:
    """Display name for the irrigation model's crop input (dataset code or name)."""
    from ml.adapter import IRRIGATION_CROP_CODES

    value = str(crop_type or "Paddy").strip()
    for name, code in IRRIGATION_CROP_CODES.items():
        if value == code:
            return name
    return value


def _error_response(error: str, lang: str, intent: str) -> dict[str, Any]:
    return {
        "response_text": t("model_error", lang, error=error),
        "language": lang, "intent": intent,
        "follow_up": False, "missing_slots": [], "prediction": None,
    }
