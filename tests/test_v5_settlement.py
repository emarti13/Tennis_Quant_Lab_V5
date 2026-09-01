import sys, pathlib, unittest
import pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from v5_settlement import parse_score_games, settle_market, match_result_row, settle_ledger

class SettlementTests(unittest.TestCase):
    def test_parse_score_games(self):
        self.assertEqual(parse_score_games('6-4 3-6 7-6(5)'), (16,16))

    def test_moneyline_and_spread_and_total(self):
        result={'winner_name':'Taylor Fritz','loser_name':'Darwin Blanch','score':'6-3 6-4'}
        self.assertEqual(settle_market({'market_group':'moneyline','selection':'Taylor Fritz','line':None,'best_decimal_odds':1.4}, result)['settled_result'],'WIN')
        self.assertEqual(settle_market({'market_group':'game_spread','selection':'Darwin Blanch','line':6.5,'best_decimal_odds':2.0}, result)['settled_result'],'WIN')
        self.assertEqual(settle_market({'market_group':'total_games','selection':'under','line':20.5,'best_decimal_odds':1.9}, result)['settled_result'],'WIN')

    def test_retirement_voids(self):
        result={'winner_name':'A','loser_name':'B','score':'6-2 1-0 RET'}
        out=settle_market({'market_group':'moneyline','selection':'A','line':None,'best_decimal_odds':2.0},result)
        self.assertEqual(out['settled_result'],'VOID')
        self.assertEqual(out['profit_units'],0.0)

    def test_match_result_row_requires_unique_pair(self):
        results=pd.DataFrame([
            {'winner_name':'A','loser_name':'B','tourney_date':20260901,'tourney_name':'US Open','score':'6-4 6-4'},
        ])
        pred={'resolved_player1':'A','resolved_player2':'B','start_time_utc':'2026-09-01T17:00:00Z','tournament':'US Open Men Singles'}
        r=match_result_row(pred,results)
        self.assertEqual(r['winner_name'],'A')

    def test_settle_ledger_is_idempotent(self):
        ledger=pd.DataFrame([{'freeze_key':'x','result_status':'OPEN','resolved_player1':'A','resolved_player2':'B','start_time_utc':'2026-09-01T17:00:00Z','tournament':'US Open Men Singles','market_group':'moneyline','selection':'A','line':None,'best_decimal_odds':2.0}])
        results=pd.DataFrame([{'winner_name':'A','loser_name':'B','tourney_date':20260901,'tourney_name':'US Open','score':'6-4 6-4'}])
        first,_=settle_ledger(ledger,results,settled_at='2026-09-01T20:00:00+00:00')
        second,_=settle_ledger(first,results,settled_at='2026-09-02T20:00:00+00:00')
        self.assertEqual(first.loc[0,'settled_at_utc'], second.loc[0,'settled_at_utc'])
        self.assertEqual(second.loc[0,'settled_result'],'WIN')

if __name__=='__main__': unittest.main()
