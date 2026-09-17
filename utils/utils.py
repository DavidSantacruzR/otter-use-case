import json
import logging
import urllib

from constants import MOUNT_MARKER, DEALS_URL

from typing import Any

logger = logging.getLogger(__name__)


def extract_widget_state(html: str) -> dict[str, Any] | None:
    """Pull the JSON argument out of `assets.mountWidget('slot-14', {...})` inside the embedded HTML.

    The payload is minified JSON with nested braces inside strings, so we brace
    match while tracking string/escape state rather than using a regex.
    """
    start = html.find(MOUNT_MARKER)
    if start == -1:
        return None
    brace = html.find("{", start)
    if brace == -1:
        return None

    depth, in_string, escaped = 0, False, False
    for i in range(brace, len(html)):
        ch = html[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[brace : i + 1])
                except json.JSONDecodeError as exc:
                    logger.warning("Widget JSON failed to parse: %s", exc)
                    return None
    return None


def bubble_url(bubble_id: str) -> str:
    return f"{DEALS_URL}?bubble-id={urllib.parse.quote(bubble_id)}"


def refinement_url(field_name: str, value: str) -> str:
    """Build the `discounts-widget` state param Amazon uses for facet filters."""
    state = {"state": {"refinementFilters": {field_name: [value]}}, "version": 1}
    encoded = urllib.parse.quote(json.dumps(state, separators=(",", ":")))
    return f"{DEALS_URL}?discounts-widget={encoded}"


def brand_lookup(state: dict[str, Any]) -> dict[str, str]:
    """brandId -> brand name, harvested from the `brands` refinement facet."""
    out: dict[str, str] = {}
    for refinement in state.get("productSearchResponse", {}).get("refinements", []):
        if refinement.get("id") == "brands":
            for option in refinement.get("options", []):
                brand_id, _, name = str(option.get("value", "")).partition("|")
                if brand_id and name:
                    out[brand_id] = name
    return out
