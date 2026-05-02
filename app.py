# -*- coding: utf-8 -*-
"""
Created on Sat May  2 20:57:15 2026

@author: NATHANAEL
"""

import streamlit as st
import os
import pandas as pd
import matplotlib.pyplot as plt

import sys
sys.path.append(os.path.dirname(__file__))

from core.smart_analysis import run_smart_analysis

st.set_page_config(page_title="Smart Lab System", layout="wide")

st.title("🧪 Smart Lab Automation Dashboard")

# ----------------------------
# FILE UPLOAD
# ----------------------------
uploaded_file = st.file_uploader("Upload Spectroscopy CSV", type=["csv"])

mode = st.selectbox("Analysis Mode", ["UV-Vis / PL", "Lifetime"])

if uploaded_file:
    df = pd.read_csv(uploaded_file)

    st.subheader("Raw Data")
    st.write(df.head())

    # Plot
    fig, ax = plt.subplots()
    ax.plot(df.iloc[:, 0], df.iloc[:, 1])
    ax.set_xlabel("X")
    ax.set_ylabel("Intensity")
    st.pyplot(fig)

    # Run smart analysis
    if st.button("Run Smart Analysis"):
        results, insights = run_smart_analysis(df, mode="uv")

        st.subheader("🔬 Results")
        st.json(results)

        st.subheader("🧠 Scientific Insight")
        st.write(insights)

# ----------------------------
# LOCAL OUTPUT VIEWER
# ----------------------------
st.divider()
st.subheader("📁 Generated Reports")

report_dir = "outputs/reports"

if os.path.exists(report_dir):
    files = os.listdir(report_dir)
    for f in files:
        st.write(f"📄 {f}")
