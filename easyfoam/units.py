"""Numbers typed with their units: "50 mm", "2 ft", "3.5 l/s", "0.1 %", "1.2 + 0.3", read into a field's own unit."""

from __future__ import annotations

import ast
import operator
import re

#: unit -> (what it measures, how many of the base unit it is)
UNITS: dict[str, tuple[str, float]] = {
    # lengths, base metre
    "m": ("length", 1.0), "mm": ("length", 1e-3), "cm": ("length", 1e-2), "km": ("length", 1e3),
    "ft": ("length", 0.3048), "in": ("length", 0.0254), "yd": ("length", 0.9144),
    # areas, base square metre
    "m²": ("area", 1.0), "mm²": ("area", 1e-6), "cm²": ("area", 1e-4), "ft²": ("area", 0.09290304),
    "in²": ("area", 6.4516e-4), "ha": ("area", 1e4),
    # discharges, base cubic metre a second
    "m³/s": ("discharge", 1.0), "l/s": ("discharge", 1e-3), "m³/h": ("discharge", 1 / 3600),
    "m³/d": ("discharge", 1 / 86400), "ml/d": ("discharge", 1000 / 86400), "l/min": ("discharge", 1e-3 / 60),
    "cfs": ("discharge", 0.028316846592), "ft³/s": ("discharge", 0.028316846592),
    "gpm": ("discharge", 6.30901964e-5), "mgd": ("discharge", 0.0438126364),
    # speeds, base metre a second
    "m/s": ("speed", 1.0), "cm/s": ("speed", 1e-2), "mm/s": ("speed", 1e-3), "km/h": ("speed", 1 / 3.6),
    "ft/s": ("speed", 0.3048),
    # accelerations
    "m/s²": ("acceleration", 1.0), "ft/s²": ("acceleration", 0.3048),
    # times, base second
    "s": ("time", 1.0), "ms": ("time", 1e-3), "min": ("time", 60.0), "h": ("time", 3600.0),
    "hr": ("time", 3600.0), "d": ("time", 86400.0), "day": ("time", 86400.0), "days": ("time", 86400.0),
    # pressures, base pascal
    "pa": ("pressure", 1.0), "hpa": ("pressure", 100.0), "kpa": ("pressure", 1e3), "mpa": ("pressure", 1e6),
    "bar": ("pressure", 1e5), "mbar": ("pressure", 100.0), "psi": ("pressure", 6894.757293168),
    # densities, base kilogram a cubic metre
    "kg/m³": ("density", 1.0), "g/cm³": ("density", 1000.0), "g/l": ("density", 1.0),
    "lb/ft³": ("density", 16.01846337),
    # kinematic viscosities, base square metre a second
    "m²/s": ("viscosity", 1.0), "mm²/s": ("viscosity", 1e-6), "cst": ("viscosity", 1e-6), "st": ("viscosity", 1e-4),
    # angles, base degree
    "°": ("angle", 1.0), "deg": ("angle", 1.0), "rad": ("angle", 57.29577951308232),
    # slopes and shares, base one
    "m/m": ("ratio", 1.0), "%": ("ratio", 0.01), "‰": ("ratio", 1e-3), "m/km": ("ratio", 1e-3),
    "ft/ft": ("ratio", 1.0),
    # other units fields are labelled with
    "n/m": ("tension", 1.0), "m²/s²": ("kinematic pressure", 1.0), "kg": ("mass", 1.0),
}  # fmt: skip

WHAT = {
    "length": "a length", "area": "an area", "discharge": "a discharge", "speed": "a speed",
    "acceleration": "an acceleration", "time": "a time", "pressure": "a pressure", "density": "a density",
    "viscosity": "a viscosity", "angle": "an angle", "ratio": "a slope or share", "tension": "a surface tension",
    "kinematic pressure": "a kinematic pressure", "mass": "a mass",
}  # fmt: skip

_POWERS = {"^2": "²", "^3": "³", "**2": "²", "**3": "³"}
_OPERATORS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
              ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}  # fmt: skip


