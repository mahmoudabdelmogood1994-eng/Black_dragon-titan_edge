"""Visualisation: Folium interactive map + Matplotlib figures."""
from __future__ import annotations
from datetime import timedelta
import math
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import folium
from folium import plugins
import satellite_analytics as SAT
from geo import to_latlon

ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"


def ndci_rgba(res):
    idx = res["ind"]["index"]
    norm = np.clip((idx + 0.05) / 0.35, 0, 1)
    rgba = plt.get_cmap("YlOrRd")(np.nan_to_num(norm))
    rgba[..., 3] = np.where(np.isnan(idx), 0.0, 0.75)
    return rgba


def build_map(res) -> folium.Map:
    cfg = res["cfg"]
    m = folium.Map(location=[cfg.plant_lat, cfg.plant_lon], zoom_start=11, tiles=None,
                   control_scale=True)
    folium.TileLayer(ESRI, name="Satellite basemap (Esri)", attr="Esri World Imagery").add_to(m)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)
    if res["scene"] is not None:
        w, s, e, n = SAT.extent(res["scene"])
        name = res["ind"]["index_name"]
        label = f"{name} heatmap" + (" (SYNTHETIC scene)" if res["synthetic"] else "")
        folium.raster_layers.ImageOverlay(ndci_rgba(res), bounds=[[s, w], [n, e]], opacity=0.85,
                                          name=label).add_to(m)
    folium.Marker([cfg.plant_lat, cfg.plant_lon], tooltip=cfg.plant_name,
                  icon=folium.Icon(color="blue", icon="industry", prefix="fa")).add_to(m)
    fg = folium.FeatureGroup("Subsea intake sensors")
    for i, (x, y) in enumerate(cfg.intake_xy_m, 1):
        la, lo = to_latlon(x, y, cfg.plant_lat, cfg.plant_lon)
        folium.CircleMarker([float(la), float(lo)], radius=5, color="#0b3d91", fill=True,
                            fill_opacity=1, tooltip=f"Subsea sensor S{i}").add_to(fg)
    fg.add_to(m)
    fh = folium.FeatureGroup("Hotspots (satellite)")
    for h in res["hotspots"]:
        folium.Circle([h.lat, h.lon], radius=h.radius_km * 1000, color="#c1121f",
                      fill=False, weight=2,
                      popup=f"Hotspot #{h.id}: risk {h.risk_pct:.0f} %, {h.area_km2:.1f} km2, "
                            f"mean {h.index_name} {h.mean_index:.2f}",
                      tooltip=f"#{h.id} risk {h.risk_pct:.0f} %").add_to(fh)
    fh.add_to(m)
    if "air" in res:
        a = res["air"]
        pts = [(float(la), float(lo)) for _, e_, n_ in a["path"]
               for la, lo in [to_latlon(e_, n_, cfg.plant_lat, cfg.plant_lon)]]
        plugins.AntPath(pts, color="#00b4d8", weight=4, delay=900, name="Drone path").add_to(m)
        t0 = res["t_acq"] + timedelta(seconds=res["t_rx"])
        feats = []
        for (t, e_, n_), (la, lo) in zip(a["path"], pts):
            feats.append({"type": "Feature",
                          "geometry": {"type": "Point", "coordinates": [lo, la]},
                          "properties": {"time": (t0 + timedelta(seconds=t)).isoformat(),
                                         "icon": "circle",
                                         "iconstyle": {"fillColor": "#00b4d8", "fillOpacity": 1,
                                                       "stroke": "true", "radius": 7}}})
        plugins.TimestampedGeoJson({"type": "FeatureCollection", "features": feats},
                                   period="PT5S", add_last_point=True, auto_play=False,
                                   loop=False, duration="PT30S", transition_time=120).add_to(m)
        bla, blo = to_latlon(res["bloom_now"][0], res["bloom_now"][1], cfg.plant_lat, cfg.plant_lon)
        folium.Circle([float(bla), float(blo)], radius=res["target"].radius_km * 1000,
                      color="#ff9f1c", dash_array="8", fill=False,
                      tooltip="Bloom position when the drone launched (advected)").add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    return m


def fig_satellite(res):
    if res["scene"] is None:
        return None
    idx = res["ind"]["index"]
    w, s, e, n = SAT.extent(res["scene"])
    fig, ax = plt.subplots(figsize=(6.4, 5.6))
    im = ax.imshow(idx, cmap="YlOrRd", vmin=-0.05, vmax=0.30, extent=(w, e, s, n))
    cfg = res["cfg"]
    ax.plot(cfg.plant_lon, cfg.plant_lat, "b^", ms=10, label="plant")
    for h in res["hotspots"]:
        ax.add_patch(plt.Circle((h.lon, h.lat), h.radius_km / 111.0, fill=False, ec="k", lw=1.5))
        ax.text(h.lon, h.lat, f"#{h.id}", ha="center", va="center", fontsize=9)
    ax.set_title(res["ind"]["index_name"] + (" (SYNTHETIC)" if res["synthetic"] else ""))
    fig.colorbar(im, ax=ax, shrink=0.8)
    ax.legend(loc="lower left")
    fig.tight_layout()
    return fig


def fig_ground(res):
    g = res.get("ground")
    if not g or "sim" not in g:
        return None
    sim, mon = g["sim"], g["mon"]
    t = sim["t"] / 3600
    fig, ax = plt.subplots(3, 1, figsize=(7.5, 7.2), sharex=True)
    ax[0].plot(t, sim["turb"].T, lw=0.6, alpha=0.7)
    ax[0].axhline(res["cfg"].turbidity_limit_ntu, color="r", ls="--", label="threshold")
    ax[0].set_ylabel("turbidity [NTU]"); ax[0].legend(loc="upper left")
    ax[1].plot(t, sim["visc"].mean(axis=0), color="purple")
    ax[1].set_ylabel("viscosity ratio")
    ax[2].plot(t, mon["R"], color="k")
    ax[2].axhline(res["cfg"].plv_threshold, color="r", ls="--")
    ax[2].set_ylabel("phase coherence R"); ax[2].set_xlabel("hours after satellite detection")
    for a in ax:
        if g["t_alarm_s"]:
            a.axvline(g["t_alarm_s"] / 3600, color="g", ls=":")
        a.axvline(g["eta_s"] / 3600, color="orange", ls=":")
    fig.tight_layout()
    return fig
