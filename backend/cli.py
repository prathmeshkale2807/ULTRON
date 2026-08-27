"""
ULTRON Terminal CLI -- Phase 28 Entrypoint Wrapper.

Delegates directly to app.cli.main to ensure all interactions route through
the authenticated REST API, SessionManager, and existing ULTRON security pipeline.
"""

from __future__ import annotations

from app.cli.main import main

if __name__ == "__main__":
    main()

