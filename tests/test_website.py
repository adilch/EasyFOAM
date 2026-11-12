"""The tutorials website: text mark-up, pages, and that docs/ matches the tutorials."""

import ast

import pytest

from website import sitegen
from website.sitegen import Mark, Step, Tutorial, block, inline
from website.tutorials import ALL


def tiny(slug="first", title="First steps", topics=("Basics",)):
    return Tutorial(
        slug=slug, title=title, summary="A *short* one.", minutes=5, level="Beginner", topics=list(topics),
        learn=["one thing"],
        steps=[
            Step("Open it", "Start the program.", screen="Welcome", marks=[Mark("w.a", "Click **New**."), Mark("w.b", "Type `x`.")]),
            Step("Read on", "No picture here.", tip="Keep going."),
        ],
    )  # fmt: skip


# --- text ---------------------------------------------------------------------


def test_inline_markup_and_escaping():
    assert inline("Use **Run** or `F6`, *not* <b>") == "Use <strong>Run</strong> or <code>F6</code>, <em>not</em> &lt;b&gt;"
    assert inline("see [the cavity](cavity.html)") == 'see <a href="cavity.html">the cavity</a>'


def test_blocks_are_paragraphs_lists_and_code():
    html = block("""
One line
continues here.

- first
- second, which
  runs on

```
wsl --install <name>
```
""")
    assert "<p>One line continues here.</p>" in html
    assert "<ul><li>first</li><li>second, which runs on</li></ul>" in html
    assert "<pre><code>wsl --install &lt;name&gt;</code></pre>" in html


# --- pages --------------------------------------------------------------------


def test_a_tutorial_page_numbers_its_steps_and_its_instructions():
    first, second = tiny(), tiny("second", "Second steps")
    page = sitegen.tutorial_page(first, [first, second], {"img/first/01.webp": (800, 500)})
    assert '<section class="step" id="step-1">' in page and '<span class="step-number">2</span>Read on' in page
    assert '<ol class="marks"><li>Click <strong>New</strong>.</li><li>Type <code>x</code>.</li></ol>' in page
    assert '<img src="img/first/01.webp"' in page and 'width="800" height="500"' in page
    assert page.count("<figure>") == 1  # the second step has no picture
    assert '<aside class="tip"><p>Keep going.</p></aside>' in page
    assert 'href="second.html"' in page and "Tutorial 1 of 2" in page
    assert 'href="../assets/site.css"' in page  # pages work from any folder and from a file


def test_the_gallery_lists_every_tutorial_and_offers_each_topic_once():
    page = sitegen.index_page([tiny(), tiny("second", "Second steps", ("Basics", "Waves"))])
    assert page.count('class="card"') == 2 and 'href="tutorials/second.html"' in page
    assert page.count('data-topic="Basics"') == 1 and 'data-topic="Waves"' in page
    assert 'data-topics="Basics|Waves"' in page


def test_writing_the_site_reports_what_changed_and_what_is_missing(tmp_path):
    tutorials = [tiny()]
    written = sitegen.build(tutorials, tmp_path)
    assert {"index.html", "tutorials/first.html", "assets/site.css", "assets/site.js", ".nojekyll"} <= set(written)
    assert sitegen.build(tutorials, tmp_path) == [] and sitegen.out_of_date(tutorials, tmp_path) == []
    assert sitegen.missing_images(tutorials, tmp_path) == ["img/first/cover.webp", "img/first/01.webp"]
    tutorials[0].steps[0].title = "Open the program"
    assert sitegen.out_of_date(tutorials, tmp_path) == ["tutorials/first.html"]


def test_the_spillway_to_download_is_a_closed_solid_of_the_stated_size(tmp_path):
    from easyfoam.geometry import mass_properties
    from easyfoam.model import Shape
    from website.files import CREST, SPILLWAY_X, spillway_profile, spillway_stl

    outline = spillway_profile()
    assert max(z for _x, z in outline) == pytest.approx(CREST)
    assert min(x for x, _z in outline) == pytest.approx(SPILLWAY_X)
    area = 0.5 * sum(xa * zb - xb * za for (xa, za), (xb, zb) in zip(outline, outline[1:] + outline[:1]))
    folder = tmp_path / "constant" / "triSurface"
    folder.mkdir(parents=True)
    (folder / "spillway.stl").write_text(spillway_stl())
    volume, centre, _inertia = mass_properties(Shape("spillway", file="spillway.stl"), tmp_path, 1.0)
    assert volume == pytest.approx(abs(area) * 1.0)  # outline area times its 1 m width: closed, facing outwards
    assert centre[1] == pytest.approx(0.25)


# --- the real tutorials ---------------------------------------------------------


def test_tutorials_are_complete_and_distinct():
    slugs = [t.slug for t in ALL]
    assert len(slugs) == len(set(slugs)) and len(ALL) >= 9
    for tutorial in ALL:
        assert tutorial.level in sitegen.LEVELS and tutorial.topics and tutorial.learn and tutorial.minutes > 0
        assert sum(step.cover for step in tutorial.steps) == 1, f"{tutorial.slug} needs one picture for its card"
        for step in tutorial.steps:
            assert step.title and (step.text or step.marks)
            assert not step.marks or step.screen, f"{tutorial.slug}: '{step.title}' has markers but no picture"
            assert not step.cover or step.screen


def test_every_marker_points_at_something_written_as_valid_python():
    for tutorial in ALL:
        for step in tutorial.steps:
            for mark in step.marks:
                ast.parse(mark.at, mode="eval")
                assert mark.where in ("corner", "left", "right", "top", "centre")
                assert mark.say.strip()


def test_links_between_tutorials_lead_somewhere():
    import re

    from website.files import DOWNLOADS

    pages = {f"{t.slug}.html" for t in ALL} | {name.removeprefix("tutorials/") for name in DOWNLOADS}
    for tutorial in ALL:
        text = tutorial.intro + "".join(step.text + step.tip for step in tutorial.steps)
        for target in re.findall(r"\]\(([^)\s]+)\)", text):
            assert target.startswith("https://") or target in pages, f"{tutorial.slug}: dead link {target}"


def test_the_site_in_docs_matches_the_tutorials():
    """Fails when a tutorial was edited without rebuilding (``python -m website build``) or a picture is missing."""
    if not (sitegen.OUT / "index.html").is_file():
        pytest.skip("the site has not been built in this checkout")
    assert sitegen.out_of_date(ALL) == []
    assert sitegen.missing_images(ALL) == []
