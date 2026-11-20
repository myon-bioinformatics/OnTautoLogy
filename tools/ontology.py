"""Checkout-compatible entry point for ontautology_shared.ontology."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ontautology_shared.ontology import *  # noqa: E402,F403
from ontautology_shared.ontology import __all__  # noqa: E402
