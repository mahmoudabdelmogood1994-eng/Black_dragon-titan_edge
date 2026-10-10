"""Streamlit dashboard:  streamlit run dashboard.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import pipeline as P
import viz
from config import Config, apply_presets

st.set_page_config(page_title="Titan-Edge Space Twin", layout="wide")
st.title("Titan-Edge  ·  Space → Ground → Air digital twin")

with st.sidebar:
    st.header("Scenario")
    data_dir = st.text_input("Band folder (GeoTIFF B03/B04/B05/B08). Empty = synthetic demo", "")
    sensor = st.selectbox("Sensor", ["sentinel2", "landsat"])
    tan_h5 = st.text_input("Tanager HDF5 (optional, overrides the folder)", "")
    tan_js = st.text_input("Tanager STAC item JSON", "")
    use_presets = st.checkbox("Apply Fujairah + notebook presets (thresholds 0.25 / 0.20)", False)
    thr = st.slider("NDCI hotspot threshold", 0.00, 0.30, 0.10, 0.01)
    speed = st.slider("Current speed (x default 25 cm/s toward the coast)", 0.2, 2.5, 1.0, 0.1)
    lat_h = st.slider("Assumed satellite data latency [h]", 0.5, 12.0, 3.0, 0.5)
    prec = st.slider("Assumed intake precursor amplitude [NTU]", 0.0, 0.5, 0.20, 0.05)
    seed = st.number_input("Random seed", 0, 9999, 7)
    st.caption("Constants marked ASSUMED in config.py are not measurements.")


@st.cache_data(show_spinner="Running SPACE → GROUND → AIR chain …")
def run(data_dir, sensor, thr, speed, lat_h, prec, seed, tan_h5, tan_js, use_presets):
    cfg = Config(sensor=sensor, ndci_threshold=thr, data_latency_h=lat_h, precursor_amp_ntu=prec)
    if use_presets:
        apply_presets(cfg, "fujairah", "tanager" if tan_h5 else "sentinel2_real")
        cfg.sensor = "tanager" if tan_h5 else sensor
        cfg.ndci_threshold = thr
    cfg.current_uv_ms = (cfg.current_uv_ms[0] * speed, cfg.current_uv_ms[1] * speed)
    return P.run_pipeline(cfg, data_dir or None, int(seed), (tan_h5, tan_js) if tan_h5 else None)


try:
    res = run(data_dir, sensor, thr, speed, lat_h, prec, seed, tan_h5, tan_js, use_presets)
except Exception as exc:                       # surface file / band problems clearly
    st.error(f"Pipeline error: {exc}")
    st.stop()

if res["synthetic"]:
    st.warning("SYNTHETIC scene: no real satellite data is loaded. Point the sidebar at a folder "
               "of real GeoTIFF bands to run on real imagery.")
st.caption(f"Index used: **{res['ind']['index_name']}**   ·   status: **{res['status']}**")

if res["status"] == "OK":
    g, a, arr = res["ground"], res["air"], res["arrival"]
    c = st.columns(5)
    c[0].metric("Top hotspot risk", f"{res['target'].risk_pct:.0f} %")
    c[1].metric("Modelled ETA to intake", f"{arr.eta_from_detection_s/3600:.1f} h")
    c[2].metric("Alarm → drone airborne", f"{res['t_rx']-res['t_alarm']+a['t_spin_s']:.1f} s")
    c[3].metric("Recommendation margin", f"{res.get('margin_s', float('nan'))/60:.0f} min")
    c[4].metric("Drone collisions", "yes" if a["collided"] else "none")

t1, t2, t3, t4 = st.tabs(["Map", "Timeline", "Subsea sensors", "Satellite index"])
with t1:
    html = viz.build_map(res).get_root().render()          # our own generated map
    if hasattr(st, "iframe"):
        st.iframe(html, height=680)
    else:                                                   # older Streamlit
        components.html(html, height=680)
    st.caption("Press play on the time slider (bottom-left) to animate the drone from the plant "
               "to the bloom. Layers can be toggled top-right.")
with t2:
    st.dataframe(pd.DataFrame(res["events"])[["utc", "layer", "event"]], hide_index=True)
with t3:
    fig = viz.fig_ground(res)
    st.pyplot(fig) if fig else st.info("No subsea simulation for this scenario.")
with t4:
    st.pyplot(viz.fig_satellite(res))
    st.dataframe(pd.DataFrame([h.__dict__ for h in res["hotspots"]]), hide_index=True)
