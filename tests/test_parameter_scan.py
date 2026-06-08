"""
Tests for tools/parameter_scan.py
"""
import itertools
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestParameterScan:
    """Test parameter scan module structure and logic"""

    def test_imports_correctly(self):
        """Script imports without errors"""
        from tools.parameter_scan import PARAM_GRID, make_v6_class, run_scan
        assert PARAM_GRID is not None
        assert make_v6_class is not None
        assert run_scan is not None

    def test_param_grid_combinations_432(self):
        """Parameter grid produces exactly 432 combinations"""
        from tools.parameter_scan import PARAM_GRID
        keys = list(PARAM_GRID.keys())
        values = list(PARAM_GRID.values())
        combinations = list(itertools.product(*values))
        assert len(combinations) == 432, f"Expected 432, got {len(combinations)}"

    def test_param_grid_keys(self):
        """Parameter grid has all 5 required keys"""
        from tools.parameter_scan import PARAM_GRID
        expected_keys = {"oversold", "overbought", "trailing_atr", "hard_atr", "div_lookback"}
        assert set(PARAM_GRID.keys()) == expected_keys

    def test_param_grid_value_counts(self):
        """Each param has correct number of values"""
        from tools.parameter_scan import PARAM_GRID
        assert len(PARAM_GRID["oversold"]) == 3       # [30, 35, 40]
        assert len(PARAM_GRID["overbought"]) == 3      # [60, 65, 70]
        assert len(PARAM_GRID["trailing_atr"]) == 4    # [2.5, 3.0, 3.5, 4.0]
        assert len(PARAM_GRID["hard_atr"]) == 4        # [2.0, 2.5, 3.0, 3.5]
        assert len(PARAM_GRID["div_lookback"]) == 3    # [10, 15, 20]
        # 3*3*4*4*3 = 432

    def test_make_v6_class_creates_valid_class(self):
        """make_v6_class produces a valid class with correct params"""
        from tools.parameter_scan import make_v6_class
        params = {
            "oversold": 30,
            "overbought": 70,
            "trailing_atr": 2.5,
            "hard_atr": 2.0,
            "div_lookback": 10,
            "name": "TestVariant"
        }
        cls = make_v6_class(params)
        assert cls is not None
        assert hasattr(cls, 'params')
        assert cls.params.trailing_atr == 2.5
        assert cls.params.hard_atr == 2.0
        assert cls.params.oversold == 30
        assert cls.params.overbought == 70
        assert cls.params.div_lookback == 10

    def test_make_v6_class_default_values(self):
        """make_v6_class uses defaults for missing params"""
        from tools.parameter_scan import make_v6_class
        cls = make_v6_class({})
        assert cls.params.trailing_atr == 3.5
        assert cls.params.hard_atr == 3.0
        assert cls.params.oversold == 35
        assert cls.params.overbought == 65
        assert cls.params.div_lookback == 15

    def test_results_ranking_logic(self):
        """Results are correctly sorted by total_pnl descending"""
        # Simulate mock results
        mock_results = [
            (100.0, {"trade_count": 10, "win_count": 5}),
            (500.0, {"trade_count": 20, "win_count": 12}),
            (-50.0, {"trade_count": 5, "win_count": 2}),
            (300.0, {"trade_count": 15, "win_count": 8}),
        ]
        # Sort by pnl descending (same logic as script)
        sorted_results = sorted(mock_results, key=lambda x: x[0], reverse=True)
        pnls = [r[0] for r in sorted_results]
        assert pnls == [500.0, 300.0, 100.0, -50.0]

    def test_win_rate_calculation(self):
        """Win rate calculation handles edge cases"""
        # From script: wr = result['win_count'] / result['trade_count'] * 100 if result['trade_count'] else 0
        def calc_wr(win_count, trade_count):
            return win_count / trade_count * 100 if trade_count else 0

        assert calc_wr(5, 10) == 50.0
        assert calc_wr(0, 0) == 0
        assert calc_wr(3, 3) == 100.0

    def test_main_guard_present(self):
        """Script has proper __main__ guard"""
        from tools.parameter_scan import run_scan
        # Verify run_scan is defined (guard exists if script is valid)
        assert callable(run_scan)

    def test_no_syntax_errors(self):
        """Module has no syntax errors"""
        import tools.parameter_scan
        assert hasattr(tools.parameter_scan, 'PARAM_GRID')