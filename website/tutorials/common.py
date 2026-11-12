"""Steps that several tutorials share."""

from website.sitegen import Mark, Step

MESH_BUTTON = Mark("w.mesh_action", "Click **Mesh** in the toolbar (or press **F5**).")
RUN_BUTTON = Mark("w.run_action", "Click **Run** in the toolbar (or press **F6**).")


def from_example(key: str, name: str, card: str) -> list[Step]:
    """The first two steps of a tutorial that starts from a ready-made example."""
    return [
        Step(
            title="Open the example",
            text="""
Start EasyFOAM. This case is one of the examples on the start page: it comes with every setting
filled in, and this tutorial walks through each of them so that you understand the case and could
build it yourself.
""",
            screen="Welcome",
            marks=[Mark(f"w.welcome.example_buttons['{key}']", f"Click **{card}**.")],
        ),
        Step(
            title="Name the project",
            text="The project is an ordinary folder that EasyFOAM creates for you.",
            screen="Dialog",
            before=lambda d: d.show_dialog(key, name),
            marks=[
                Mark("dlg.name", f"Type a name, for example `{name}`."),
                Mark("dlg.ok", "Click **Create project**."),
            ],
        ),
    ]


def create(key: str, name: str):
    """For ``Step.before``: create the project the two steps above describe."""
    return lambda d: d.create(key, name)
