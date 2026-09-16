from __future__ import annotations

import streamlit as st

from v5_validation_accuracy import validation_accuracy_tables


def _show_table(frame, *, include_record=False):
    shown = frame.copy()
    if include_record:
        shown["Decided"] = shown["Wins"] + shown["Losses"]
        shown = shown[["Tour", "Wins", "Losses", "Pushes", "Decided", "Accuracy"]]
    st.dataframe(
        shown.style.format({"Accuracy": "{:.2%}"}),
        use_container_width=True,
        hide_index=True,
    )


def render_validation_accuracy_tables():
    tables = validation_accuracy_tables()
    st.divider()
    st.header("Walk-forward validation accuracy")
    st.caption(
        "Frozen validation evidence, separate from live post-reset production settlement. "
        "Spread and total results use one balanced closing consensus observation per match "
        "(median across books), so a match is not multiplied by bookmaker or line rows."
    )

    st.subheader("Match winner")
    _show_table(tables["match_winner"])

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Game spread")
        _show_table(tables["spread"], include_record=True)
    with c2:
        st.subheader("Total games")
        _show_table(tables["total"], include_record=True)
