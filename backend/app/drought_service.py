"""Drought Management & Water Conservation decision service.

Design principles (the same as farming_service.py):

* **No fabricated numbers.**  Cost figures are text ranges ("₹500–₹2,000"),
  never invented precise values. Yield or rainfall figures come from verified
  sources or from the farmer's own input — never assumed.
* **Transparent decision rules.**  Severity assessment and every category of
  recommendation are built from explicit, documented rules so an operator (or
  expert reviewer) can inspect and update them without touching the LLM.
* **RAG for context, not decisions.**  The RAG pipeline is called once to
  retrieve verified crop- and region-relevant guidance. The retrieved text is
  surfaced to the farmer as advisory context; it does not drive the structured
  recommendations.
* **Weather is live, but forecast rainfall is clearly labelled.**  We use the
  existing Open-Meteo client (app.weather) and always carry the
  ``forecast_note`` that forecasted rain has not fallen yet.
* **Graceful degradation.**  Weather unavailable → assessment proceeds with a
  data-gap note. RAG unavailable → same.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from app import weather as weather_module
from app.weather import WeatherUnavailableError

logger = logging.getLogger("farmiq.drought")


# ---------------------------------------------------------------------------
# Severity thresholds (based on FAO / ICAR guidelines)
# Soil-moisture proxy: use farmer-reported rainfall + water_availability
# ---------------------------------------------------------------------------

_SEVERITY_RULES = [
    # (condition_fn, severity, reason_template)
    (
        lambda ctx: ctx["water_availability"] == "none"
            and (ctx["recent_rainfall_mm"] or 0) < 10,
        "extreme",
        "No water source available and very low recent rainfall (< 10 mm reported).",
    ),
    (
        lambda ctx: ctx["water_availability"] == "none",
        "severe",
        "No irrigation source available. Crop is dependent entirely on rainfall.",
    ),
    (
        lambda ctx: (ctx["recent_rainfall_mm"] or 0) < 20
            and ctx["water_availability"] == "limited",
        "severe",
        "Very low recent rainfall (< 20 mm) with only limited irrigation.",
    ),
    (
        lambda ctx: (ctx["recent_rainfall_mm"] or 0) < 50
            and ctx["water_availability"] in ("none", "limited"),
        "moderate",
        "Below-normal recent rainfall with limited water availability.",
    ),
    (
        lambda ctx: ctx["water_availability"] == "limited",
        "mild",
        "Limited water availability. Monitor crop stress indicators.",
    ),
    (
        lambda ctx: (ctx["recent_rainfall_mm"] or 0) < 50,
        "mild",
        "Below-average recent rainfall. Soil moisture may be depleted.",
    ),
    (
        lambda _: True,  # default
        "none",
        "Current conditions do not indicate drought stress based on supplied data.",
    ),
]


def _assess_severity(ctx: dict[str, Any]) -> tuple[str, str]:
    """Return (severity_level, reason) from farmer-supplied context."""
    for condition, severity, reason in _SEVERITY_RULES:
        try:
            if condition(ctx):
                return severity, reason
        except Exception:  # noqa: BLE001 - malformed ctx key → skip rule
            continue
    return "none", "Unable to determine severity from supplied data."


# ---------------------------------------------------------------------------
# Stage mapping helpers
# ---------------------------------------------------------------------------

_EARLY_STAGES = {"not_yet_sown", "germination", "seedling"}
_CRITICAL_WATER_STAGES = {
    "tillering", "jointing", "heading", "flowering",
    "grain filling", "fruit set", "pod filling", "boll formation",
}


def _is_early_stage(stage: str) -> bool:
    return any(s in stage.lower() for s in _EARLY_STAGES) or stage.lower() == "not_yet_sown"


def _is_critical_stage(stage: str) -> bool:
    return any(s in stage.lower() for s in _CRITICAL_WATER_STAGES)


# ---------------------------------------------------------------------------
# Recommendation builders per category
# ---------------------------------------------------------------------------

def _sowing_recommendations(ctx: dict[str, Any], severity: str) -> list[dict]:
    """Sowing decisions: should the farmer sow, delay, or reconsider?"""
    recs = []
    status = ctx.get("sowing_status", "already_sown")

    if status == "not_yet_sown":
        if severity in ("severe", "extreme"):
            recs.append({
                "action": "Delay sowing until adequate rainfall or irrigation is secured.",
                "reason": (
                    "Sowing under severe water stress risks complete crop failure. "
                    "ICAR recommends a minimum of 50–60 mm reliable moisture before sowing "
                    "most kharif crops."
                ),
                "urgency": "critical",
                "materials": [],
                "estimated_cost_inr": None,
                "expected_benefits": [
                    "Avoids total loss from dry germination",
                    "Preserves seed and input costs",
                ],
                "limitations": [
                    "Delayed sowing may shorten the growing season",
                    "Late sowing window varies by crop and region",
                ],
                "source": "ICAR Contingency Crop Planning Guidelines",
            })
            recs.append({
                "action": "Consider drought-tolerant or short-duration variety if sowing must proceed.",
                "reason": (
                    "Short-duration varieties (70–90 days) can complete their cycle "
                    "within the available moisture window, reducing risk of crop failure."
                ),
                "urgency": "high",
                "materials": ["Short-duration certified seed (region-specific variety)"],
                "estimated_cost_inr": "₹1,500–₹4,000 per acre (seed only; verify locally)",
                "expected_benefits": [
                    "Lower water requirement over shorter crop cycle",
                    "Harvest before monsoon withdrawal",
                ],
                "limitations": [
                    "Yield potential may be lower than full-season varieties",
                    "Variety availability depends on your state agricultural department",
                ],
                "source": "ICAR / State KVK Short-Duration Variety Recommendations",
            })
        elif severity == "moderate":
            recs.append({
                "action": "Sow only if at least 50 mm of rainfall has been received within the past 10 days.",
                "reason": (
                    "Pre-sowing soil moisture is critical for uniform germination. "
                    "Inadequate moisture leads to poor stand establishment."
                ),
                "urgency": "high",
                "materials": ["Moisture meter (optional but useful)"],
                "estimated_cost_inr": None,
                "expected_benefits": ["Uniform germination", "Reduced replanting cost"],
                "limitations": ["Rule of thumb; actual requirement varies by crop and soil type"],
                "source": "ICAR Agronomy Division guidelines",
            })
        else:
            recs.append({
                "action": "Proceed with sowing after confirming adequate soil moisture.",
                "reason": "Current water conditions appear sufficient for sowing.",
                "urgency": "low",
                "materials": [],
                "estimated_cost_inr": None,
                "expected_benefits": ["Timely sowing aligns with optimal growing window"],
                "limitations": ["Monitor early growth for moisture stress symptoms"],
                "source": None,
            })
    else:
        # Already sown
        if severity in ("severe", "extreme"):
            recs.append({
                "action": "Prioritise immediate life-saving irrigation if any water source is available.",
                "reason": (
                    "At severe drought stress, crops show permanent wilting within days. "
                    "Even a small amount of irrigation (10–20 mm) at vegetative stage "
                    "can save the crop stand."
                ),
                "urgency": "critical",
                "materials": ["Any available irrigation equipment"],
                "estimated_cost_inr": "Depends on pump fuel cost; typically ₹300–₹800 per hour of pumping",
                "expected_benefits": ["Prevents permanent wilting and total crop loss"],
                "limitations": [
                    "Effectiveness depends on growth stage",
                    "Water quality should be checked",
                ],
                "source": "ICAR Water Management Division",
            })
        else:
            recs.append({
                "action": "Monitor crop for early water-stress symptoms (rolling/curling leaves, colour change).",
                "reason": "Early detection allows corrective irrigation before permanent damage.",
                "urgency": "moderate" if severity == "moderate" else "low",
                "materials": ["Visual scouting checklist (KVK leaflet)"],
                "estimated_cost_inr": None,
                "expected_benefits": ["Early intervention reduces yield loss"],
                "limitations": ["Visual symptoms may appear 1–2 days after stress onset"],
                "source": None,
            })

    return recs


def _water_conservation_recommendations(ctx: dict[str, Any], severity: str) -> list[dict]:
    """Mulching, harvesting, moisture conservation."""
    recs = []
    soil = ctx.get("soil_type", "").lower()
    crop = ctx.get("crop", "").lower()

    # Mulching — universal recommendation under drought
    recs.append({
        "action": "Apply organic mulch (crop residues, dry grass, or straw) between crop rows.",
        "reason": (
            "Mulching reduces soil-surface evaporation by 25–50%, "
            "lowers soil temperature, and improves water infiltration. "
            "Recommended by ICAR for rainfed and water-stressed fields."
        ),
        "urgency": "high" if severity in ("moderate", "severe", "extreme") else "moderate",
        "materials": [
            "Crop residues (paddy straw, wheat straw, sugarcane trash) — 4–6 t/ha",
            "OR dry grass/leaves — 2–4 t/ha",
        ],
        "estimated_cost_inr": "₹0–₹1,500 per acre if own residues used; verify purchase cost locally",
        "expected_benefits": [
            "25–50% reduction in soil-surface evaporation (ICAR field trials)",
            "Improved soil organic matter over time",
            "Weed suppression",
        ],
        "limitations": [
            "Labour required for spreading (1–2 person-days per acre)",
            "Poorly applied mulch can create pest habitat",
        ],
        "source": "ICAR Research Complex for NEH Region — Mulching Guidelines",
    })

    # Rainwater harvesting — if any rainfall present
    recs.append({
        "action": "Construct or clean farm bunds/field channels to capture and retain any rainfall.",
        "reason": (
            "Even small amounts of rainfall can be conserved through proper bunding. "
            "A 30 cm raised bund can retain 25–40 mm of rainfall runoff."
        ),
        "urgency": "moderate",
        "materials": [
            "Soil and labour for bund construction or repair",
            "Farm pond (if land permits) — consult KVK for MGNREGA support",
        ],
        "estimated_cost_inr": "₹500–₹3,000 per acre for bund repair; farm pond ₹50,000–₹2,00,000 (PMKSY subsidy available)",
        "expected_benefits": [
            "Retains 25–40 mm additional moisture per rainfall event",
            "Reduces soil erosion",
        ],
        "limitations": [
            "Effective only when rainfall occurs",
            "Requires level field or suitable topography",
        ],
        "source": "PMKSY (Pradhan Mantri Krishi Sinchayee Yojana) Guidelines, GoI",
    })

    # Sandy soils lose water fastest — extra advice
    if "sandy" in soil or "loam" in soil:
        recs.append({
            "action": "Apply one dose of well-decomposed farmyard manure (FYM) or compost to improve water-holding capacity.",
            "reason": (
                "Sandy and loamy soils have low water retention. "
                "Adding 5–10 tonnes/ha of FYM improves water-holding capacity by 15–25%."
            ),
            "urgency": "moderate",
            "materials": ["FYM or compost — 5–10 t/ha (2–4 t/acre)"],
            "estimated_cost_inr": "₹500–₹2,500 per acre; own farm compost reduces cost to near-zero",
            "expected_benefits": ["Improved water retention", "Gradual nutrient release"],
            "limitations": ["Benefit is cumulative; one application improves but does not solve sandy-soil drainage"],
            "source": "ICAR Soil Science Division",
        })

    return recs


def _irrigation_management_recommendations(ctx: dict[str, Any], severity: str) -> list[dict]:
    """Prioritise critical stages, practical water-management measures."""
    recs = []
    stage = ctx.get("growth_stage", "").lower()
    irr_type = ctx.get("irrigation_type", "none")
    hours = ctx.get("irrigation_hours_available")
    crop = ctx.get("crop", "").lower()

    is_critical = _is_critical_stage(stage)

    if irr_type in ("borewell", "canal", "drip", "sprinkler", "other"):
        if is_critical:
            recs.append({
                "action": f"Prioritise irrigation at the current critical growth stage ({ctx.get('growth_stage', 'current stage')}).",
                "reason": (
                    "Water stress at reproductive and grain-filling stages causes "
                    "irreversible yield loss (40–60% loss at flowering per ICAR data). "
                    "This stage must be protected first."
                ),
                "urgency": "critical" if severity in ("moderate", "severe", "extreme") else "high",
                "materials": ["Available irrigation source", "Flow meter (optional)"],
                "estimated_cost_inr": "Depends on source; estimate ₹300–₹1,200 per irrigation per acre",
                "expected_benefits": [
                    "Protecting yield at the most sensitive stage",
                    "One well-timed irrigation can offset weeks of dry spell",
                ],
                "limitations": [
                    "Water quality (salinity, pH) affects effectiveness",
                    "Flood irrigation is less efficient than drip/sprinkler",
                ],
                "source": "ICAR Crop Physiology Division — Critical Irrigation Stages",
            })

        if irr_type in ("drip", "sprinkler"):
            recs.append({
                "action": "Use deficit irrigation (apply 60–70% of crop water requirement per cycle).",
                "reason": (
                    "Deficit irrigation maintains acceptable yield while conserving 25–35% "
                    "of water. Effective under drip and sprinkler systems."
                ),
                "urgency": "high" if severity in ("severe", "extreme") else "moderate",
                "materials": ["Drip/sprinkler system (existing)", "Moisture tensiometer (optional)"],
                "estimated_cost_inr": "No additional material cost; saves fuel/electricity",
                "expected_benefits": [
                    "25–35% water saving",
                    "Reduced pumping cost",
                ],
                "limitations": [
                    "Deficit at wrong stage causes yield penalty",
                    "Requires knowledge of crop-water relationships",
                ],
                "source": "ICAR Central Research Institute for Dryland Agriculture (CRIDA)",
            })

        if hours is not None and hours < 4:
            recs.append({
                "action": "Concentrate available irrigation time on the most critical crop rows or zones.",
                "reason": (
                    f"With only ~{hours:.0f} hours/day available, partial irrigation is better than "
                    "uniform under-irrigation. Prioritise seedling rows or the flowering zone."
                ),
                "urgency": "high",
                "materials": [],
                "estimated_cost_inr": None,
                "expected_benefits": ["Saves critical crop patches even under water scarcity"],
                "limitations": ["Partial coverage increases within-field variability"],
                "source": None,
            })
    else:
        # No irrigation — rainfed recommendations
        recs.append({
            "action": "Inter-row tillage (hoeing) after any light rainfall to break soil crust and reduce run-off.",
            "reason": (
                "Light inter-row tillage opens the soil surface to maximise infiltration "
                "from any rainfall event and reduces surface evaporation."
            ),
            "urgency": "moderate",
            "materials": ["Bullock-drawn or tractor cultivator"],
            "estimated_cost_inr": "₹300–₹800 per acre (labour + bullock/tractor)",
            "expected_benefits": [
                "Improved rainfall infiltration",
                "Weed control",
            ],
            "limitations": ["Avoid in standing crops once canopy closes"],
            "source": "ICAR CRIDA — Rainfed Crop Management Handbook",
        })

    return recs


def _crop_alternatives_recommendations(ctx: dict[str, Any], severity: str) -> list[dict]:
    """Suggest alternatives when conditions support it — not speculatively."""
    recs = []
    status = ctx.get("sowing_status", "already_sown")
    crop = ctx.get("crop", "").lower()
    soil = ctx.get("soil_type", "").lower()

    if status == "not_yet_sown" and severity in ("severe", "extreme"):
        recs.append({
            "action": "Consider switching to a drought-tolerant crop such as sorghum (jowar), pearl millet (bajra), or green gram (moong).",
            "reason": (
                "These crops are classified as drought-tolerant by ICAR and state "
                "agricultural universities. They can survive on 300–400 mm seasonal "
                "rainfall and are widely recommended in Maharashtra, Rajasthan, and MP "
                "under deficit rainfall conditions."
            ),
            "urgency": "high",
            "materials": ["Certified seed of drought-tolerant variety (state KVK / APMC)"],
            "estimated_cost_inr": "₹800–₹3,000 per acre (seed only); verify at local input dealer",
            "expected_benefits": [
                "Lower water requirement than rice/sugarcane/cotton",
                "Some crops double as fodder (sorghum, bajra)",
            ],
            "limitations": [
                "Market price for alternate crop must be assessed locally",
                "Variety selection should follow state agricultural department advice",
            ],
            "source": "ICAR CRIDA — Contingency Crop Planning for Drought-Prone Areas",
        })

    elif status != "not_yet_sown" and severity == "extreme":
        recs.append({
            "action": "Assess crop condition; if more than 50% mortality, consider replanting a short-duration crop.",
            "reason": (
                "Replanting is justified only when existing stand falls below 50% of recommended "
                "plant population. A short-duration crop can still yield partially within the season."
            ),
            "urgency": "high",
            "materials": ["Short-duration certified seed", "Consult local KVK / agricultural officer"],
            "estimated_cost_inr": "₹1,500–₹4,000 per acre (seed + replanting labour)",
            "expected_benefits": ["Partial harvest is better than total loss"],
            "limitations": [
                "Replanting cost must be weighed against expected rainfall",
                "Suitable only within the season planting window",
            ],
            "source": "ICAR Contingency Agriculture Recommendations",
        })

    if not recs:
        recs.append({
            "action": "Continue with current crop; evaluate alternatives only if crop mortality exceeds 50%.",
            "reason": "Crop switching is costly and appropriate only under severe, confirmed stress.",
            "urgency": "low",
            "materials": [],
            "estimated_cost_inr": None,
            "expected_benefits": [],
            "limitations": [],
            "source": None,
        })

    return recs


def _dry_spell_management_recommendations(ctx: dict[str, Any], severity: str) -> list[dict]:
    """Crop-stage-specific dry-spell measures."""
    recs = []
    stage = ctx.get("growth_stage", "vegetative").lower()
    crop = ctx.get("crop", "").lower()

    recs.append({
        "action": "Apply foliar spray of 1% potassium chloride (KCl) or 2% urea solution to relieve moisture stress.",
        "reason": (
            "Foliar application compensates for reduced root uptake under water stress. "
            "KCl improves turgor pressure; urea provides an emergency nitrogen supply. "
            "Recommended by ICAR under dry-spell conditions."
        ),
        "urgency": "high" if severity in ("moderate", "severe", "extreme") else "moderate",
        "materials": [
            "Potassium chloride (MOP) — 1 kg per 100 litres water, or",
            "Urea — 2 kg per 100 litres water",
            "Sprayer (knapsack or tractor-mounted)",
        ],
        "estimated_cost_inr": "₹50–₹300 per acre per spray application",
        "expected_benefits": [
            "Temporary relief from moisture stress",
            "Maintains photosynthesis during short dry spells",
        ],
        "limitations": [
            "Effective for short dry spells (5–10 days); cannot substitute for soil-water",
            "Spray in early morning or evening only (avoid midday heat)",
            "Consult KVK before applying if crop shows severe burn symptoms",
        ],
        "source": "ICAR Research Complex — Foliar Spray Recommendations under Drought",
    })

    if _is_critical_stage(stage):
        recs.append({
            "action": "Do not apply additional nitrogen fertiliser during the dry spell.",
            "reason": (
                "Nitrogen fertilisation under water stress causes salt burn and may "
                "worsen crop condition. Defer until soil moisture recovers."
            ),
            "urgency": "high",
            "materials": [],
            "estimated_cost_inr": None,
            "expected_benefits": ["Prevents fertiliser-induced stress"],
            "limitations": ["Nitrogen need resumes after moisture recovery"],
            "source": "ICAR Agronomy Recommendations",
        })

    recs.append({
        "action": "Earthing-up and ridge formation around crop rows to conserve moisture.",
        "reason": (
            "Earthing up increases the soil volume around the root zone and reduces "
            "lateral water loss. Recommended for row crops (maize, sugarcane, cotton)."
        ),
        "urgency": "moderate",
        "materials": ["Tractor-mounted ridger or bullock-drawn ridger"],
        "estimated_cost_inr": "₹400–₹900 per acre",
        "expected_benefits": [
            "Better root-zone water retention",
            "Reduces lodging risk in windy conditions",
        ],
        "limitations": ["Best applied at early vegetative stage; difficult after crop is tall"],
        "source": "ICAR CRIDA",
    })

    return recs


def _financial_planning_recommendations(ctx: dict[str, Any], severity: str) -> list[dict]:
    """Estimated costs, government schemes, and practical financial guidance."""
    recs = []
    budget = ctx.get("budget_inr")

    recs.append({
        "action": "Enquire about PMFBY (Pradhan Mantri Fasal Bima Yojana) crop insurance claim if drought is declared.",
        "reason": (
            "PMFBY covers yield loss due to drought, dry spell, and unseasonal rainfall. "
            "Claims must be filed within 72 hours of crop damage through the nearest bank "
            "or Common Service Centre (CSC)."
        ),
        "urgency": "high" if severity in ("severe", "extreme") else "moderate",
        "materials": ["Kisan Credit Card / loan papers", "Land ownership / tenancy documents"],
        "estimated_cost_inr": "Premium: 1.5–2% of sum insured for kharif crops (subsidy applicable)",
        "expected_benefits": [
            "Partial compensation for crop loss",
            "Reduces financial burden after drought",
        ],
        "limitations": [
            "Cover depends on area-level trigger (yield below threshold)",
            "Claims require timely filing and official drought declaration",
        ],
        "source": "PMFBY Guidelines, Ministry of Agriculture & Farmers Welfare, GoI",
    })

    recs.append({
        "action": "Prioritise spending on water-saving materials (mulch, bund repair) over additional fertiliser.",
        "reason": (
            "Under drought stress, soil moisture is the limiting factor. Fertiliser "
            "applied without adequate moisture provides little benefit and may cause crop damage."
        ),
        "urgency": "moderate",
        "materials": [],
        "estimated_cost_inr": None,
        "expected_benefits": ["Better return on limited budget under water scarcity"],
        "limitations": ["This is general guidance; actual decision depends on crop condition"],
        "source": None,
    })

    if budget is not None and budget < 5000:
        recs.append({
            "action": "Focus on zero-cost or low-cost measures: mulching with on-farm residues, foliar urea spray, and bund repair.",
            "reason": (
                f"With a limited budget of approximately ₹{budget:,.0f}, "
                "on-farm materials provide the highest water-saving benefit per rupee."
            ),
            "urgency": "high",
            "materials": ["On-farm crop residues", "Urea (small quantity)", "Labour"],
            "estimated_cost_inr": "₹200–₹1,500 total for residue mulch + one foliar spray",
            "expected_benefits": ["Maximum benefit within budget constraint"],
            "limitations": ["Scale of intervention limited by available materials"],
            "source": None,
        })

    recs.append({
        "action": "Contact the nearest Krishi Vigyan Kendra (KVK) or Block Agriculture Officer for state-specific drought relief measures.",
        "reason": (
            "State governments announce specific input subsidies, seed distribution, and "
            "relief packages during drought. KVK can also arrange demonstration plots "
            "and technical advice free of charge."
        ),
        "urgency": "moderate",
        "materials": [],
        "estimated_cost_inr": "Free",
        "expected_benefits": ["Access to subsidised inputs, seeds, and technical support"],
        "limitations": ["Availability varies by state and declaration status"],
        "source": "ICAR Krishi Vigyan Kendra Network",
    })

    return recs


# ---------------------------------------------------------------------------
# Category builder
# ---------------------------------------------------------------------------

_CATEGORY_BUILDERS = {
    "sowing_decision": (_sowing_recommendations, "Sowing Decisions"),
    "water_conservation": (_water_conservation_recommendations, "Water Conservation"),
    "irrigation_management": (_irrigation_management_recommendations, "Irrigation Management"),
    "crop_alternatives": (_crop_alternatives_recommendations, "Crop Alternatives"),
    "dry_spell_management": (_dry_spell_management_recommendations, "Dry Spell Management"),
    "financial_planning": (_financial_planning_recommendations, "Financial Planning"),
}

_URGENCY_RANK = {"critical": 0, "high": 1, "moderate": 2, "low": 3}


def _highest_urgency(items: list[dict]) -> str:
    if not items:
        return "low"
    return min(items, key=lambda x: _URGENCY_RANK.get(x.get("urgency", "low"), 3))["urgency"]


def build_categories(ctx: dict[str, Any], severity: str) -> list[dict]:
    categories = []
    for cat_key, (builder_fn, cat_label) in _CATEGORY_BUILDERS.items():
        try:
            items = builder_fn(ctx, severity)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Category builder %s failed: %s", cat_key, exc)
            items = []
        categories.append({
            "category": cat_key,
            "category_label": cat_label,
            "urgency": _highest_urgency(items),
            "items": items,
        })
    return categories


# ---------------------------------------------------------------------------
# Weather fetch helper
# ---------------------------------------------------------------------------

def _fetch_weather_snapshot(location: str) -> dict[str, Any]:
    """Fetch weather from Open-Meteo for the given location.

    Returns a dict that maps to DroughtWeatherSummary. Always returns a dict
    (never raises), with fetch_error populated on failure.
    """
    try:
        geo = weather_module.geocode(location)
        lat, lon = geo["latitude"], geo["longitude"]
        report = weather_module.build_report(lat, lon, place_name=geo.get("name"))

        historical = report.get("historical_rainfall") or {}
        forecast = report.get("forecast_rainfall") or {}
        current = report.get("current") or {}

        return {
            "fetched": True,
            "location_resolved": report.get("location", {}).get("name"),
            "current_temp_c": current.get("temperature_c"),
            "current_humidity_pct": current.get("humidity_pct"),
            "historical_rain_mm": historical.get("total_mm"),
            "historical_days": historical.get("days"),
            "forecast_rain_7d_mm": forecast.get("total_mm"),
            "forecast_note": (
                "Forecast rainfall is not confirmed. Do not act on forecast data alone. "
                "Forecast data from Open-Meteo."
            ),
            "fetch_error": None,
            "data_as_of": report.get("fetched_at"),
        }
    except WeatherUnavailableError as exc:
        logger.info("Weather fetch skipped for drought assessment: %s", exc)
        return {
            "fetched": False,
            "fetch_error": str(exc),
            "forecast_note": "Weather forecast unavailable. Enter rainfall data manually.",
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unexpected weather fetch error: %s", exc)
        return {
            "fetched": False,
            "fetch_error": "Weather data could not be retrieved.",
            "forecast_note": "Weather forecast unavailable. Enter rainfall data manually.",
        }


# ---------------------------------------------------------------------------
# RAG context helper
# ---------------------------------------------------------------------------

def _fetch_rag_context(ctx: dict[str, Any], language: str = "en") -> dict[str, Any]:
    """Retrieve crop- and region-specific drought guidance from the RAG pipeline.

    Returns a dict with ``rag_context``, ``rag_sources``, and ``rag_status``.
    Never raises — a missing RAG pipeline is silently degraded.
    """
    from app import rag_service
    from app.rag_service import RagUnavailableError

    crop = ctx.get("crop", "")
    location = ctx.get("location", "")
    stage = ctx.get("growth_stage", "")
    soil = ctx.get("soil_type", "")

    question = (
        f"Drought management and water conservation recommendations for {crop} "
        f"at {stage} growth stage in {location}. "
        f"Soil type: {soil}. "
        "Include ICAR or state agricultural university guidance on sowing decisions, "
        "mulching, irrigation scheduling, and dry-spell management."
    )

    try:
        result = rag_service.answer_question(question, language=language)
        return {
            "rag_context": result.get("answer") or "",
            "rag_sources": result.get("sources") or [],
            "rag_status": result.get("retrieval_status") or "OK",
        }
    except RagUnavailableError:
        return {
            "rag_context": None,
            "rag_sources": [],
            "rag_status": "unavailable",
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("RAG context fetch failed for drought: %s", exc)
        return {
            "rag_context": None,
            "rag_sources": [],
            "rag_status": "error",
        }


# ---------------------------------------------------------------------------
# Main assessment entry point
# ---------------------------------------------------------------------------

DISCLAIMERS = [
    "These recommendations are based on general agricultural guidelines and the information you provided. "
    "They are not a substitute for advice from a qualified agricultural officer or Krishi Vigyan Kendra (KVK).",
    "Cost estimates are approximate ranges based on typical input prices. "
    "Actual costs vary by region, season, and supplier. Verify locally before purchasing.",
    "Forecast rainfall has not fallen yet and cannot be relied upon for irrigation decisions.",
    "FarmIQ cannot guarantee crop survival, yield recovery, or financial outcomes.",
]


def assess_drought(payload: dict[str, Any]) -> dict[str, Any]:
    """Run the full drought assessment from a validated request payload.

    Parameters
    ----------
    payload:
        Validated dict matching ``DroughtAssessmentRequest``.

    Returns a dict matching ``DroughtAssessmentResponse``.
    """
    ctx = {
        "crop": payload.get("crop", ""),
        "growth_stage": payload.get("growth_stage", ""),
        "location": payload.get("location", ""),
        "soil_type": payload.get("soil_type", ""),
        "area_value": payload.get("area_value", 1.0),
        "area_unit": payload.get("area_unit", "acres"),
        "sowing_status": payload.get("sowing_status", "already_sown"),
        "recent_rainfall_mm": payload.get("recent_rainfall_mm"),
        "water_availability": payload.get("water_availability", "limited"),
        "irrigation_type": payload.get("irrigation_type", "none"),
        "irrigation_hours_available": payload.get("irrigation_hours_available"),
        "budget_inr": payload.get("budget_inr"),
    }

    # 1. Severity assessment
    severity, severity_reason = _assess_severity(ctx)

    # 2. Weather (optional)
    weather_snapshot: dict[str, Any] = {}
    if payload.get("fetch_weather", True) and ctx["location"]:
        weather_snapshot = _fetch_weather_snapshot(ctx["location"])
    else:
        weather_snapshot = {
            "fetched": False,
            "forecast_note": "Weather fetch was not requested.",
        }

    # 3. Structured recommendations
    categories = build_categories(ctx, severity)

    # 4. RAG advisory context — retrieved in the farmer's selected language.
    rag_data = _fetch_rag_context(ctx, language=payload.get("language") or "en")

    # 5. Data gaps
    data_gaps = []
    if ctx["recent_rainfall_mm"] is None:
        data_gaps.append("Recent rainfall not provided — assessment uses water_availability only.")
    if ctx["irrigation_hours_available"] is None:
        data_gaps.append("Irrigation hours not provided — general guidance applied.")
    if ctx.get("budget_inr") is None:
        data_gaps.append("Budget not provided — financial planning guidance is general.")

    now_iso = datetime.now(timezone.utc).isoformat()

    return {
        "crop": ctx["crop"],
        "growth_stage": ctx["growth_stage"],
        "location": ctx["location"],
        "soil_type": ctx["soil_type"],
        "area_value": ctx["area_value"],
        "area_unit": ctx["area_unit"],
        "sowing_status": ctx["sowing_status"],
        "water_availability": ctx["water_availability"],
        "irrigation_type": ctx["irrigation_type"],
        "drought_severity": severity,
        "drought_severity_reason": severity_reason,
        "weather": weather_snapshot,
        "categories": categories,
        "rag_context": rag_data.get("rag_context"),
        "rag_sources": rag_data.get("rag_sources") or [],
        "rag_status": rag_data.get("rag_status", "not_attempted"),
        "disclaimers": DISCLAIMERS,
        "data_gaps": data_gaps,
        "created_at": now_iso,
    }
