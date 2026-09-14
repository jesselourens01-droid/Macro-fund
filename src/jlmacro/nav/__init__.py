"""NAV engine (Phase 9): computes portfolio NAV, high-water mark and drawdown from
the Trade rows Phase 8 actually persists, and the performance fee that accrues
against that high-water mark. This is what finally gives Phase 6's drawdown governor
a real `current_drawdown` to read instead of one supplied by hand.
"""
