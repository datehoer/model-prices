"""Generate New API expressions; prices.json remains a separate legacy contract."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import urllib.request

FIELDS = (("prompt", "p"), ("completion", "c"), ("input_cache_read", "cr"),
          ("input_cache_write", "cc"), ("input_cache_write_1h", "cc1h"))
SHARED_INPUT_FIELDS = {"audio": "prompt", "input_audio_cache": "input_cache_read"}


def expression(pricing, model_id=""):
    required = {"prompt", "completion"}
    if "claude" in model_id.lower():
        required.update(field for field, _ in FIELDS)
    for field in required:
        if field not in pricing or pricing[field] == "":
            raise ValueError(f"missing required price: {field}")
    base = {field: pricing[field] for field, _ in FIELDS
            if field in pricing and pricing[field] != ""}
    overrides = pricing.get("overrides", [])
    supported = {field for field, _ in FIELDS} | set(SHARED_INPUT_FIELDS) | {"min_prompt_tokens"}
    for item in overrides:
        if "min_prompt_tokens" not in item or set(item) - supported:
            raise ValueError("unsupported pricing override; only context thresholds are supported")
    overrides = sorted(overrides, key=lambda item: item["min_prompt_tokens"])
    prices, thresholds = [base], []
    effective = dict(pricing)
    for tier in [pricing, *overrides]:
        effective.update(tier)
        for auxiliary, token_field in SHARED_INPUT_FIELDS.items():
            if auxiliary in effective:
                try:
                    shared = Decimal(str(effective[auxiliary])) == Decimal(str(effective[token_field]))
                except (InvalidOperation, KeyError):
                    shared = False
                if not shared:
                    raise ValueError("separate audio input pricing is not supported")
    for item in overrides:
        threshold = item["min_prompt_tokens"]
        if type(threshold) is not int or threshold <= 0 or threshold > 2147483647:
            raise ValueError("invalid context threshold")
        if thresholds and threshold <= thresholds[-1]:
            raise ValueError("duplicate context threshold")
        thresholds.append(threshold)
        prices.append({**prices[-1], **{field: item[field] for field, _ in FIELDS
                                      if field in item and item[field] != ""}})
    leaves = []
    for index, price in enumerate(prices):
        terms = []
        for field, variable in FIELDS:
            if field not in price:
                continue
            try:
                value = Decimal(str(price[field]))
            except InvalidOperation as error:
                raise ValueError("invalid token price") from error
            if not value.is_finite() or value < 0 or value > 1000:
                raise ValueError("invalid token price")
            literal = format(value * 1000000, "f")
            if "." in literal:
                literal = literal.rstrip("0").rstrip(".")
            terms.append(f"{variable} * {literal}")
        label = "standard" if index == 0 else f"context_{thresholds[index - 1]}"
        leaves.append(f'tier("{label}", ' + " + ".join(terms) + ")")
    result = leaves[-1]
    for index in reversed(range(len(thresholds))):
        result = f"len < {thresholds[index]} ? {leaves[index]} : {result}"
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
    return {"schema_version": 1, "success": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "units": "USD per million tokens in expressions; source prices are USD per token",
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
