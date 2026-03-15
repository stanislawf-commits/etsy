"""
src/shapes/stamp_elements.py — generuje wzory stempla (Claude JSON → Shapely).

Publiczne API:
    plan_stamp(product: dict) -> dict   # Claude → JSON plan wzoru
    build_relief(plan: dict) -> Polygon # JSON plan → Shapely Polygon

TODO: implementacja w Faza 9 Step I
"""

from shapely.geometry import Polygon


def plan_stamp(product: dict) -> dict:
    """
    Wywołuje Claude claude_client.claude_json() i zwraca plan wzoru stempla.

    Args:
        product: dict z polami slug, stamp_topic, base_shape, size_mm, ...

    Returns:
        dict z planem (elementy, rozkład, parametry)
    """
    raise NotImplementedError("stamp_elements.plan_stamp — TODO: Faza 9 Step I")


def build_relief(plan: dict) -> Polygon:
    """
    Buduje Shapely Polygon z JSON planu wzoru stempla.

    Args:
        plan: dict zwrócony przez plan_stamp()

    Returns:
        Polygon gotowy do stamp_scad()
    """
    raise NotImplementedError("stamp_elements.build_relief — TODO: Faza 9 Step I")
