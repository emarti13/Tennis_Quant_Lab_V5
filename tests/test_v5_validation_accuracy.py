import pytest

from v5_validation_accuracy import validation_accuracy_tables


def test_validation_tables_preserve_latest_walk_forward_results():
    tables = validation_accuracy_tables()
    assert set(tables) == {"match_winner", "spread", "total"}

    winner = tables["match_winner"].set_index("Tour")
    assert winner.loc["ATP", "Accuracy"] == pytest.approx(.7489)
    assert winner.loc["WTA", "Accuracy"] == pytest.approx(.8038)

    spread = tables["spread"].set_index("Tour")
    assert spread.loc["ATP", ["Wins", "Losses", "Pushes"]].tolist() == [768, 908, 26]
    assert spread.loc["WTA", "Accuracy"] == pytest.approx(.6379)

    total = tables["total"].set_index("Tour")
    assert total.loc["ATP", ["Wins", "Losses", "Pushes"]].tolist() == [621, 748, 21]
    assert total.loc["WTA", "Accuracy"] == pytest.approx(.5083)


def test_spread_and_total_accuracy_is_decided_outcomes_not_pushes():
    tables = validation_accuracy_tables()
    for name in ("spread", "total"):
        for _, row in tables[name].iterrows():
            assert row["Accuracy"] == pytest.approx(row["Wins"] / (row["Wins"] + row["Losses"]), abs=5e-5)
