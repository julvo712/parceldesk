"""Exact, provenance-backed prices; unlisted models stay unknown."""
from decimal import Decimal, InvalidOperation
from typing import Mapping, Optional

TOKEN_TYPES = ('input', 'output', 'cache_read', 'cache_write')

def money(value) -> Decimal:
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('Invalid monetary value') from exc
    if not result.is_finite() or result < 0:
        raise ValueError('Money must be finite and nonnegative')
    return result

def estimate(usage: Mapping, model: str, catalog: Mapping) -> Optional[Decimal]:
    """Usage input must already exclude cache buckets; never infer vendor semantics."""
    entry = catalog.get('models', {}).get(model)
    if not entry or not entry.get('source_url') or not entry.get('effective_date'):
        return None
    rates = entry.get('usd_per_million', {})
    total = Decimal(0)
    for bucket in TOKEN_TYPES:
        value = usage.get(bucket)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError('Token buckets must be nonnegative integers or null')
        if value and bucket not in rates:
            return None
        total += Decimal(value) * money(rates.get(bucket, 0)) / Decimal(1_000_000)
    return total
