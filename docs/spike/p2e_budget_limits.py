"""Shared reviewable limits; importing them never loads a Runtime or model client."""

from decimal import Decimal

MAX_CALLS = 7
INPUT_BYTES = 90000
INPUT_TOKEN_BOUND = INPUT_BYTES + 8192
OUTPUT_TOKENS = 1024
PRIOR_OCCUPANCY_USD = Decimal("0.0535860")
RESERVED_USD = (
    Decimal(MAX_CALLS)
    * (Decimal(INPUT_TOKEN_BOUND) * Decimal("0.10") + Decimal(OUTPUT_TOKENS) * Decimal("0.50"))
    / Decimal(1_000_000)
)
