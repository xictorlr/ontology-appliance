"""Deterministic, read-only source connectors.

Each connector normalizes an operator-provided catalog snapshot into the
repository's source-profile, evidence-index, and snapshot artifact shapes.
Connectors never open a network connection from this package: extraction SQL
is published as documented constants, and the normalizers are pure functions
so CI stays deterministic.
"""
