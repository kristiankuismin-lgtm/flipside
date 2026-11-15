"""Vercel's Python runtime entry point.

The live demo runs cache-only: every figure on screen comes from what was
already harvested, not from a request-time call that would need the Cala
or Context.dev keys exposed on a public serverless function. Those keys
stay local; this reads the sqlite snapshots shipped alongside the code.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("CALA_CACHE_ONLY", "1")

from app.api import app  # noqa: E402
