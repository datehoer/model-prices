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
        with self.assertRaises(KeyError):
            expression({k: v for k, v in PRICE.items() if k != "input_cache_write_1h"})
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


if __name__ == "__main__":
    unittest.main()
