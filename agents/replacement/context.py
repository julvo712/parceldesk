"""The pure, intentionally small live-coding surface."""
def build_context(context: dict, order_id: str) -> str:
    return f"Business date: {context['business_date']}. Selected order: {order_id}. Customer: {context['customer_id']}. Resolve this order only. Requested dates must be verified against carrier estimates."
