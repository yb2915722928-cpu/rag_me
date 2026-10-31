"""Compatibility alias for the canonical media result assembly."""
from importlib import import_module
import sys

sys.modules[__name__] = import_module("..audioTranscriptionAndVideoUnderstanding.assembly", __package__)
