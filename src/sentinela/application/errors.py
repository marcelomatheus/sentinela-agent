"""Typed service errors that must not be mistaken for bad user input."""


class ExtractionFormatError(RuntimeError):
    """The model did not return a valid structured extraction."""
