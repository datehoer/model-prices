# Model prices

`prices.json` is the existing legacy price list. Its schema and values are preserved.

`newapi-pricing.json` is the complete New API expression catalog. Expression coefficients
are USD per million tokens, with separate input, output, cache read, 5-minute cache write
and 1-hour cache write prices. Context tiers use total input length (`len`).

Edit `sources.json` to explicitly map local model IDs to OpenRouter IDs. No aliases are
inferred. Optional `overrides` use the same pricing fields as OpenRouter (USD per token)
and override that model's upstream price. Missing or invalid prices fail the generation;
the last good catalog stays available. Existing unrelated models are not imported.

GitHub Actions refreshes the catalog daily and after source changes; it can also be run
manually. New API's price-source panel links selected local IDs to catalog IDs and saves
version-checked expressions locally. Manual local price edits stop automatic following.
The ordinary upstream-sync panel can also import this URL as a static price source:

https://raw.githubusercontent.com/datehoer/model-prices/main/newapi-pricing.json

Validate locally with `python3 -m unittest discover -s scripts -p 'test_*.py'`, then
run `python3 scripts/update_prices.py`. The original `prices.json` remains independent.
