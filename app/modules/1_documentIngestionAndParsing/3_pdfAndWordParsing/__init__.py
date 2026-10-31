"""Compatibility imports for the canonical PDF/DOCX extraction package."""

from importlib import import_module
import sys


_package = import_module("..pdfAndDocxExtraction", __package__)
# The parent alias carries the canonical __path__; register every legacy child
# first so none can execute the canonical source again under its old name.
for _child in ("models", "mineru", "pdf", "docx"):
    sys.modules[f"{__name__}.{_child}"] = import_module(f"{_package.__name__}.{_child}")
sys.modules[f"{__name__}.__init__"] = _package
sys.modules[__name__] = _package
