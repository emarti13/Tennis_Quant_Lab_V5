import streamlit as st

from results_accuracy_page import render_results_accuracy

st.set_page_config(page_title="V5 Results & Accuracy", layout="wide", page_icon="📊")
render_results_accuracy()