def normal_unit(text: str) -> str:
    """A unit as the tables spell it: "m3/s" and "M^3/S" become "m³/s"."""
    unit = text.strip().replace(" ", "").replace("·", "")
    for power, sign in _POWERS.items():
        unit = unit.replace(power, sign)
    unit = re.sub(r"(?<=[a-zA-Z])2(?=/|$)", "²", unit)  # m2, ft2, mm2/s
    unit = re.sub(r"(?<=[a-zA-Z])3(?=/|$)", "³", unit)  # m3/s, ft3/s
    return unit.lower()


def lookup(unit: str) -> tuple[str, float] | None:
    """What a unit measures and its size in the base unit, or None if it is not known."""
    return UNITS.get(normal_unit(unit)) if unit.strip() else None


def _evaluate(text: str) -> float:
    """A number, or arithmetic on numbers ("1.2 + 0.3", "2*0.75"); nothing else is allowed."""

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
            return _OPERATORS[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPERATORS:
            return _OPERATORS[type(node.op)](walk(node.operand))
        raise ValueError

    try:
        value = walk(ast.parse(text.strip(), mode="eval"))
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError, TypeError):
        raise ValueError(f"“{text.strip()}” is not a number") from None
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError(f"“{text.strip()}” is not a finite number")
    return value


def _split(text: str) -> tuple[str, str]:
    """The number part and the unit part of what was typed ("50 mm" -> "50", "mm")."""
    stripped = text.strip()
    candidates = sorted({*UNITS, "m3/s", "ft3/s", "m3/h", "m3/d", "m2", "ft2", "m2/s", "kg/m3"}, key=len, reverse=True)
    lowered = stripped.lower()
    for unit in candidates:
        for spelled in {unit, unit.replace("²", "2").replace("³", "3"), unit.replace("²", "^2").replace("³", "^3")}:
            if lowered.endswith(spelled.lower()):
                number = stripped[: len(stripped) - len(spelled)]
                if number.strip() and (number[-1].isspace() or number[-1].isdigit() or number[-1] in ".)"):
                    return number, stripped[len(number):]
    return stripped, ""


def parse_quantity(text: str, field_unit: str = "") -> tuple[float, str]:
    """Read what was typed into a field measured in ``field_unit``: the value in that unit and a note on any change.

    A comma may stand for the decimal point. Raises ``ValueError`` with the reason when the text cannot be used.
    """
    number, unit = _split(text.replace(",", ".") if "." not in text else text)
    if not unit:
        try:
            return _evaluate(number), ""
        except ValueError:
            trailing = re.match(r"^\s*([-+]?[\d.]+(?:e[-+]?\d+)?)\s*([^\d\s.+\-*/()].*?)\s*$", number, re.IGNORECASE)
            if trailing:  # a number and a word: a unit the tables do not have
                raise ValueError(f"“{trailing.group(2)}” is not a unit EasyFOAM knows") from None
            raise
    value = _evaluate(number)
    typed, field = lookup(unit), lookup(field_unit) if field_unit else None
    if typed is None:
        raise ValueError(f"“{unit.strip()}” is not a unit EasyFOAM knows")
    if field is None:
        raise ValueError("type a plain number here" + (f": this is in {field_unit}" if field_unit else ""))
    if typed[0] != field[0]:
        raise ValueError(f"{unit.strip()} is {WHAT[typed[0]]}, but this is {WHAT[field[0]]} in {field_unit}")
    converted = value * typed[1] / field[1]
    if typed[1] == field[1]:  # the same unit, or another name for it
        return converted, ""
    return converted, f"{number.strip()} {unit.strip()} = {converted:.6g} {field_unit}"


def unit_in_label(label: str) -> str:
    """The unit in a form label such as "End time [s]" (empty if it has none)."""
    found = re.search(r"\[([^\]]+)\]", label)
    return found.group(1).strip() if found else ""
