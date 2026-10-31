"""Compatibility alias for the canonical video prompts."""
from importlib import import_module
import sys

sys.modules[__name__] = import_module("..audioTranscriptionAndVideoUnderstanding.prompts", __package__)
