"""Rendered English for user-facing message keys.

Forecast explanations are owned here; advisory reasons/advice move to strings.yaml
(advisory engine) and keep the same keys.
"""

from backend.schemas import Message

TEXT = {
    "explain.falling.ventilation": "The model expects {pollutant} to fall, mainly because of "
    "better ventilation (stronger winds and a deeper mixing layer).",
    "explain.rising.ventilation": "The model expects {pollutant} to rise, mainly because of "
    "weaker ventilation (calmer winds and a shallower mixing layer).",
    "explain.falling.recent_buildup": "The model expects {pollutant} to fall, mainly because "
    "the recent build-up is easing.",
    "explain.rising.recent_buildup": "The model expects {pollutant} to rise, mainly because "
    "pollution has been building up over the last few hours.",
    "explain.falling.regional_pollution": "The model expects {pollutant} to fall, mainly "
    "because regional pollution levels are expected to drop.",
    "explain.rising.regional_pollution": "The model expects {pollutant} to rise, mainly "
    "because regional pollution levels are expected to increase.",
    "explain.falling.time_of_day": "The model expects {pollutant} to fall, mainly because of "
    "the usual daytime pattern at this location.",
    "explain.rising.time_of_day": "The model expects {pollutant} to rise, mainly because of "
    "the usual evening pattern at this location.",
    "reason.general.satisfactory": "Air quality is {band}. Normal outdoor activity is fine.",
    "reason.exertion.moderately_polluted": "Air quality is {band}. Hard exercise makes you "
    "breathe in much more air, and more pollution with it.",
    "reason.sensitive.very_poor": "Air quality is {band}. People with {condition} are more "
    "affected at this level.",
    "reason.outdoor_worker.very_poor": "Air quality is {band}. Over a long outdoor shift, "
    "exposure at this level adds up.",
    "advice.go_ahead": "Go ahead. Conditions are fine for this activity.",
    "advice.wear_n95": "Wear a well-fitted N95 mask.",
    "advice.lower_intensity": "Consider a lighter pace or a shorter session.",
    "advice.stay_indoors": "Stay indoors and keep windows closed during peak hours.",
    "advice.n95_if_must": "If you must go out, wear a well-fitted N95 mask.",
    "advice.n95_on_shift": "Wear a well-fitted N95 mask throughout the shift.",
    "advice.indoor_breaks": "Take regular breaks indoors or in a cleaner space.",
    "advice.use_best_window": "Plan your {activity} for {start}-{end} IST, when air is "
    "expected to be cleanest.",
    "refresh.accepted": "Refresh started. New data in about a minute.",
    "refresh.rate_limited": "Data was refreshed recently. Try again in {minutes} min.",
}


def message(key: str, **params: str | int | float) -> Message:
    return Message(key=key, params=params, text=TEXT[key].format(**params))
