import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataclasses import dataclass

@dataclass
class MockCandle:
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float

class MockBridge:
    def __init__(self, candles=None):
        self._candles = candles or []

    def connect(self): return True
    def disconnect(self): pass

    def get_account_info(self):
        from core.bridge import AccountInfo
        return AccountInfo(login=123456, balance=10000.0, equity=10000.0, margin=100.0, free_margin=9900.0, currency='USD', leverage=100)

    def get_positions(self, symbol=None): return []
    def get_candles(self, symbol, timeframe, count, offset=0): return self._candles
    def get_tick_price(self, symbol): return (2000.0, 2000.5)
    def close_position(self, ticket, lots=0.0): return True
    def open_position(self, order_type, symbol, volume, price, sl=0.0, tp=0.0, magic=0, comment=''): return 12345

def test_module_import():
    from strategies.v6_hybrid import V6HybridStrategy
    print('[test_module_import] PASS: V6HybridStrategy imported')
    return V6HybridStrategy

def test_class_attributes(V6HybridStrategy):
    assert V6HybridStrategy.name == 'H1_v6_hybrid'
    print('[test_class_attributes] PASS: name = H1_v6_hybrid')

def test_instantiation_empty():
    from strategies.v6_hybrid import V6HybridStrategy
    bridge = MockBridge(candles=[])
    strategy = V6HybridStrategy(bridge=bridge, magic=666666, timeframe='H1')
    assert strategy is not None
    assert strategy.name == 'H1_v6_hybrid'
    assert strategy.magic == 666666
    assert strategy.timeframe == 'H1'
    assert strategy.candles == []
    assert strategy.oversold == 30
    assert strategy.overbought == 65
    assert strategy.p_trailing_atr == 4.0
    assert strategy.p_hard_atr == 2.0
    print('[test_instantiation_empty] PASS: instantiation successful with correct params')

def test_strategy_map():
    from main import STRATEGY_MAP
    assert 'H1_v6_hybrid' in STRATEGY_MAP
    name = STRATEGY_MAP['H1_v6_hybrid'].__name__
    print('[test_strategy_map] PASS: STRATEGY_MAP contains H1_v6_hybrid -> ' + name)

def test_settings_pool():
    from config import settings
    assert hasattr(settings, 'STRATEGY_POOL')
    assert 'H1_v6_hybrid' in settings.STRATEGY_POOL
    config = settings.STRATEGY_POOL['H1_v6_hybrid']
    assert config['magic'] == 666666
    assert config['timeframe'] == 'H1'
    print('[test_settings_pool] PASS: STRATEGY_POOL[H1_v6_hybrid] config correct')

def test_public_methods(V6HybridStrategy):
    required = ['generate_signal', 'get_dynamic_sl_tp', 'check_ema20_exit']
    for m in required:
        assert hasattr(V6HybridStrategy, m)
    print('[test_public_methods] PASS: all public methods exist: ' + str(required))

def test_indicator_methods(V6HybridStrategy):
    indicators = ['_calc_sma', '_calc_ema', '_calc_stoch', '_calc_rsi', '_calc_macd',
                  '_calc_bb_levels', '_calc_atr', '_calc_atr_values', '_calc_atr_sma',
                  '_calc_keltner', '_check_bottom_divergence', '_check_top_divergence']
    for m in indicators:
        assert hasattr(V6HybridStrategy, m), 'Missing: ' + m
    print('[test_indicator_methods] PASS: all ' + str(len(indicators)) + ' indicator methods exist')

def test_signal_no_data():
    from strategies.v6_hybrid import V6HybridStrategy
    bridge = MockBridge(candles=[])
    strategy = V6HybridStrategy(bridge=bridge, magic=666666, timeframe='H1')
    assert strategy.generate_signal() is None
    print('[test_signal_no_data] PASS: empty data returns None')

def test_signal_insufficient_candles():
    from strategies.v6_hybrid import V6HybridStrategy
    candles = [MockCandle('t' + str(i), 2000.0, 2002.0, 1998.0, 2001.0, 100.0) for i in range(249)]
    bridge = MockBridge(candles=candles)
    strategy = V6HybridStrategy(bridge=bridge, magic=666666, timeframe='H1')
    assert strategy.generate_signal() is None
    print('[test_signal_insufficient_candles] PASS: 249 candles returns None')

def test_dynamic_sl_tp():
    from strategies.v6_hybrid import V6HybridStrategy
    from core.bridge import OrderType
    candles = [MockCandle('t' + str(i), 2000.0, 2005.0, 1995.0, 2002.0, 100.0) for i in range(300)]
    bridge = MockBridge(candles=candles)
    strategy = V6HybridStrategy(bridge=bridge, magic=666666, timeframe='H1')
    entry = 2000.0
    sl, tp = strategy.get_dynamic_sl_tp(OrderType.BUY, entry)
    assert sl < entry
    assert tp > entry
    print('[test_dynamic_sl_tp] PASS: BUY SL=' + str(sl) + ', TP=' + str(tp))

def test_check_exit():
    from strategies.v6_hybrid import V6HybridStrategy
    candles = [MockCandle('t' + str(i), 2000.0, 2005.0, 1995.0, 2002.0, 100.0) for i in range(300)]
    bridge = MockBridge(candles=candles)
    strategy = V6HybridStrategy(bridge=bridge, magic=666666, timeframe='H1')
    class MockPos:
        ticket = 12345
        order_type = 'OP_BUY'
        open_price = 2000.0
    result = strategy.check_ema20_exit(MockPos(), bid=2000.0, ask=2000.5)
    assert isinstance(result, bool)
    print('[test_check_exit] PASS: returns ' + str(result) + ' (bool)')

print('')
print('='*60)
print('V6 Hybrid Strategy Test Suite')
print('='*60)
print('')

passed = 0
failed = 0

try:
    VS = test_module_import()
    passed += 1
    test_class_attributes(VS)
    passed += 1
    test_instantiation_empty()
    passed += 1
    test_strategy_map()
    passed += 1
    test_settings_pool()
    passed += 1
    test_public_methods(VS)
    passed += 1
    test_indicator_methods(VS)
    passed += 1
    test_signal_no_data()
    passed += 1
    test_signal_insufficient_candles()
    passed += 1
    test_dynamic_sl_tp()
    passed += 1
    test_check_exit()
    passed += 1
except Exception as e:
    failed = 1
    print('')
    print('FAIL: ' + str(e))
    import traceback
    traceback.print_exc()

total = passed + failed
status = 'PASS' if failed == 0 else 'FAIL'
print('')
print('='*60)
print('RESULT: ' + status + ' (' + str(passed) + '/' + str(total) + ' passed)')
print('='*60)
print('')
sys.exit(0 if failed == 0 else 1)
