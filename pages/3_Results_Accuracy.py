import streamlit as st

from results_accuracy_page import render_results_accuracy
from v5_validation_accuracy_ui import render_validation_accuracy_tables

st.set_page_config(page_title="V5 Results & Accuracy", layout="wide", page_icon="📊")
render_results_accuracy()
render_validation_accuracy_tables()
