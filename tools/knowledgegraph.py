"""Checkout-compatible entry point for ontautology_shared.knowledgegraph."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ontautology_shared.knowledgegraph import *  # noqa: E402,F403
from ontautology_shared.knowledgegraph import __all__  # noqa: E402


if __name__ == "__main__":
    from ontautology_shared.knowledgegraph import main
    main()
