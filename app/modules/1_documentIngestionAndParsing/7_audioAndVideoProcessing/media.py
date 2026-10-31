"""Compatibility alias for the canonical media preparation module."""
from importlib import import_module
import sys

sys.modules[__name__] = import_module("..audioTranscriptionAndVideoUnderstanding.media", __package__)
