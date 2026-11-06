"""Manual cost calculation — no API returns cost directly, so we maintain our own table."""

PRICES_PER_MILLION_TOKENS_USD = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int = 0) -> float:
    prices = PRICES_PER_MILLION_TOKENS_USD.get(model)
    if prices is None:
        for known_model in sorted(PRICES_PER_MILLION_TOKENS_USD, key=len, reverse=True):
            if model.startswith(f"{known_model}-"):
                prices = PRICES_PER_MILLION_TOKENS_USD[known_model]
                break
    if prices is None:
        return 0.0
    return (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000
