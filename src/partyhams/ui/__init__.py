"""PySide6 user interface.

Kept out of the package's top-level imports so the headless core (models, contest
engine, networking, persistence) can be imported and tested without Qt installed.
Import from here only from the app entry point.
"""
