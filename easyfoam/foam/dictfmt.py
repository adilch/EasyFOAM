"""Serialise Python data into OpenFOAM's dictionary file format.

Mapping of Python values:

* ``dict``            -> ``key { ... }`` block (insertion order is kept)
* ``list`` / ``tuple`` -> ``( ... )``; one item per line when the items are
  themselves lists or dictionaries, otherwise inline
* ``bool``            -> ``true`` / ``false``
* ``int`` / ``float`` -> number
* ``str``             -> written verbatim (so ``"Gauss linear"`` or
  ``"uniform (0 0 0)"`` work as-is)
* :class:`Q`          -> a double-quoted string (file names, regex keys)
* :class:`Named`      -> a ``name { ... }`` block inside a list

Keys that start with ``#`` are directives (``#includeEtc``) and get no ``;``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

INDENT = "    "
KEY_WIDTH = 15

BANNER = """\
/*--------------------------------*- C++ -*----------------------------------*\\
| Written by EasyFOAM - edit through the EasyFOAM project where possible.     |
\\*---------------------------------------------------------------------------*/
"""


@dataclass(frozen=True)
class Q:
    """A string that must be written inside double quotes."""

    text: str

    def __str__(self) -> str:
        return '"' + self.text.replace("\\", "\\\\").replace('"', '\\"') + '"'


@dataclass(frozen=True)
class Named:
    """A named dictionary used as a list item (blockMesh ``boundary``, etc.)."""

    name: str
    body: Mapping[str, Any]


def _scalar(value: Any, key: str) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (str, Q)):
        return str(value)
    raise TypeError(f"cannot write value of type {type(value).__name__} for entry '{key}'")


def _is_list(value: Any) -> bool:
    return isinstance(value, (list, tuple))


def _needs_block(items: Any) -> bool:
    """True when a list has to be written one item per line."""
    if not items:
        return False
    if any(isinstance(i, (Mapping, Named)) for i in items):
        return True
    return all(_is_list(i) for i in items)


def _inline(value: Any, key: str) -> str:
    if _is_list(value):
        return "(" + " ".join(_inline(v, key) for v in value) + ")"
    return _scalar(value, key)


def _list_block(items: Any, key: str, pad: str, out: list[str]) -> None:
    out.append(f"{pad}(")
    inner = pad + INDENT
    for item in items:
        if isinstance(item, Named):
            out.append(f"{inner}{item.name}")
            _dict_block(item.body, inner, out)
        elif isinstance(item, Mapping):
            _dict_block(item, inner, out)
        elif _is_list(item) and _needs_block(item):
            _list_block(item, key, inner, out)
        else:
            out.append(f"{inner}{_inline(item, key)}")
    out.append(f"{pad})")


def _dict_block(data: Mapping[str, Any], pad: str, out: list[str]) -> None:
    out.append(f"{pad}{{")
    _entries(data, pad + INDENT, out)
    out.append(f"{pad}}}")


def _entries(data: Mapping[str, Any], pad: str, out: list[str]) -> None:
    for key, value in data.items():
        if key.startswith("#"):
            out.append(f"{pad}{key} {_inline(value, key)}")
        elif isinstance(value, Mapping):
            out.append(f"{pad}{key}")
            _dict_block(value, pad, out)
        elif _is_list(value) and _needs_block(value):
            out.append(f"{pad}{key}")
            _list_block(value, key, pad, out)
            out[-1] += ";"
        else:
            out.append(f"{pad}{key.ljust(KEY_WIDTH)} {_inline(value, key)};")


def dumps(data: Mapping[str, Any]) -> str:
    """Return the body of a dictionary file (no ``FoamFile`` header)."""
    out: list[str] = []
    _entries(data, "", out)
    return "\n".join(out) + "\n"


def foam_file(cls: str, obj: str, data: Mapping[str, Any], *, location: str | None = None) -> str:
    """Return a complete OpenFOAM file: banner, ``FoamFile`` header and body."""
    header: dict[str, Any] = {"version": "2.0", "format": "ascii", "class": cls}
    if location is not None:
        header["location"] = Q(location)
    header["object"] = obj
    return BANNER + dumps({"FoamFile": header}) + "\n" + dumps(data)
