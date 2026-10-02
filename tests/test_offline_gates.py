"""Regression checks for offline provider isolation and package exit status."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import factcheck
import run
from backtest import run_backtest
from contracts import Script
from extract import bundled_sample_spec


class OfflineGates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_backtest(bundled_sample_spec(), offline=True)

    def test_bundled_result_is_marked_and_matches_recorded_example(self):
        self.assertTrue(self.result.survivorship_limited)
        self.assertEqual(self.result.data_source, "sample")
        self.assertAlmostEqual(self.result.metrics["sharpe"], 0.83, places=2)
        self.assertAlmostEqual(self.result.metrics["cagr"] * 100, 8.71, places=2)
        self.assertAlmostEqual(self.result.metrics["mdd"] * 100, -23.68, places=2)

    def test_offline_factcheck_does_not_call_provider_even_with_a_key(self):
        script = Script(hook="Historical strategy test", beats=["The measured Sharpe is 0.83."], cta="Read the source.")
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-only"}), patch.object(factcheck, "_llm_pass") as provider:
            passed, failures = factcheck.factcheck(script, self.result, allow_online=False)
        self.assertTrue(passed, failures)
        provider.assert_not_called()

    def test_offline_factcheck_still_rejects_untraceable_numbers(self):
        script = Script(hook="A measured Sharpe of 987.654", beats=[], cta="Read the source.")
        passed, failures = factcheck.factcheck(script, self.result, allow_online=False)
        self.assertFalse(passed)
        self.assertTrue(any("not traceable" in failure for failure in failures))

    def test_package_check_returns_failure_when_qc_rejects_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "out" / "fixture"
            output.mkdir(parents=True)
            for passed in (False, True):
                (output / "meta.json").write_text(json.dumps({"qc_passed": passed}))
                with patch.object(run, "ROOT", root), patch.object(run, "build_reel", return_value="fixture"):
                    self.assertEqual(run.staged_check("package"), 0 if passed else 1)


if __name__ == "__main__":
    unittest.main()
