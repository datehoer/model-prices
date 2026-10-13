"""Generate New API expressions; prices.json remains a separate legacy contract."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import urllib.request
from urllib.parse import urlsplit

FIELDS = (("prompt", "p"), ("completion", "c"), ("input_cache_read", "cr"),
          ("input_cache_write", "cc"), ("input_cache_write_1h", "cc1h"))
SHARED_INPUT_FIELDS = {"audio": "prompt", "input_audio_cache": "input_cache_read"}


def expression(pricing, model_id=""):
    required = {"prompt", "completion"}
    if "claude" in model_id.lower():
        required.update(field for field, _ in FIELDS)
    if any(field not in pricing or pricing[field] == "" for field in required):
        raise ValueError("missing required token or Claude cache price")
    overrides = pricing.get("overrides", [])
    price_fields = {field for field, _ in FIELDS} | {"audio", "input_audio_cache", "audio_output"}
    conditions = {"min_prompt_tokens", "utc_days", "utc_start", "utc_end"}
    has_time = any(set(item) & {"utc_days", "utc_start", "utc_end"} for item in overrides)
    if has_time and any("min_prompt_tokens" in item for item in overrides):
        raise ValueError("mixed context and time overrides are unsupported")
    if any(set(item) - price_fields - conditions for item in overrides):
        raise ValueError("unsupported pricing override field")
    if not has_time:
        if any("min_prompt_tokens" not in item for item in overrides):
            raise ValueError("missing context threshold")
        overrides = sorted(overrides, key=lambda item: item["min_prompt_tokens"])
    base = {field: pricing[field] for field in price_fields if field in pricing and pricing[field] != ""}
    prices, tests, labels = [base], [], ["standard"]
    days = {name: index for index, name in enumerate(["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"])}
    previous = 0
    for index, item in enumerate(overrides):
        if has_time:
            parts = []
            selected = item.get("utc_days", [])
            if selected:
                if len(set(selected)) != len(selected) or any(day not in days for day in selected):
                    raise ValueError("invalid UTC days")
                parts.append("(" + " || ".join(f'weekday("UTC") == {day}' for day in sorted(days[day] for day in selected)) + ")")
            if "utc_start" in item or "utc_end" in item:
                start, end = item.get("utc_start"), item.get("utc_end")
                if any(type(value) is not int or value < 0 or value > 2359 or value % 100 > 59 for value in [start, end]) or start == end:
                    raise ValueError("invalid UTC interval")
                clock = '(hour("UTC") * 100 + minute("UTC"))'
                joiner = " && " if start < end else " || "
                parts.append(f'({clock} >= {start}{joiner}{clock} < {end})')
            if not parts:
                raise ValueError("empty time condition")
            tests.append(" && ".join(parts))
            labels.append(f"utc_{index + 1}")
            parent = base
        else:
            threshold = item["min_prompt_tokens"]
            if type(threshold) is not int or threshold <= previous or threshold > 2147483647:
                raise ValueError("invalid or duplicate context threshold")
            previous = threshold
            tests.append(f"len < {threshold}")
            labels.append(f"context_{threshold}")
            parent = prices[-1]
        prices.append({**parent, **{field: item[field] for field in price_fields if field in item and item[field] != ""}})
    use_audio = any("audio" in price and Decimal(str(price["audio"])) != Decimal(str(price["prompt"])) for price in prices)
    use_audio_cache = (use_audio and any("input_audio_cache" in price for price in prices)) or any("input_audio_cache" in price and ("input_cache_read" not in price or Decimal(str(price["input_audio_cache"])) != Decimal(str(price["input_cache_read"]))) for price in prices)
    use_audio_output = any("audio_output" in price for price in prices)
    fields = list(FIELDS)
    if use_audio: fields.append(("audio", "ai"))
    if use_audio_cache: fields.append(("input_audio_cache", "ai_cr"))
    if use_audio_output: fields.append(("audio_output", "ao"))
    for field, _ in fields:
        if any(field in price for price in prices) and not all(field in price for price in prices):
            raise ValueError("incomplete category across pricing tiers")
    leaves = []
    for price, label in zip(prices, labels):
        terms = []
        for field, variable in fields:
            if field not in price: continue
            try: value = Decimal(str(price[field]))
            except InvalidOperation as error: raise ValueError("invalid token price") from error
            if not value.is_finite() or value < 0 or value > 1000: raise ValueError("invalid token price")
            literal = format(value * 1000000, "f")
            if "." in literal: literal = literal.rstrip("0").rstrip(".")
            terms.append(f"{variable} * {literal}")
        leaves.append(f'tier("{label}", ' + " + ".join(terms) + ")")
    if has_time:
        result = leaves[0]
        for index in reversed(range(len(tests))): result = f"{tests[index]} ? {leaves[index + 1]} : {result}"
    else:
        result = leaves[-1]
        for index in reversed(range(len(tests))): result = f"{tests[index]} ? {leaves[index]} : {result}"
    return result


def generate(sources, catalog):
    if not isinstance(sources.get("models"), dict) or not sources["models"]:
        raise ValueError("explicit model bindings are required")
    expressions, metadata = {}, {}
    overrides = sources.get("overrides", {})
    for local, source in sorted(sources["models"].items()):
        if not isinstance(local, str) or not local or local.strip() != local:
            raise ValueError("invalid local model ID")
        if not isinstance(source, str) or "/" not in source or source.strip() != source:
            raise ValueError("invalid OpenRouter model ID")
        price = overrides[local] if local in overrides else catalog[source]["pricing"]
        # Claude cache categories are mandatory even for an opaque local alias.
        expressions[local] = expression(price, local + " " + source)
        metadata[local] = {"source": "manual" if local in overrides else "openrouter",
                           "source_model": source, "pricing": price}
    unknown = set(overrides) - set(sources["models"])
    if unknown:
        raise ValueError("override has no explicit model binding")
    contracts = sources.get("contracts", {})
    for local, contract in sorted(contracts.items()):
        if local in expressions or not local or local.strip() != local:
            raise ValueError("invalid or duplicate manual model ID")
        reference = urlsplit(contract.get("source_url", ""))
        if reference.scheme != "https" or not reference.hostname or reference.username:
            raise ValueError("manual contract requires an HTTPS reference")
        if contract.get("unit") not in {"token", "request", "task_usage", "measured"}:
            raise ValueError("invalid manual pricing unit")
        if not isinstance(contract.get("expression"), str) or not contract["expression"].strip():
            raise ValueError("manual contract requires an expression")
        expressions[local] = contract["expression"]
        metadata[local] = {**contract, "source": "official_manual", "source_model": contract.get("source_model", local)}
    return {"schema_version": 2 if contracts else 1, "success": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "units": "Token coefficients: USD per million tokens; fixed/task amounts: USD; OpenRouter source prices: USD per token",
            "data": {"billing_mode": {name: "tiered_expr" for name in expressions},
                     "billing_expr": expressions}, "source_metadata": metadata}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    sources = json.loads((root / "sources.json").read_text())
    if args.catalog:
        raw = json.loads(args.catalog.read_text())
    else:
        with urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=30) as response:
            raw = json.load(response)
    catalog = {}
    for model in raw["data"]:
        if model["id"] in catalog:
            raise ValueError("duplicate upstream model ID")
        catalog[model["id"]] = model
    result = generate(sources, catalog)
    # Complete generation must succeed before replacing the last good artifact.
    target = root / "newapi-pricing.json"
    pending = target.with_suffix(".json.tmp")
    pending.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    pending.replace(target)
    print(f"Generated {len(result['data']['billing_expr'])} complete model prices")


if __name__ == "__main__":
    main()
