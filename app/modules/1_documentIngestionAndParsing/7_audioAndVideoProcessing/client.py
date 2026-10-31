"""Compatibility alias for the canonical media client."""
from importlib import import_module
import sys

sys.modules[__name__] = import_module("..audioTranscriptionAndVideoUnderstanding.client", __package__)
