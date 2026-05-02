# -*- coding: utf-8 -*-
"""
Created on Sat May  2 21:05:27 2026

@author: NATHANAEL
"""

def run_smart_analysis(df, mode="uv"):
    """
    CLEAN API: single entry point for all spectroscopy analysis
    """

    # 1. INPUT VALIDATION
    if df is None or len(df) == 0:
        return {"error": "Empty dataset"}

    x = df.iloc[:, 0].values
    y = df.iloc[:, 1].values

    # 2. PROCESSING
    peak_idx = y.argmax()

    result = {
        "mode": mode,
        "peak_position": float(x[peak_idx]),
        "peak_intensity": float(y[peak_idx]),
        "data_points": len(df)
    }

    # 3. INTERPRETATION LAYER
    if result["peak_position"] > 520:
        result["interpretation"] = "Red shift detected (possible aggregation)"
    else:
        result["interpretation"] = "Blue shift detected (quantum confinement)"

    # 4. OUTPUT (STRICT STRUCTURE)
    return result