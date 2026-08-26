import datetime
import json
import unittest

import pandas as pd

from generate_accuracy_report import (
    classify_quality_level,
    expand_sku_accuracy_rows,
    summarize_accuracy_opportunities,
    summarize_final_rates,
)


class TestGenerateAccuracyReport(unittest.TestCase):
    def test_expand_rows_basic(self):
        run_date = datetime.date(2026, 3, 10)
        spu_rows = pd.DataFrame(
            [
                {
                    "spu": "2141",
                    "run_date": run_date,
                    "winner_algo": "Ensemble_Wgt",
                    "validation_wmape": 0.12,
                    "sku_accuracy_json": json.dumps(
                        {
                            "SKU_A": {"wmape": 0.10, "total_sales": 1000, "weight_in_spu": 0.8},
                            "SKU_B": {"wmape": 0.20, "total_sales": 250, "weight_in_spu": 0.2},
                        },
                        ensure_ascii=False,
                    ),
                }
            ]
        )

        detail_df, summary_df = expand_sku_accuracy_rows(spu_rows)
        self.assertEqual(len(detail_df), 2)
        self.assertEqual(len(summary_df), 1)

        weighted = summary_df.iloc[0]["sku_weighted_wmape"]
        self.assertAlmostEqual(weighted, 0.12, places=6)

    def test_expand_rows_error(self):
        run_date = datetime.date(2026, 3, 10)
        spu_rows = pd.DataFrame(
            [
                {
                    "spu": "2141",
                    "run_date": run_date,
                    "winner_algo": "Ensemble_Wgt",
                    "validation_wmape": 0.12,
                    "sku_accuracy_json": json.dumps({"error": "failed"}, ensure_ascii=False),
                }
            ]
        )

        detail_df, summary_df = expand_sku_accuracy_rows(spu_rows)
        self.assertEqual(len(detail_df), 0)
        self.assertEqual(len(summary_df), 1)
        self.assertEqual(summary_df.iloc[0]["error"], "failed")

    def test_expand_rows_missing_json_marks_gap(self):
        run_date = datetime.date(2026, 3, 10)
        spu_rows = pd.DataFrame(
            [
                {
                    "spu": "2141",
                    "run_date": run_date,
                    "winner_algo": "Ensemble_Wgt",
                    "validation_wmape": 0.18,
                    "training_weeks": 60,
                    "sku_accuracy_json": None,
                }
            ]
        )

        detail_df, summary_df = expand_sku_accuracy_rows(spu_rows)
        self.assertEqual(len(detail_df), 0)
        self.assertEqual(summary_df.iloc[0]["error"], "missing_sku_accuracy")
        self.assertEqual(summary_df.iloc[0]["quality_level"], "warning")
        self.assertEqual(summary_df.iloc[0]["sample_level"], "usable")

    def test_summarize_accuracy_opportunities_marks_sample_and_quality_risks(self):
        run_date = datetime.date(2026, 3, 10)
        spu_rows = pd.DataFrame(
            [
                {
                    "spu": "2141",
                    "run_date": run_date,
                    "winner_algo": "Ensemble_Wgt",
                    "validation_wmape": 0.42,
                    "training_weeks": 18,
                    "sku_accuracy_json": json.dumps(
                        {
                            "SKU_A": {"wmape": 0.35, "total_sales": 1000, "weight_in_spu": 0.8},
                            "SKU_B": {"wmape": 0.70, "total_sales": 250, "weight_in_spu": 0.2},
                        },
                        ensure_ascii=False,
                    ),
                },
                {
                    "spu": "2208",
                    "run_date": run_date,
                    "winner_algo": "Prophet",
                    "validation_wmape": 0.08,
                    "training_weeks": 120,
                    "sku_accuracy_json": json.dumps(
                        {
                            "SKU_X": {"wmape": 0.06, "total_sales": 800, "weight_in_spu": 1.0},
                        },
                        ensure_ascii=False,
                    ),
                },
            ]
        )

        summary_df = summarize_accuracy_opportunities(spu_rows)

        self.assertEqual(list(summary_df["spu"]), ["2141", "2208"])
        self.assertTrue(bool(summary_df.iloc[0]["needs_rule_review"]))
        self.assertEqual(summary_df.iloc[0]["likely_primary_cause"], "sample")
        self.assertEqual(summary_df.iloc[0]["quality_level"], "bad")
        self.assertEqual(summary_df.iloc[0]["recommended_action"], "sample_rule_filter")
        self.assertFalse(bool(summary_df.iloc[0]["is_recommended"]))
        self.assertEqual(summary_df.iloc[1]["likely_primary_cause"], "stable")
        self.assertEqual(summary_df.iloc[1]["recommended_action"], "keep_as_reference")
        self.assertTrue(bool(summary_df.iloc[1]["is_recommended"]))

    def test_summarize_accuracy_opportunities_marks_missing_sku_accuracy_for_backfill(self):
        run_date = datetime.date(2026, 3, 10)
        spu_rows = pd.DataFrame(
            [
                {
                    "spu": "2301",
                    "run_date": run_date,
                    "winner_algo": "Prophet",
                    "validation_wmape": 0.18,
                    "training_weeks": 80,
                    "sku_accuracy_json": None,
                }
            ]
        )

        summary_df = summarize_accuracy_opportunities(spu_rows)

        self.assertEqual(summary_df.iloc[0]["error"], "missing_sku_accuracy")
        self.assertTrue(bool(summary_df.iloc[0]["needs_rule_review"]))
        self.assertEqual(summary_df.iloc[0]["recommended_action"], "backfill_sku_accuracy")

    def test_quality_thresholds_align_with_governance_band(self):
        self.assertEqual(classify_quality_level(0.15), "pass")
        self.assertEqual(classify_quality_level(0.16), "warning")
        self.assertEqual(classify_quality_level(0.30), "warning")
        self.assertEqual(classify_quality_level(0.31), "bad")

    def test_summarize_final_rates_outputs_acceptance_funnel_metrics(self):
        run_date = datetime.date(2026, 3, 10)
        spu_rows = pd.DataFrame(
            [
                {
                    "spu": "2141",
                    "run_date": run_date,
                    "winner_algo": "Ensemble_Wgt",
                    "validation_wmape": 0.12,
                    "training_weeks": 80,
                    "sku_accuracy_json": json.dumps(
                        {"SKU_A": {"wmape": 0.12, "total_sales": 500, "weight_in_spu": 1.0}},
                        ensure_ascii=False,
                    ),
                },
                {
                    "spu": "2208",
                    "run_date": run_date,
                    "winner_algo": "Prophet",
                    "validation_wmape": 0.22,
                    "training_weeks": 120,
                    "sku_accuracy_json": json.dumps(
                        {"SKU_X": {"wmape": 0.22, "total_sales": 400, "weight_in_spu": 1.0}},
                        ensure_ascii=False,
                    ),
                },
                {
                    "spu": "2301",
                    "run_date": run_date,
                    "winner_algo": "Prophet",
                    "validation_wmape": 0.10,
                    "training_weeks": 18,
                    "sku_accuracy_json": json.dumps(
                        {"SKU_Z": {"wmape": 0.10, "total_sales": 300, "weight_in_spu": 1.0}},
                        ensure_ascii=False,
                    ),
                },
                {
                    "spu": "2401",
                    "run_date": run_date,
                    "winner_algo": "ARIMA",
                    "validation_wmape": 0.18,
                    "training_weeks": 60,
                    "sku_accuracy_json": None,
                },
            ]
        )

        metrics = summarize_final_rates(spu_rows)

        self.assertEqual(metrics["total_spu_count"], 4)
        self.assertEqual(metrics["sample_ready_count"], 3)
        self.assertEqual(metrics["sample_error_pass_count"], 1)
        self.assertEqual(metrics["sample_error_fail_count"], 1)
        self.assertAlmostEqual(metrics["sample_rate"], 0.75, places=6)
        self.assertAlmostEqual(metrics["error_pass_rate"], 0.5, places=6)
        self.assertAlmostEqual(metrics["error_fail_rate"], 0.25, places=6)
        self.assertAlmostEqual(metrics["sample_pass_rate"], 0.75, places=6)
        self.assertAlmostEqual(metrics["sample_error_pass_rate"], 1 / 3, places=6)
        self.assertAlmostEqual(metrics["sample_error_fail_rate"], 1 / 3, places=6)
        self.assertAlmostEqual(metrics["high_accuracy_sample_coverage_rate"], 0.25, places=6)
        self.assertAlmostEqual(metrics["algorithm_improvable_coverage_rate"], 0.25, places=6)


if __name__ == "__main__":
    unittest.main()
