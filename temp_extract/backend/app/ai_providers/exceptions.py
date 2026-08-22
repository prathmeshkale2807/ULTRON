"""Exceptions for the AI Provider layer. Callers (ProviderManager, and
later the orchestrator) branch on these types -- never on string matching
of error messages, which could accidentally leak provider error text
containing request details into control flow/logs."""

from __future__ import annotations


class ProviderError(Exception):
    """Base class for all provider-layer failures."""


class ProviderTimeoutError(ProviderError):
    """A provider call exceeded its configured timeout."""


class ProviderUnauthorizedError(ProviderError):
    """Raised when a request's sensitivity tag isn't authorized for the
    provider that would otherwise handle it. This is a policy violation,
    not a transient failure -- ProviderManager never retries or falls
    back past this; it must be looked at, not silently worked around."""


class NoAuthorizedProviderError(ProviderError):
    """No configured provider (primary, fallback, or local) is authorized
    to handle this request's sensitivity tag. Correct behavior is to
    report this to the caller, never to silently downgrade privacy by
    picking an unauthorized provider anyway."""
