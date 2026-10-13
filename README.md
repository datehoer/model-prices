# Model prices

`prices.json` is the existing legacy price list. Its schema and values are preserved.

`newapi-pricing.json` is the complete New API expression catalog. Expression coefficients
use USD per million tokens for token categories and USD for fixed/request and task usage charges. Input and output prices are required; published cache read
and write prices are included separately. Claude models require cache read, 5-minute
cache write and 1-hour cache write prices. Unpublished optional cache categories are
omitted, never guessed or set to zero. Context tiers use total input length (`len`).
UTC weekday and time-window overrides retain their schedule, including intervals
crossing midnight. Distinct audio input, audio cache and audio output prices use
`ai`, `ai_cr` and `ao`; identical input rates can share the text term. Incomplete
categories across tiers and unsupported override conditions reject generation.

Edit `sources.json` to explicitly map local model IDs to OpenRouter IDs. No aliases are
inferred. Optional `overrides` use the same pricing fields as OpenRouter (USD per token)
and override that model's upstream price. Missing or invalid prices fail the generation;
the last good catalog stays available. Existing unrelated models are not imported.

Verified vendor-specific prices can also be maintained in `sources.json` under
`contracts`. Each explicit local ID requires an `expression`, `unit` (`token`,
`request`, or `task_usage`) and an HTTPS `source_url`. Keep its region, currency,
conversion policy and exceptions in `notes`. This emits schema version 2, supported
by New API's price-source reader alongside version 1. The gateway validates every
expression and checks task expressions against the active plugin's usage schema
when applying a binding. Manual vendor contracts stay versioned in this repository;
daily refresh only fetches OpenRouter prices and never invents missing vendor prices.

GitHub Actions refreshes the catalog daily and after source changes; it can also be run
manually. New API's price-source panel links selected local IDs to catalog IDs and saves
version-checked expressions locally. Manual local price edits stop automatic following.
The ordinary upstream-sync panel can also import this URL as a static price source:

https://raw.githubusercontent.com/datehoer/model-prices/main/newapi-pricing.json

Validate locally with `python3 -m unittest discover -s scripts -p 'test_*.py'`, then
run `python3 scripts/update_prices.py`. The original `prices.json` remains independent.
