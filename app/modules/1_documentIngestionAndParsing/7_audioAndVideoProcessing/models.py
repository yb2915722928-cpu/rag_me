"""Compatibility alias for the canonical media models."""
from importlib import import_module
import sys

sys.modules[__name__] = import_module("..audioTranscriptionAndVideoUnderstanding.models", __package__)
