"""The EasyFOAM tutorials website.

Each tutorial is written once, in ``website/tutorials``. That one description
is used twice: ``website.driver`` operates the real application step by step and
takes the pictures (with numbered markers on the controls), and
``website.sitegen`` writes the pages, so the numbers in a picture always match
the instructions next to it.

    python -m website shots [name ...]   take the pictures (needs OpenFOAM; runs the cases)
    python -m website build              write the pages into docs/
    python -m website check              are the pages in docs/ up to date and complete?
"""
