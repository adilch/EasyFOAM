"""Tutorial descriptions and the pages made from them (no GUI needed here)."""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs"
ASSETS = Path(__file__).resolve().parent / "assets"
SITE_NAME = "EasyFOAM tutorials"
TAGLINE = "Learn flow simulation step by step, with free software and your own OpenFOAM."
LEVELS = ("Beginner", "Intermediate", "Advanced")


@dataclass
class Mark:
    """One numbered marker in a picture, with the instruction that goes with it."""

    at: str  # where: a Python expression for the driver, e.g. "w.mesh_panel.generate"
    say: str  # what to do there
    where: str = "corner"  # where on the control the marker sits: corner (top left), left, right, top or centre


@dataclass
class Step:
    title: str
    text: str = ""
    marks: list[Mark] = field(default_factory=list)
    screen: str = ""  # what the picture shows: "", "Welcome", "Dialog" or a workflow step
    tab: str = ""  # bottom tab to show in the picture
    before: Callable | None = None  # called with the driver before the picture is taken
    tip: str = ""
    crop: str = "window"  # window | left (steps and panel) | right (3D view and plots)
    cover: bool = False  # also save the 3D view of this picture as the tutorial's card image


@dataclass
class Tutorial:
    slug: str
    title: str
    summary: str
    minutes: int
    level: str
    topics: list[str]
    learn: list[str]
    steps: list[Step]
    intro: str = ""
    run_time: str = ""  # how long the computer works, in words

    def image(self, number: int) -> str:
        return f"img/{self.slug}/{number:02d}.webp"

    @property
    def cover(self) -> str:
        return f"img/{self.slug}/cover.webp"


# --- text ---------------------------------------------------------------------

