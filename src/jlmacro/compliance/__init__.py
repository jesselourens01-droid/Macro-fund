"""Compliance and audit logging.

The append-only AuditLogEntry model (jlmacro.models.audit) is introduced in Phase 1;
the logging service that writes structured events through it (jlmacro.utils.audit) is
also introduced in Phase 1 so every later phase can log through it from day one.
"""
