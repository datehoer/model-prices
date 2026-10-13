import unittest
from update_prices import expression, generate

PRICE = {"prompt": "0.000002", "completion": "0.00001", "input_cache_read": "0.0000001",
         "input_cache_write": "0.0000025", "input_cache_write_1h": "0.000004"}


class PriceContracts(unittest.TestCase):
    def test_all_cache_categories_and_exact_decimal_prices(self):
        self.assertEqual(expression(PRICE), 'tier("standard", p * 2 + c * 10 + cr * 0.1 + cc * 2.5 + cc1h * 4)')

    def test_context_threshold_uses_total_input_and_keeps_explicit_zero(self):
        result = expression({**PRICE, "overrides": [{"min_prompt_tokens": 100000, "prompt": "0.000004", "input_cache_read": "0"}]})
        self.assertTrue(result.startswith('len < 100000 ? tier("standard",'))
        self.assertIn('tier("context_100000", p * 4 + c * 10 + cr * 0 + cc * 2.5 + cc1h * 4)', result)

    def test_incomplete_or_invalid_catalog_cannot_generate_partial_prices(self):
        for value in ["-1", "NaN", "Infinity", "bad"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                expression({**PRICE, "prompt": value})
        with self.assertRaises(ValueError):
            expression({k: v for k, v in PRICE.items() if k != "input_cache_write_1h"}, "claude-opus-5")
        with self.assertRaises(ValueError):
            expression({**PRICE, "overrides": [{"min_prompt_tokens": 100}, {"min_prompt_tokens": 100}]})

    def test_explicit_alias_and_manual_override_take_precedence(self):
        result = generate({"models": {"native": "anthropic/source"}, "overrides": {"native": {**PRICE, "prompt": "0"}}},
                          {"anthropic/source": {"pricing": PRICE}})
        self.assertEqual(set(result["data"]["billing_expr"]), {"native"})
        self.assertIn("p * 0", result["data"]["billing_expr"]["native"])
        self.assertEqual(result["source_metadata"]["native"]["source"], "manual")

    def test_missing_source_does_not_silently_use_another_model(self):
        with self.assertRaises(KeyError):
            generate({"models": {"native": "anthropic/missing"}}, {"anthropic/source": {"pricing": PRICE}})

    def test_non_claude_omits_unpublished_cache_categories(self):
        pricing = {"prompt": "0.000002", "completion": "0.00001", "input_cache_read": "0.0000001"}
        self.assertEqual(expression(pricing, "gpt-6.1-sol"),
                         'tier("standard", p * 2 + c * 10 + cr * 0.1)')
        self.assertEqual(expression({"prompt": "0", "completion": "0"}),
                         'tier("standard", p * 0 + c * 0)')
        for missing in ["prompt", "completion"]:
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                expression({k: v for k, v in pricing.items() if k != missing})

    def test_optional_cache_price_can_start_in_a_context_tier(self):
        pricing = {"prompt": "0.000001", "completion": "0.000002",
                   "overrides": [{"min_prompt_tokens": 100000, "input_cache_read": "0.0000001"}]}
        self.assertEqual(expression(pricing),
                         'len < 100000 ? tier("standard", p * 1 + c * 2) : '
                         'tier("context_100000", p * 1 + c * 2 + cr * 0.1)')

    def test_opaque_claude_alias_requires_complete_cache_prices(self):
        with self.assertRaises(ValueError):
            generate({"models": {"native": "anthropic/claude-opus-5"}},
                     {"anthropic/claude-opus-5": {"pricing": {"prompt": "0", "completion": "0"}}})

    def test_time_or_mixed_condition_overrides_are_not_flattened(self):
        for override in [{"utc_days": ["saturday"], "prompt": "0"},
                         {"min_prompt_tokens": 100000, "utc_start": 100}]:
            with self.subTest(override=override), self.assertRaises(ValueError):
                expression({**PRICE, "overrides": [override]})

    def test_identical_audio_input_rates_share_text_prices(self):
        pricing = {"prompt": "0.000002", "completion": "0.00001", "audio": "0.000002",
                   "input_cache_read": "0.0000001", "input_audio_cache": "0.0000001",
                   "overrides": [{"min_prompt_tokens": 200000, "prompt": "0.000004", "audio": "0.000004"}]}
        self.assertIn('tier("context_200000", p * 4 + c * 10 + cr * 0.1)', expression(pricing))
        with self.assertRaises(ValueError):
            expression({**pricing, "audio": "0.000003"})


if __name__ == "__main__":
    unittest.main()