_INLINE = (
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
    (re.compile(r"\*\*([^*]+)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"\*([^*]+)\*"), r"<em>\1</em>"),
    (re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)"), r'<a href="\2">\1</a>'),
)


def inline(text: str) -> str:
    """``**bold**``, ``*emphasis*``, `` `code` `` and ``[links](url)`` in a line of text."""
    out = html.escape(text, quote=False)
    for pattern, replacement in _INLINE:
        out = pattern.sub(replacement, out)
    return out


def block(text: str) -> str:
    """Paragraphs, ``- `` lists and fenced code blocks, separated by blank lines."""
    out: list[str] = []
    lines = text.strip("\n").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
        elif line.startswith("```"):
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            indent = min((len(c) - len(c.lstrip()) for c in code if c.strip()), default=0)
            body = "\n".join(html.escape(c[indent:], quote=False) for c in code)
            out.append(f"<pre><code>{body}</code></pre>")
        elif line.startswith("- "):
            items = []
            while i < len(lines) and lines[i].strip().startswith("- "):
                items.append(lines[i].strip()[2:])
                i += 1
                while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith(("- ", "```")):
                    items[-1] += " " + lines[i].strip()
                    i += 1
            out.append("<ul>" + "".join(f"<li>{inline(item)}</li>" for item in items) + "</ul>")
        else:
            words = []
            while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith(("- ", "```")):
                words.append(lines[i].strip())
                i += 1
            out.append(f"<p>{inline(' '.join(words))}</p>")
    return "\n".join(out)


# --- pages --------------------------------------------------------------------

LOGO = (
    '<svg class="logo" viewBox="0 0 64 64" aria-hidden="true"><rect width="64" height="64" rx="14"/>'
    '<circle cx="25" cy="32" r="8"/><path d="M8 15h14c11 0 13 7 23 7h11M8 49h14c11 0 13-7 23-7h11M41 32h15"/></svg>'
)
FOOT = (
    "EasyFOAM is free software (GPL-3.0-or-later). It is an independent project: it is not approved or "
    "endorsed by OpenCFD Limited, producer and distributor of the OpenFOAM software via www.openfoam.com "
    "and owner of the OPENFOAM® and OpenCFD® trade marks, and it is not affiliated with any other "
    "vendor of simulation software."
)


def _page(title: str, description: str, body: str, root: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(description, quote=True)}">
<link rel="stylesheet" href="{root}assets/site.css">
<link rel="icon" href="{root}assets/icon.svg" type="image/svg+xml">
</head>
<body>
<header class="top">
  <a class="brand" href="{root}index.html">{LOGO}<span>EasyFOAM</span><span class="brand-sub">tutorials</span></a>
  <nav>
    <a href="{root}index.html">All tutorials</a>
    <a href="{root}tutorials/getting-started.html">Install</a>
  </nav>
</header>
{body}
<footer class="foot">
  <p>{FOOT}</p>
</footer>
<script src="{root}assets/site.js"></script>
</body>
</html>
"""


def _chips(tutorial: Tutorial) -> str:
    time = f'<span class="chip">about {tutorial.minutes} min</span>'
    level = f'<span class="chip level-{tutorial.level.lower()}">{tutorial.level}</span>'
    topics = "".join(f'<span class="chip topic">{html.escape(t)}</span>' for t in tutorial.topics)
    return time + level + topics


def index_page(tutorials: list[Tutorial]) -> str:
    topics: list[str] = []
    for tutorial in tutorials:
        topics += [t for t in tutorial.topics if t not in topics]
    filters = '<button class="filter on" data-topic="">All</button>' + "".join(
        f'<button class="filter" data-topic="{html.escape(t, quote=True)}">{html.escape(t)}</button>' for t in topics
    )
    cards = []
    for number, tutorial in enumerate(tutorials, start=1):
        cards.append(
            f'<a class="card" href="tutorials/{tutorial.slug}.html" '
            f'data-topics="{html.escape("|".join(tutorial.topics), quote=True)}">'
            f'<img src="tutorials/{tutorial.cover}" alt="" loading="lazy" width="640" height="400">'
            f'<div class="card-body"><span class="card-number">{number}</span>'
            f"<h2>{html.escape(tutorial.title)}</h2><p>{inline(tutorial.summary)}</p>"
            f'<div class="chips">{_chips(tutorial)}</div></div></a>'
        )
    body = f"""<section class="hero">
  <h1>{SITE_NAME}</h1>
  <p>{TAGLINE}</p>
  <p class="hero-sub">Every tutorial is a complete case: each click is numbered in a picture of the real
  program, and every number you type is given. Start at the top if you are new; they get harder as they go.</p>
</section>
<main class="gallery">
  <div class="filters" role="group" aria-label="Show tutorials about">{filters}</div>
  <div class="cards">
{chr(10).join(cards)}
  </div>
  <p class="empty" hidden>No tutorial on that topic yet.</p>
</main>"""
    return _page(SITE_NAME, TAGLINE, body, "")


def tutorial_page(tutorial: Tutorial, tutorials: list[Tutorial], image_sizes: dict[str, tuple[int, int]]) -> str:
    position = tutorials.index(tutorial)
    contents = []
    sections = []
    for number, step in enumerate(tutorial.steps, start=1):
        contents.append(f'<li><a href="#step-{number}">{html.escape(step.title)}</a></li>')
        parts = [f'<h2><span class="step-number">{number}</span>{html.escape(step.title)}</h2>']
        if step.text:
            parts.append(block(step.text))
        if step.marks:
            items = "".join(f"<li>{inline(mark.say)}</li>" for mark in step.marks)
            parts.append(f'<ol class="marks">{items}</ol>')
        if step.screen:
            src = tutorial.image(number)
            size = image_sizes.get(src)
            dims = f' width="{size[0]}" height="{size[1]}"' if size else ""
            alt = html.escape(f"{tutorial.title}, step {number}: {step.title}", quote=True)
            parts.append(
                f'<figure><a href="{src}" class="zoom"><img src="{src}" alt="{alt}" loading="lazy"{dims}></a></figure>'
            )
        if step.tip:
            parts.append(f'<aside class="tip">{block(step.tip)}</aside>')
        sections.append(f'<section class="step" id="step-{number}">\n' + "\n".join(parts) + "\n</section>")

    learn = "".join(f"<li>{inline(item)}</li>" for item in tutorial.learn)
    run_time = f"<p class=\"run-time\">Computer time: {inline(tutorial.run_time)}</p>" if tutorial.run_time else ""
    links = []
    if position > 0:
        earlier = tutorials[position - 1]
        links.append(f'<a class="prev" href="{earlier.slug}.html"><span>Previous</span>{html.escape(earlier.title)}</a>')
    else:
        links.append("<span></span>")
    if position + 1 < len(tutorials):
        later = tutorials[position + 1]
        links.append(f'<a class="next" href="{later.slug}.html"><span>Next</span>{html.escape(later.title)}</a>')
    body = f"""<div class="layout">
<aside class="contents">
  <a class="back" href="../index.html">← All tutorials</a>
  <p class="contents-title">Steps</p>
  <ol>
{chr(10).join(contents)}
  </ol>
</aside>
<main class="tutorial">
  <p class="crumb">Tutorial {position + 1} of {len(tutorials)}</p>
  <h1>{html.escape(tutorial.title)}</h1>
  <p class="lead">{inline(tutorial.summary)}</p>
  <div class="chips">{_chips(tutorial)}</div>
  {block(tutorial.intro)}
  <div class="learn"><h3>What you will learn</h3><ul>{learn}</ul>{run_time}</div>
{chr(10).join(sections)}
  <nav class="pager">{"".join(links)}</nav>
</main>
</div>
<div class="lightbox" hidden><img alt=""></div>"""
    return _page(f"{tutorial.title} — {SITE_NAME}", tutorial.summary, body, "../")


def image_sizes(tutorials: list[Tutorial], out: Path = OUT) -> dict[str, tuple[int, int]]:
    """Pixel sizes of the pictures that exist, so pages reserve their space while loading."""
    try:
        from PIL import Image
    except ImportError:
        return {}
    sizes = {}
    for tutorial in tutorials:
        for number, step in enumerate(tutorial.steps, start=1):
            path = out / "tutorials" / tutorial.image(number)
            if step.screen and path.is_file():
                with Image.open(path) as picture:
                    sizes[tutorial.image(number)] = picture.size
    return sizes


def pages(tutorials: list[Tutorial], out: Path = OUT) -> dict[str, str]:
    """Every file of the site that is text: path relative to ``out`` -> content."""
    sizes = image_sizes(tutorials, out)
    files = {"index.html": index_page(tutorials), ".nojekyll": ""}
    for tutorial in tutorials:
        files[f"tutorials/{tutorial.slug}.html"] = tutorial_page(tutorial, tutorials, sizes)
    files["tutorials/index.json"] = steps_index(tutorials)
    for asset in sorted(ASSETS.iterdir()):
        if asset.suffix in (".css", ".js", ".svg"):
            files[f"assets/{asset.name}"] = asset.read_text(encoding="utf-8")
    from website.files import DOWNLOADS

    for name, make in DOWNLOADS.items():
        files[name] = make()
    return files


def steps_index(tutorials: list[Tutorial]) -> str:
    """For the help button of the program: each tutorial, and the first of its steps that shows each workflow step."""
    entries = []
    for tutorial in tutorials:
        screens: dict[str, int] = {}
        for number, step in enumerate(tutorial.steps, start=1):
            if step.screen and step.screen not in ("Welcome", "Dialog"):
                screens.setdefault(step.screen, number)
        entries.append({"slug": tutorial.slug, "title": tutorial.title, "topics": tutorial.topics, "steps": screens})
    return json.dumps(entries, indent=1, ensure_ascii=False) + "\n"


def missing_images(tutorials: list[Tutorial], out: Path = OUT) -> list[str]:
    wanted = []
    for tutorial in tutorials:
        wanted.append(tutorial.cover)
        wanted += [tutorial.image(n) for n, step in enumerate(tutorial.steps, start=1) if step.screen]
    return [name for name in wanted if not (out / "tutorials" / name).is_file()]


def build(tutorials: list[Tutorial], out: Path = OUT) -> list[str]:
    """Write the pages; returns the paths that changed."""
    changed = []
    for name, content in pages(tutorials, out).items():
        path = out / name
        if not path.is_file() or path.read_text(encoding="utf-8") != content:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
            changed.append(name)
    return changed


def out_of_date(tutorials: list[Tutorial], out: Path = OUT) -> list[str]:
    """Pages in ``out`` that differ from what the tutorials say now."""
    stale = []
    for name, content in pages(tutorials, out).items():
        path = out / name
        if not path.is_file() or path.read_text(encoding="utf-8") != content:
            stale.append(name)
    return stale
