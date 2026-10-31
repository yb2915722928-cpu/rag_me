"""Compatibility alias for the canonical handoff implementation."""
from importlib import import_module
import sys

sys.modules[__name__] = import_module("..unifiedDocumentHandoff.hosted_documents", __package__)
