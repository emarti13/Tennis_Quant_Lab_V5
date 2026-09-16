import streamlit as st

from results_accuracy_page import load_accuracy_ledger, render_results_accuracy
from v5_signal_tracking import render_tracking_tables

st.set_page_config(page_title="V5 Results & Accuracy", layout="wide", page_icon="📊")
render_results_accuracy()
ledger = load_accuracy_ledger()
if not ledger.empty:
    render_tracking_tables(st, ledger, heading="Results Accuracy — market outcomes by tour and signal")
