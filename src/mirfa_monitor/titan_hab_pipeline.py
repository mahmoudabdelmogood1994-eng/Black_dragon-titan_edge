#!/usr/bin/env python3
"""
Titan Edge - HAB (NDCI) screening pipeline, v2 (corrected).

What changed vs v1
------------------
1. AOI VALIDATION: the intake point must lie inside the bbox, otherwise the run
   fails loudly (v1 labelled an Abu Dhabi/Tarif bbox as "Fujairah" with an intake
   300+ km outside it).
2. CLEAN WATER MASK: NDWI + NIR ceiling, small water bodies removed, shoreline
   eroded (v1 flagged mostly shoreline / shallow-bottom pixels).
3. ONE UNIFIED RULE for every sensor: same NDCI threshold and the same minimum
   cluster AREA in m2 (v1 used 0.25 / no clustering for S2 and 0.20 / 8 px for Tanager).
4. STATUS LEVELS: NONE / WATCH / ALERT_CANDIDATE / INCONCLUSIVE instead of a
   binary ALERT driven by a single maximum pixel.
5. TRACEABILITY: scene datetime, data age, cloud %, valid-water fraction and the
   parameters used are written into the event JSON.

Usage
-----
  python titan_hab_pipeline.py fetch --out out_mirfa      # downloads latest scene for Mirfa and runs
  python titan_hab_pipeline.py series --out out_series    # last 60 days: compare scenes, persistence, trend
  python titan_hab_pipeline.py s2  --dir s2_fujairah --out out/
  python titan_hab_pipeline.py tanager --event tanager_event.json --scene SCENE.json --out out/

For Fujairah, download Sentinel-2 L2A (B03,B04,B05,B08 + SCL) for a bbox that
CONTAINS the intake, e.g. [56.15, 25.12, 56.30, 25.25], write meta.json with
{"source","bbox","datetime","aoi","intake":[lat,lon]} next to the tifs, then run
the "s2" command. Pass --scl SCL.tif to mask clouds/shadows when you have it.
"""
import argparse, base64, io, json, os, sys
from datetime import datetime, timezone

import numpy as np
import tifffile
from PIL import Image
from scipy import ndimage as ndi

# Mirfa IWPP (Abu Dhabi, western region). Coordinates are the APPROXIMATE plant
# location (WRI Global Power Plant DB); confirm the real seawater intake with the operator.
MIRFA = dict(name="Mirfa IWPP desalination plant, Abu Dhabi", intake=(24.121, 53.447),
             bbox=[53.36, 24.04, 53.54, 24.20])
NEAR_INTAKE_KM = 5.0

# ----------------------------- unified parameters -----------------------------
PARAMS = dict(
    ndci_threshold=0.20,
    min_cluster_area_m2=7200.0,   # = 8 Tanager px (30 m) -> 18 S2 px (20 m)
    ndwi_water=0.10,
    nir_max_water=0.20,           # drops bright land / cloud / bright shallow bottom
    min_water_body_px=500,        # ignore ponds / sabkha pools (20 ha at 20 m)
    shore_buffer_px=3,            # 60 m at 20 m
    watch_min_pixels=1,
    min_signal_sum=0.03,          # smoothed (red + red-edge) must exceed this, else NDCI is noise
    smooth_px=3,                  # 3x3 mean before the ratio (tames noise on dark water)
    ndci_sanity_max=0.9,          # real NDCI never gets this high -> data/scaling problem
)


# ------------------------------- helpers --------------------------------------
def inside(bbox, lat, lon):
    w, s, e, n = bbox
    return (s <= lat <= n) and (w <= lon <= e)


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi, dl = p2 - p1, np.radians(lon2 - lon1)
    h = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return float(2 * r * np.arcsin(np.sqrt(h)))


def validate_aoi(bbox, intake):
    if intake is None:
        return False, "no intake defined"
    if not inside(bbox, intake[0], intake[1]):
        return False, (f"intake {intake} is OUTSIDE bbox {bbox}; "
                       "results cannot describe the intake zone")
    return True, "ok"


def read_geo(path):
    p = tifffile.TiffFile(path).pages[0]
    tags = {t.code: t.value for t in p.tags.values()}
    sx, sy, _ = tags[33550]
    _, _, _, x0, y0, _ = tags[33922]
    keys = tags[34735]
    epsg = None
    for i in range(4, len(keys), 4):
        if keys[i] == 3072:
            epsg = keys[i + 3]
    return dict(x0=x0, y0=y0, res=sx, epsg=epsg or 32639)


def clean_water(red, re_, nir, grn, p=PARAMS, scl=None):
    valid = np.isfinite(red + re_ + nir + grn)
    if scl is not None:  # drop no-data, saturated, shadow, clouds, cirrus, snow
        valid &= ~np.isin(scl, [0, 1, 3, 8, 9, 10, 11])
    # NDWI>0.1 written as an inequality so dark / slightly negative reflectances stay stable
    spec = (nir < p["nir_max_water"]) & (grn > (1 + p["ndwi_water"]) / (1 - p["ndwi_water"]) * nir)
    spec |= (grn < 0.02) & (nir < 0.02)          # very dark = clear deep water
    if scl is not None:
        spec |= (scl == 6)                       # Sentinel-2 SCL water class
    water = valid & spec
    water = ndi.binary_closing(water, iterations=1) & valid
    water = ndi.binary_opening(water, iterations=1)
    lab, n = ndi.label(water)
    if n:
        sizes = np.bincount(lab.ravel())
        keep = sizes >= p["min_water_body_px"]
        keep[0] = False
        water = keep[lab]
    clean = (ndi.binary_erosion(water, iterations=p["shore_buffer_px"])
             if p["shore_buffer_px"] > 0 else water)
    return valid, water, clean


def compute_ndci(red, re_, valid, p=PARAMS):
    """NDCI on 3x3-smoothed reflectance, only where the signal is above the noise floor."""
    k = p["smooth_px"]
    v = valid.astype("float64")
    den = ndi.uniform_filter(v, k) + 1e-12
    r_s = ndi.uniform_filter(np.where(valid, red, 0.0), k) / den
    e_s = ndi.uniform_filter(np.where(valid, re_, 0.0), k) / den
    tot = r_s + e_s
    ok = valid & (tot >= p["min_signal_sum"]) & (r_s > 0)
    ndci = np.full(red.shape, np.nan)
    ndci[ok] = (e_s[ok] - r_s[ok]) / tot[ok]
    return ndci


def run_s2(a):
    meta = json.load(open(os.path.join(a.dir, "meta.json")))
    bbox = meta["bbox"]
    if a.intake:
        meta["intake"] = list(a.intake)
    if a.aoi_name:
        meta["aoi"] = a.aoi_name
    intake = meta.get("intake")
    ok, msg = validate_aoi(bbox, intake)
    geo = read_geo(os.path.join(a.dir, "S2_B04.tif"))
    res = geo["res"]
    B = {k: tifffile.imread(os.path.join(a.dir, f"S2_{k}.tif")).astype("float64")
         for k in ("B03", "B04", "B05", "B08")}
    scl = tifffile.imread(a.scl) if a.scl else None
    red, re_, nir, grn = B["B04"], B["B05"], B["B08"], B["B03"]
    valid, water, clean = clean_water(red, re_, nir, grn, scl=scl)
    ndci = compute_ndci(red, re_, valid)
    p = PARAMS
    thr = p["ndci_threshold"]
    px_area = res * res
    min_px = int(np.ceil(p["min_cluster_area_m2"] / px_area))

    cand = clean & (ndci > thr)
    lab, n = ndi.label(cand, structure=np.ones((3, 3)))
    sizes = np.bincount(lab.ravel())[1:] if n else np.array([])
    qual_ids = [i + 1 for i, s in enumerate(sizes) if s >= min_px]
    qual = np.isin(lab, qual_ids) if qual_ids else np.zeros_like(cand)

    vals = ndci[clean & np.isfinite(ndci)]
    n_def = int(vals.size)
    if n_def == 0:
        vals = np.array([np.nan])
    band_stats = {nm: [round(float(x), 4) for x in np.nanpercentile(arr[clean], (5, 50, 95))]
                  for nm, arr in (("B03_green", grn), ("B04_red", red), ("B05_rededge", re_), ("B08_nir", nir))
                  if clean.any()}
    sens = {}
    for t in (0.10, 0.15, 0.20, 0.25):
        m = clean & (ndci > t)
        l2, n2 = ndi.label(m, structure=np.ones((3, 3)))
        s2 = np.bincount(l2.ravel())[1:] if n2 else np.array([])
        sens[str(t)] = dict(pixels=int(m.sum()), clusters=int(n2),
                            qualifying=int((s2 >= min_px).sum()),
                            largest_px=int(s2.max()) if n2 else 0)

    mask_sens = []
    for nm, bf in ((0.12, 3), (0.20, 1), (0.20, 3), (0.30, 3), (9.0, 3)):
        pp = dict(p, nir_max_water=nm, shore_buffer_px=bf)
        _, _, cc = clean_water(red, re_, nir, grn, pp, scl=scl)
        if not cc.any():
            continue
        mm = cc & (ndci > thr)
        l3, n3 = ndi.label(mm, structure=np.ones((3, 3)))
        s3 = np.bincount(l3.ravel())[1:] if n3 else np.array([0])
        mask_sens.append(dict(nir_max=nm, shore_buffer_px=bf, clean_px=int(cc.sum()),
                              ndci_max=round(float(np.nanmax(np.where(cc, ndci, np.nan))), 3),
                              px_above_thr=int(mm.sum()), qualifying_clusters=int((s3 >= min_px).sum())))

    scene_dt = meta.get("datetime")
    age = None
    if scene_dt:
        age = (datetime.now(timezone.utc) -
               datetime.fromisoformat(scene_dt.replace("Z", "+00:00"))).days

    clean_frac = float(clean.sum() / max(valid.sum(), 1))
    nir_med = band_stats.get("B08_nir", [0, 0, 0])[1]
    neg_refl = nir_med < -0.02
    sane = ((not n_def) or float(np.nanmax(vals)) < p["ndci_sanity_max"]) and not neg_refl
    if not sane:
        status = "INCONCLUSIVE"
        action = ("DATA CHECK FAILED: " +
                  ("water reflectance is negative (median NIR %.3f) - offset was subtracted twice? " % nir_med
                   if neg_refl else "NDCI >= %.1f is physically implausible - " % p["ndci_sanity_max"]) +
                  "check reflectance scaling/offset (see band_stats_clean_water)")
        qual_ids = []
        qual = np.zeros_like(cand)
    elif valid.mean() < 0.5:
        status, action = "INCONCLUSIVE", "scene covers < 50% of the AOI (partial tile)"
    elif clean.sum() < 2000 or n_def < 1000:
        status, action = "INCONCLUSIVE", "too little clean open water with usable signal in AOI"
    elif len(qual_ids) > 0:
        status = "ALERT_CANDIDATE"
        action = "confirm on next scene (>=2 dates) before raising ALERT"
    elif cand.sum() >= p["watch_min_pixels"]:
        status, action = "WATCH", "isolated pixels only - re-check next acquisition"
    else:
        status, action = "NONE", "standby"
    clusters = []
    if qual_ids:
        T = _transformer(geo["epsg"])
        for i in qual_ids:
            ys, xs = np.where(lab == i)
            cy, cx = ys.mean(), xs.mean()
            lon, lat = T.transform(geo["x0"] + (cx + .5) * res, geo["y0"] - (cy + .5) * res)
            dist = round(haversine_km(lat, lon, *intake), 2) if ok else None
            clusters.append(dict(lat=round(lat, 5), lon=round(lon, 5), pixels=int(len(ys)),
                                 distance_to_intake_km=dist,
                                 area_m2=float(len(ys) * px_area),
                                 ndci_max=round(float(ndci[ys, xs].max()), 3)))

    near = [c for c in clusters if c["distance_to_intake_km"] is not None
            and c["distance_to_intake_km"] <= NEAR_INTAKE_KM]
    if near:
        action = (f"HIGH PRIORITY: cluster within {NEAR_INTAKE_KM:.0f} km of intake "
                  f"(nearest {min(c['distance_to_intake_km'] for c in near)} km) - " + action)
    if age is not None and age > 30 and status != "INCONCLUSIVE":
        action += f" | scene is {age} days old - not near-real-time"


    event = dict(
        processed_utc=datetime.now(timezone.utc).isoformat(),
        scene_datetime=scene_dt, data_age_days=age,
        aoi=meta.get("aoi_validated") or _aoi_label(bbox, ok, meta),
        bbox=bbox,
        intake=intake if ok else None,
        intake_in_aoi=ok, aoi_check=msg,
        sources=[meta.get("source", "Sentinel-2 L2A")],
        indicator="NDCI (spectral proxy, not ground truth)",
        parameters=dict(p, pixel_size_m=res, min_cluster_pixels_at_this_res=min_px),
        valid_pixels=int(valid.sum()), valid_fraction_of_aoi=round(float(valid.mean()), 4),
        clean_water_pixels=int(clean.sum()),
        clean_water_fraction_of_valid=round(clean_frac, 4),
        ndci_clean_water=dict(max=round(float(np.nanmax(vals)), 4),
                              p99=round(float(np.nanpercentile(vals, 99)), 4),
                              p50=round(float(np.nanmedian(vals)), 4),
                              pixels_with_usable_signal=n_def),
        band_stats_clean_water=band_stats,
        data_quality=("ok" if sane else "FAILED_SANITY_CHECK"),
        preprocessing={k: meta.get(k) for k in ("reflectance_offset_subtracted", "nir_dn_p2",
                                                "already_reflectance", "processing_baseline",
                                                "cloud_cover_scene")},
        pixels_above_threshold=int(cand.sum()),
        clusters_total=int(n), clusters_qualifying=len(qual_ids),
        largest_cluster_px=int(sizes.max()) if n else 0,
        affected_area_m2=float(qual.sum() * px_area),
        pct_clean_water_above_threshold=round(float(cand.sum() / clean.sum() * 100), 5),
        sensitivity=sens, mask_sensitivity=mask_sens, qualifying_clusters=clusters,
        status=status, next_action=action,
        clusters_near_intake=len(near), near_intake_km=NEAR_INTAKE_KM,
        v1_comparison=dict(v1_status="ALERT", v1_ndci_max=0.4380,
                           note="v1 max (0.438) came from shoreline/mixed pixels (within ~1-2 px of land); "
                                "no cluster met the area rule under any mask setting tested"),
    )
    os.makedirs(a.out, exist_ok=True)
    json.dump(event, open(os.path.join(a.out, "titan_edge_event.json"), "w"),
              indent=2, ensure_ascii=False)
    meta2 = dict(meta, aoi_check=msg, intake_in_aoi=ok)
    json.dump(meta2, open(os.path.join(a.out, "meta.json"), "w"), indent=2)
    if not getattr(a, "no_map", False):
        build_s2_map(a.out, bbox, intake if ok else None, geo, ndci, clean, cand, qual,
                     water, event)
    print(json.dumps({k: event[k] for k in ("status", "next_action", "ndci_clean_water",
                      "pixels_above_threshold", "clusters_qualifying", "intake_in_aoi")},
                     indent=2))


def _aoi_label(bbox, ok, meta):
    w, s, e, n = bbox
    base = meta.get("aoi", "")
    if ok:
        return base
    return (f"Tarif / Abu Dhabi coast, Arabian Gulf (bbox {w:.2f}-{e:.2f}E, {s:.2f}-{n:.2f}N) "
            f"- corrected; v1 label was '{base}'")


def _transformer(epsg):
    from pyproj import Transformer
    return Transformer.from_crs(epsg, 4326, always_xy=True)


# --------------------------------- map ----------------------------------------
def _png_b64(rgba):
    buf = io.BytesIO()
    Image.fromarray(rgba).save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _to_latlon_grid(geo, layers, shape_hw, nx=1300):
    """Resample UTM rasters onto a regular lat/lon grid (nearest) for Leaflet."""
    from pyproj import Transformer
    T = Transformer.from_crs(4326, geo["epsg"], always_xy=True)
    H, W = shape_hw
    Tin = Transformer.from_crs(geo["epsg"], 4326, always_xy=True)
    xs = geo["x0"] + np.array([0, W]) * geo["res"]
    ys = geo["y0"] - np.array([0, H]) * geo["res"]
    lons, lats = Tin.transform(np.array([xs[0], xs[1], xs[0], xs[1]]),
                               np.array([ys[0], ys[0], ys[1], ys[1]]))
    w, e, s, n = lons.min(), lons.max(), lats.min(), lats.max()
    ny = int(nx * (n - s) / ((e - w) * np.cos(np.radians((n + s) / 2))))
    glon = np.linspace(w, e, nx)
    glat = np.linspace(n, s, ny)
    LON, LAT = np.meshgrid(glon, glat)
    X, Y = T.transform(LON, LAT)
    col = np.floor((X - geo["x0"]) / geo["res"]).astype(int)
    row = np.floor((geo["y0"] - Y) / geo["res"]).astype(int)
    ok = (col >= 0) & (col < W) & (row >= 0) & (row < H)
    col = np.clip(col, 0, W - 1)
    row = np.clip(row, 0, H - 1)
    out = []
    for lyr in layers:
        o = lyr[row, col]
        if o.dtype == bool:
            o = o & ok
        else:
            o = np.where(ok[..., None] if o.ndim == 3 else ok, o, 0)
        out.append(o)
    return out, [[float(s), float(w)], [float(n), float(e)]]


def build_s2_map(out_dir, bbox, intake, geo, ndci, clean, cand, qual, water, ev):
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import cm, colors
    H, W = ndci.shape
    norm = colors.Normalize(-0.15, 0.30)
    rgba = (matplotlib.colormaps["turbo"](norm(np.nan_to_num(ndci, nan=-1)))[..., :3] * 255).astype("uint8")
    a_ndci = np.where(clean, 215, 0).astype("uint8")
    ndci_img = np.dstack([rgba, a_ndci])
    wm = np.zeros((H, W, 4), "uint8"); wm[water] = (0, 120, 255, 90); wm[clean] = (0, 200, 255, 120)
    wp = np.zeros((H, W, 4), "uint8"); wp[cand] = (255, 140, 0, 255); wp[qual] = (255, 0, 0, 255)
    (g_ndci, g_wm, g_wp), bounds = _to_latlon_grid(geo, [ndci_img, wm, wp], (H, W))
    w, s, e, n = bbox
    clu = ev["qualifying_clusters"]
    clu_js = json.dumps(clu)
    panel = f"""
<b>Titan Edge - HAB screening (Sentinel-2, v2)</b><br>
Status: <b style="color:{ {'NONE':'#2e7d32','WATCH':'#ef6c00','ALERT_CANDIDATE':'#c62828','INCONCLUSIVE':'#555'}[ev['status']] }">{ev['status']}</b><br>
Scene: {ev['scene_datetime']} ({ev['data_age_days']} days old)<br>
NDCI (clean water) max {ev['ndci_clean_water']['max']} / p99 {ev['ndci_clean_water']['p99']}<br>
Rule: NDCI&gt;{ev['parameters']['ndci_threshold']}, cluster &ge; {int(ev['parameters']['min_cluster_area_m2'])} m&sup2;,
shore buffer {ev['parameters']['shore_buffer_px']*ev['parameters']['pixel_size_m']:.0f} m<br>
Pixels &gt; thr: {ev['pixels_above_threshold']} | qualifying clusters: {ev['clusters_qualifying']}<br>
AOI: {ev['aoi']}<br>
{('<span style="color:#1565c0">Intake (approx.) inside AOI; clusters near intake: ' + str(ev['clusters_near_intake']) + '</span>') if ev['intake_in_aoi'] else '<span style="color:#b71c1c">Intake is NOT inside this AOI - no intake claim is made.</span>'}
<br><small>NDCI is a spectral proxy, not ground truth.</small>"""
    mk = ""
    if intake:
        mk = (f"L.marker([{intake[0]},{intake[1]}]).addTo(map).bindTooltip('Desalination plant / intake (approx.)');"
              f"L.circle([{intake[0]},{intake[1]}],{{radius:{NEAR_INTAKE_KM*1000},color:'#1565c0',fill:false,dashArray:'6'}})"
              f".addTo(map).bindTooltip('{NEAR_INTAKE_KM:.0f} km watch radius');")
    html = _html_template(
        title="Titan Edge - HAB map (v2)", panel=panel, markers=mk,
        center=[(s + n) / 2, (w + e) / 2], zoom=11, aoi=[[s, w], [n, e]], bounds=bounds,
        overlays=[("Sentinel-2 NDCI (clean water)", _png_b64(g_ndci), True),
                  ("Water mask (blue=raw, cyan=clean)", _png_b64(g_wm), False),
                  ("Pixels > threshold (orange) / qualifying (red)", _png_b64(g_wp), True)],
        extra_js=f"""
var clusters={clu_js};
clusters.forEach(function(c){{L.circleMarker([c.lat,c.lon],{{radius:9,color:'red',fillOpacity:.3}})
 .bindTooltip('Cluster '+c.pixels+' px / '+c.area_m2+' m2, NDCI max '+c.ndci_max).addTo(map);}});""")
    open(os.path.join(out_dir, "titan_edge_hab_map.html"), "w", encoding="utf-8").write(html)


def _html_template(title, panel, center, zoom, aoi, bounds, overlays, extra_js="",
                   aoi_color="red", markers=""):
    ov_js = ""
    names = []
    for i, (name, uri, on) in enumerate(overlays):
        ov_js += (f"var ov{i}=L.imageOverlay('{uri}',{json.dumps(bounds)},{{opacity:1.0}});"
                  f"{'ov%d.addTo(map);' % i if on else ''}\n")
        names.append(f"{json.dumps(name)}:ov{i}")
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{title}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.css"/>
<script src="https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.js"></script>
<style>html,body,#map{{height:100%;margin:0}}
.panel{{background:rgba(255,255,255,.93);padding:8px 10px;font:12px/1.4 sans-serif;max-width:340px;
border-radius:6px;box-shadow:0 1px 5px rgba(0,0,0,.4)}}</style></head><body><div id="map"></div>
<script>
var map=L.map('map').setView({json.dumps(center)},{zoom});
var osm=L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19,attribution:'&copy; OpenStreetMap'}});
var esri=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',{{maxZoom:19,attribution:'Esri'}}).addTo(map);
{ov_js}
L.rectangle({json.dumps(aoi)},{{color:'{aoi_color}',fill:false,weight:2}}).addTo(map).bindTooltip('AOI (bbox)');
{markers}
L.control.layers({{'Esri.WorldImagery':esri,'OpenStreetMap':osm}},{{{",".join(names)}}},{{collapsed:false}}).addTo(map);
var p=L.control({{position:'bottomleft'}});p.onAdd=function(){{var d=L.DomUtil.create('div','panel');d.innerHTML={json.dumps(panel)};return d;}};p.addTo(map);
{extra_js}
</script></body></html>"""


# ------------------------------- Tanager --------------------------------------
def run_tanager(a):
    ev = json.load(open(a.event))
    sc = json.load(open(a.scene))
    props = sc["properties"]
    cloud = props.get("cloud_percent")
    scene_dt = ev["scene_datetime"]
    age = (datetime.now(timezone.utc) -
           datetime.fromisoformat(scene_dt.replace("Z", "+00:00"))).days
    bbox = ev["bbox"]
    p = PARAMS
    inconclusive = cloud is not None and cloud >= 30
    status = "INCONCLUSIVE" if (inconclusive and ev["clusters_qualifying"] == 0) else ev["anomaly_status"]
    new = dict(ev)
    new.pop("timestamp_utc", None)
    new.update(
        processed_utc=ev["timestamp_utc"], data_age_days=age,
        aoi=f"{props.get('location_description')} (scene bbox)",
        intake=None, intake_in_aoi=False,
        aoi_check="Fujairah intake (25.1807N, 56.2222E) is outside this scene; no intake claim",
        cloud_percent=cloud, quality_category=props.get("quality_category"),
        gsd_m=props.get("gsd"),
        parameters=dict(ndci_threshold=p["ndci_threshold"],
                        min_cluster_area_m2=p["min_cluster_area_m2"],
                        pixel_size_m=ev["pixel_size_m"],
                        min_cluster_pixels_at_this_res=int(np.ceil(p["min_cluster_area_m2"] / ev["pixel_size_m"] ** 2))),
        anomaly_status=status,
        status_reason=(f"{cloud}% cloud cover - 'no anomaly' cannot be asserted for the cloudy part"
                       if inconclusive else "ok"),
        next_action=("acquire a clear, recent scene over the real intake AOI"
                     if inconclusive else ev["next_action"]),
        carried_over_unverified=["ndci_max", "mean_turbidity_proxy", "clusters_total"],
        note="Raster data was not in the delivered package; numeric results are carried over from v1 "
             "and must be re-run on the HDF5/SR product with the same rules as the S2 pipeline.",
    )
    os.makedirs(a.out, exist_ok=True)
    json.dump(new, open(os.path.join(a.out, "tanager_event.json"), "w"), indent=2, ensure_ascii=False)
    json.dump(sc, open(os.path.join(a.out, f"{ev['scene_id']}.json"), "w"))
    if a.map_html:
        build_tanager_map(a.out, a.map_html, new)
    print(json.dumps({k: new[k] for k in ("anomaly_status", "status_reason", "next_action")}, indent=2))


def build_tanager_map(out_dir, src_html, ev):
    import re
    s = open(src_html, errors="ignore").read()
    imgs = re.findall(r'L\.imageOverlay\(\s*"(data:image/png;base64,[A-Za-z0-9+/=]+)"', s)
    w, so, e, n = ev["bbox"]
    bnds = [[so, w], [n, e]]
    peak = re.search(r'L\.circleMarker\(\s*\[([\d.]+),\s*([\d.]+)\]', s)
    mk = ""
    if peak:
        mk = (f"L.circleMarker([{peak.group(1)},{peak.group(2)}],{{radius:8,color:'red'}})"
              f".addTo(map).bindTooltip('Peak NDCI {ev['ndci_max']:.3f} (approx. location) - below threshold');")
    panel = f"""<b>Tanager-1 - HAB screening (v2)</b><br>
Status: <b style="color:#555">{ev['anomaly_status']}</b> - {ev['status_reason']}<br>
Scene: {ev['scene_datetime']} ({ev['data_age_days']} days old)<br>
Cloud: {ev['cloud_percent']}% | GSD {ev['gsd_m']} m<br>
NDCI max {ev['ndci_max']:.3f} (threshold {ev['parameters']['ndci_threshold']}); rule: cluster &ge; {int(ev['parameters']['min_cluster_area_m2'])} m&sup2;<br>
<span style="color:#b71c1c">AOI: {ev['aoi']}. Fujairah intake is NOT inside this scene - marker removed.</span><br>
<small>Numbers carried over from v1 (raster not provided). NDCI is a proxy, not ground truth.</small>"""
    ov = [("Water mask (NDWI &gt; 0.1)", imgs[0], False), ("NDCI (water)", imgs[1], True)]
    html = _html_template("Titan Edge - Tanager map (v2)", panel,
                          [(so + n) / 2, (w + e) / 2], 10, bnds and [[so, w], [n, e]], bnds, ov,
                          aoi_color="yellow", markers=mk)
    open(os.path.join(out_dir, "titan_edge_tanager_map.html"), "w", encoding="utf-8").write(html)


# --------------------------------- fetch --------------------------------------
def write_geotiff(path, arr, x0, y0, res, epsg):
    """Write a north-up single-band float32 GeoTIFF (UTM) readable by read_geo()."""
    keys = [1, 1, 0, 3, 1024, 0, 1, 1, 1025, 0, 1, 1, 3072, 0, 1, int(epsg)]
    tifffile.imwrite(path, arr.astype("float32"), extratags=[
        (33550, "d", 3, (float(res), float(res), 0.0), True),
        (33922, "d", 6, (0.0, 0.0, 0.0, float(x0), float(y0), 0.0), True),
        (34735, "H", len(keys), keys, True)])


def decide_offset(nir_dn):
    """Offset present => water NIR DN sits around 1000 (=0.1). If the 2nd percentile is far
    below that, the provider already removed the offset and subtracting again gives negative
    reflectance (this happened on the first Mirfa run)."""
    v = nir_dn[np.isfinite(nir_dn) & (nir_dn > 0)]
    p2 = float(np.percentile(v, 2)) if v.size else float("nan")
    return bool(p2 >= 600), p2


def _stac_search(bbox, days_list, max_cloud, date_range=None, collection="sentinel-2-l2a"):
    """Search Earth Search. date_range=(start, end) as 'YYYY-MM-DD' replays a past period
    (e.g. a documented bloom); otherwise look back over `days_list` from today."""
    from datetime import timedelta
    from pystac_client import Client
    cat = Client.open("https://earth-search.aws.element84.com/v1")
    q = {"eo:cloud_cover": {"lt": max_cloud}}
    if date_range:
        start, end = date_range
        items = list(cat.search(collections=[collection], bbox=bbox, datetime=f"{start}/{end}",
                                query=q).items())
        return items, f"{start}..{end}"
    now = datetime.now(timezone.utc)
    for days in days_list:
        rng = f"{(now - timedelta(days=days)).date()}/{now.date()}"
        items = list(cat.search(collections=[collection], bbox=bbox, datetime=rng, query=q).items())
        if items:
            return items, days
        print(f"No scene with cloud < {max_cloud}% in the last {days} days...")
    return [], None


def download_item(item, bbox, name, intake, outdir):
    """Download one Sentinel-2 item (clipped to bbox, 20 m) into outdir as GeoTIFFs + meta.json."""
    from odc.stac import load
    lon0 = (bbox[0] + bbox[2]) / 2
    epsg = 32600 + int((lon0 + 180) // 6) + 1
    ds = load([item], bands=["green", "red", "rededge1", "nir", "scl"], bbox=bbox,
              crs=f"EPSG:{epsg}", resolution=20, resampling={"scl": "nearest", "*": "bilinear"})
    ds = ds.isel(time=0)
    res = 20
    x0 = float(ds.x.values[0]) - res / 2
    y0 = float(ds.y.values[0]) + res / 2
    pb = item.properties.get("s2:processing_baseline")
    raw = {}
    for band, nm in (("green", "B03"), ("red", "B04"), ("rededge1", "B05"), ("nir", "B08")):
        arr = ds[band].values.astype("float64")
        arr[arr == 0] = np.nan
        raw[nm] = arr
    if not np.isfinite(raw["B08"]).any():
        raise RuntimeError("scene has no valid pixels inside the AOI")
    already_reflectance = bool(np.nanmax(raw["B08"]) <= 5)
    if already_reflectance:
        offset, nir_p2, scale = False, float("nan"), 1.0
    else:
        offset, nir_p2 = decide_offset(raw["B08"])
        scale = 1e-4
    print(f"[{item.properties['datetime'][:10]}] Reflectance handling: "
          f"already_reflectance={already_reflectance}, NIR DN p2={nir_p2:.0f} -> subtract 0.1 offset: {offset}")
    os.makedirs(outdir, exist_ok=True)
    for nm, arr in raw.items():
        refl = arr * scale - (0.1 if offset else 0.0)       # no clipping: negatives are kept
        write_geotiff(os.path.join(outdir, f"S2_{nm}.tif"), refl, x0, y0, res, epsg)
    write_geotiff(os.path.join(outdir, "SCL.tif"), ds["scl"].values, x0, y0, res, epsg)
    meta = dict(source=f"Sentinel-2 L2A ({item.id})", bbox=bbox, datetime=item.properties["datetime"],
                cloud_cover_scene=item.properties.get("eo:cloud_cover"), processing_baseline=pb,
                reflectance_offset_subtracted=offset, nir_dn_p2=nir_p2,
                already_reflectance=already_reflectance, aoi=name, intake=list(intake))
    json.dump(meta, open(os.path.join(outdir, "meta.json"), "w"), indent=2)
    return meta


def _dr(a):
    """(start, end) from --start/--end, or None for 'last N days'."""
    if getattr(a, "start", None):
        return (a.start, a.end or datetime.now(timezone.utc).date().isoformat())
    return None


def run_fetch(a):
    """Download the latest clear Sentinel-2 L2A scene around the intake and run the screening."""
    bbox = a.bbox or MIRFA["bbox"]
    intake = tuple(a.intake) if a.intake else MIRFA["intake"]
    name = a.aoi_name or MIRFA["name"]
    ok, msg = validate_aoi(bbox, intake)
    if not ok:
        sys.exit("ERROR: " + msg)
    items, days = _stac_search(bbox, (a.days, 45, 120), a.max_cloud, _dr(a), a.collection)
    if not items:
        sys.exit("No suitable Sentinel-2 scene found. Try --max-cloud 40.")
    items.sort(key=lambda i: i.properties["datetime"], reverse=True)
    item = items[0]
    print(f"Found {len(items)} scene(s) in the last {days} days; using {item.id}")
    download_item(item, bbox, name, intake, a.dir)
    a.scl = os.path.join(a.dir, "SCL.tif")
    a.intake = list(intake)
    a.aoi_name = name
    run_s2(a)


# ------------------------------ multi-date series ------------------------------
SITE_KM = 0.5            # clusters within 500 m across scenes are treated as the same "site"
RECURRING_MIN_SCENES = 3  # a site seen in >= 3 scenes is reported as recurring (likely a fixed feature)
PERSIST_KM = 1.0          # a cluster "persists" if a qualifying cluster lay within 1 km in the previous scene
TREND_RISING = 0.01       # p99 NDCI change per week treated as a real trend

STATUS_AR = {"NONE": "لا شذوذ", "WATCH": "مراقبة", "ALERT_CANDIDATE": "تنبيه مرشَّح (غير مؤكد)",
             "ALERT": "تنبيه مؤكد (ظهر في مشهدين)", "ALERT_NEAR_INTAKE": "تنبيه مؤكد قرب المأخذ",
             "INCONCLUSIVE": "غير حاسم"}
STATUS_COLOR = {"NONE": "#2e7d32", "WATCH": "#ef6c00", "ALERT_CANDIDATE": "#e65100",
                "ALERT": "#c62828", "ALERT_NEAR_INTAKE": "#b71c1c", "INCONCLUSIVE": "#616161"}


def find_recurring_sites(usable_rows, intake):
    sites = []
    for r in usable_rows:
        for c in r["clusters"]:
            best, bd = None, SITE_KM
            for st in sites:
                d = haversine_km(c["lat"], c["lon"], st["lat"], st["lon"])
                if d <= bd:
                    best, bd = st, d
            if best is None:
                best = dict(lat=c["lat"], lon=c["lon"], members=[])
                sites.append(best)
            best["members"].append((r["date"], c))
    out = []
    for st in sites:
        dates = sorted({d for d, _ in st["members"]})
        if len(dates) < RECURRING_MIN_SCENES:
            continue
        lat = float(np.median([c["lat"] for _, c in st["members"]]))
        lon = float(np.median([c["lon"] for _, c in st["members"]]))
        out.append(dict(lat=round(lat, 5), lon=round(lon, 5), scenes_seen=len(dates), dates=dates,
                        usable_scenes_in_window=len(usable_rows),
                        distance_to_intake_km=round(haversine_km(lat, lon, *intake), 2),
                        ndci_max=round(max(c["ndci_max"] for _, c in st["members"]), 3),
                        max_pixels=max(c["pixels"] for _, c in st["members"]),
                        interpretation="fixed-position recurrence - more typical of a fixed feature "
                                       "(shallow bottom, jetty, vessel, outfall) than a drifting bloom; check visually",
                        maps_url=f"https://www.google.com/maps/@{lat:.5f},{lon:.5f},500m/data=!3m1!1e3"))
    out.sort(key=lambda x: (-x["scenes_seen"], x["distance_to_intake_km"]))
    return out


def analyze_series(events, intake=None):
    rows = []
    for ev in events:
        nd = ev["ndci_clean_water"]
        clusters = [dict(c) for c in ev.get("qualifying_clusters", [])]
        dists = [c["distance_to_intake_km"] for c in clusters if c.get("distance_to_intake_km") is not None]
        rows.append(dict(
            date=ev["scene_datetime"][:10], datetime=ev["scene_datetime"], status=ev["status"],
            usable=(ev["data_quality"] == "ok" and ev["status"] != "INCONCLUSIVE"),
            reason=ev["next_action"] if ev["status"] == "INCONCLUSIVE" else "",
            cloud_pct=(ev.get("preprocessing") or {}).get("cloud_cover_scene"),
            valid_fraction=ev.get("valid_fraction_of_aoi"),
            ndci_p50=nd.get("p50"), ndci_p99=nd.get("p99"), ndci_max=nd.get("max"),
            pixels_above_threshold=ev["pixels_above_threshold"],
            qualifying_clusters=ev["clusters_qualifying"], persistent_clusters=0,
            affected_area_m2=ev["affected_area_m2"],
            nearest_cluster_km=min(dists) if dists else None, clusters=clusters))
    usable = [r for r in rows if r["usable"]]
    for i, r in enumerate(usable):
        if i == 0:
            continue
        prev = usable[i - 1]["clusters"]
        for c in r["clusters"]:
            if any(haversine_km(c["lat"], c["lon"], q["lat"], q["lon"]) <= PERSIST_KM for q in prev):
                c["persistent"] = True
                r["persistent_clusters"] += 1
    recurring = find_recurring_sites(usable, tuple(intake)) if intake else []
    persist_near = [c for r in usable[-1:] for c in r["clusters"]
                    if c.get("persistent") and c.get("distance_to_intake_km") is not None
                    and c["distance_to_intake_km"] <= NEAR_INTAKE_KM]
    # trend of p99 over the last (up to) 5 usable scenes
    trend = dict(label="غير كافٍ", slope_per_week=None, n=len(usable[-5:]))
    last5 = usable[-5:]
    if len(last5) >= 3:
        t0 = datetime.fromisoformat(last5[0]["datetime"].replace("Z", "+00:00"))
        x = [(datetime.fromisoformat(r["datetime"].replace("Z", "+00:00")) - t0).total_seconds() / 604800 for r in last5]
        slope = float(np.polyfit(x, [r["ndci_p99"] for r in last5], 1)[0])
        trend["slope_per_week"] = round(slope, 4)
        trend["label"] = ("متصاعد" if slope > TREND_RISING else "متراجع" if slope < -TREND_RISING else "مستقر")
    latest = rows[-1] if rows else None
    if latest is None:
        status, why = "INCONCLUSIVE", "no scenes"
    elif not latest["usable"]:
        status, why = "INCONCLUSIVE", "latest scene unusable: " + latest["reason"]
    elif persist_near:
        status, why = "ALERT_NEAR_INTAKE", f"{len(persist_near)} persistent cluster(s) within {NEAR_INTAKE_KM:.0f} km of intake"
    elif latest["persistent_clusters"] > 0:
        status, why = "ALERT", f"{latest['persistent_clusters']} cluster(s) seen in two consecutive scenes"
    elif latest["qualifying_clusters"] > 0:
        status, why = "ALERT_CANDIDATE", "qualifying cluster(s) in latest scene only - confirm on next scene"
    elif latest["pixels_above_threshold"] > 0:
        status, why = "WATCH", "isolated pixels above threshold only"
    else:
        status, why = "NONE", "no pixels above threshold"
    rec_near = [x for x in recurring if x["distance_to_intake_km"] <= NEAR_INTAKE_KM]
    if rec_near:
        x = rec_near[0]
        why += (f" | recurring fixed site {x['distance_to_intake_km']} km from intake, seen in "
                f"{x['scenes_seen']} of {x['usable_scenes_in_window']} scenes - inspect visually")
    if status in ("ALERT_CANDIDATE", "WATCH", "NONE") and trend["label"] == "متصاعد":
        why += " | p99 NDCI trend is rising - watch the next acquisition"
    return dict(series_status=status, reason=why, trend=trend, scenes=len(rows),
                usable_scenes=len(usable), recurring_sites=recurring, rows=rows)


def build_series_report(out_dir, summary, aoi, intake):
    rows = summary["rows"]
    st = summary["series_status"]
    W_, H_, ml, mr, mt, mb = 760, 300, 52, 16, 16, 40
    pts = [r for r in rows if r["usable"]]
    chart = '<p>لا توجد مشاهد صالحة لرسم المنحنى.</p>'
    if len(pts) >= 1:
        t = [datetime.fromisoformat(r["datetime"].replace("Z", "+00:00")).timestamp() for r in pts]
        tmin, tmax = min(t), max(t) if max(t) > min(t) else min(t) + 86400
        ymax = max(0.35, max(r["ndci_max"] for r in pts) + 0.05)
        ymin = min(-0.1, min(r["ndci_p50"] for r in pts) - 0.02)
        X = lambda v: ml + (v - tmin) / (tmax - tmin) * (W_ - ml - mr)
        Y = lambda v: mt + (ymax - v) / (ymax - ymin) * (H_ - mt - mb)
        g = [f'<line x1="{ml}" y1="{Y(0.2):.1f}" x2="{W_-mr}" y2="{Y(0.2):.1f}" stroke="#c62828" stroke-dasharray="6 4"/>'
             f'<text x="{W_-mr-4}" y="{Y(0.2)-4:.1f}" text-anchor="end" font-size="11" fill="#c62828">عتبة 0.20</text>']
        for k in range(int(np.floor(ymin * 10)), int(np.ceil(ymax * 10)) + 1):
            v = k / 10
            if ymin <= v <= ymax:
                g.append(f'<line x1="{ml}" y1="{Y(v):.1f}" x2="{W_-mr}" y2="{Y(v):.1f}" stroke="#ddd"/>'
                         f'<text x="{ml-6}" y="{Y(v)+4:.1f}" text-anchor="end" font-size="11" fill="#555">{v:.1f}</text>')
        for key, color, label in (("ndci_p50", "#1565c0", "وسيط"), ("ndci_p99", "#ef6c00", "المئين 99"), ("ndci_max", "#6a1b9a", "الأقصى")):
            path = " ".join(f"{X(tt):.1f},{Y(r[key]):.1f}" for tt, r in zip(t, pts))
            g.append(f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{path}"/>')
            for tt, r in zip(t, pts):
                g.append(f'<circle cx="{X(tt):.1f}" cy="{Y(r[key]):.1f}" r="3.5" fill="{color}"/>')
        for tt, r in zip(t, pts):
            g.append(f'<text x="{X(tt):.1f}" y="{H_-mb+16}" text-anchor="middle" font-size="10" fill="#555">{r["date"][5:]}</text>')
        leg = "".join(f'<tspan fill="{c}" dx="12">&#9679; {l}</tspan>' for _, c, l in
                      (("", "#1565c0", "وسيط"), ("", "#ef6c00", "المئين 99"), ("", "#6a1b9a", "الأقصى")))
        g.append(f'<text x="{ml+8}" y="{mt+10}" font-size="11">{leg}</text>')
        chart = f'<svg viewBox="0 0 {W_} {H_}" style="width:100%;max-width:{W_}px;background:#fff;border:1px solid #ddd">{"".join(g)}</svg>'
    trs = ""
    for r in rows:
        near = f'{r["nearest_cluster_km"]:.1f}' if r["nearest_cluster_km"] is not None else "-"
        f2 = lambda v: "-" if v is None else f"{v:.3f}"
        trs += (f'<tr><td>{r["date"]}</td><td style="color:{STATUS_COLOR.get(r["status"], "#000")}"><b>{STATUS_AR.get(r["status"], r["status"])}</b></td>'
                f'<td>{f2(r["ndci_p50"])}</td><td>{f2(r["ndci_p99"])}</td><td>{f2(r["ndci_max"])}</td>'
                f'<td>{r["pixels_above_threshold"]}</td><td>{r["qualifying_clusters"]}</td><td>{r["persistent_clusters"]}</td>'
                f'<td>{near}</td><td>{"-" if r["cloud_pct"] is None else format(r["cloud_pct"], ".1f")}</td></tr>')
    rec = summary.get("recurring_sites", [])
    rec_html = ""
    if rec:
        rr = "".join(f'<tr><td>{x["lat"]:.5f}, {x["lon"]:.5f}</td><td>{x["scenes_seen"]} من {x["usable_scenes_in_window"]}</td>'
                     f'<td>{x["distance_to_intake_km"]}</td><td>{x["ndci_max"]}</td><td>{x["max_pixels"]}</td>'
                     f'<td><a href="{x["maps_url"]}" target="_blank">افتح في خرائط Google</a></td></tr>' for x in rec)
        rec_html = (f'<h3>مواقع متكررة (ظهرت في {RECURRING_MIN_SCENES} مشاهد أو أكثر ضمن {int(SITE_KM*1000)} م)</h3>'
                    f'<p style="font-size:13px">التكرار في نفس الموضع يوحي عادةً بمعلم ثابت (قاع ضحل أو رصيف أو سفينة أو مخرج تصريف) أكثر منه ازدهاراً طحلبياً متحركاً. افحصها بصرياً على صورة القمر الصناعي.</p>'
                    f'<table><tr><th>الموقع</th><th>عدد المشاهد</th><th>المسافة للمأخذ (كم)</th><th>NDCI أقصى</th><th>أكبر مساحة (بكسل)</th><th>رابط</th></tr>{rr}</table>')
    tr_ = summary["trend"]
    slope = "-" if tr_["slope_per_week"] is None else f'{tr_["slope_per_week"]:+.3f} / أسبوع'
    html = f"""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>تقرير مراقبة الطحالب</title>
<style>body{{font-family:Tahoma,Arial,sans-serif;margin:12px;color:#222}}table{{border-collapse:collapse;width:100%;font-size:13px}}
td,th{{border:1px solid #ddd;padding:4px 6px;text-align:center}}th{{background:#f3f3f3}}.box{{padding:10px 14px;border-radius:6px;background:#f7f7f7;margin-bottom:12px}}</style></head><body>
<h2>مراقبة الطحالب الضارة - {aoi}</h2>
<div class="box"><div style="font-size:20px;color:{STATUS_COLOR.get(st, '#000')}"><b>الحالة الحالية: {STATUS_AR.get(st, st)}</b> <small>({st})</small></div>
<div>{summary['reason']}</div>
<div>الاتجاه (المئين 99 لـ NDCI): <b>{tr_['label']}</b> {slope} | المشاهد: {summary['usable_scenes']} صالح من {summary['scenes']}</div>
<div>المأخذ (تقريبي): {intake[0]:.5f}, {intake[1]:.5f} | نصف قطر المراقبة {NEAR_INTAKE_KM:.0f} كم</div></div>
{chart}
<h3>جدول المشاهد</h3><table><tr><th>التاريخ</th><th>الحالة</th><th>NDCI وسيط</th><th>NDCI م99</th><th>NDCI أقصى</th>
<th>بكسلات فوق العتبة</th><th>تجمعات مؤهلة</th><th>تجمعات متكررة</th><th>أقرب تجمع (كم)</th><th>سحب %</th></tr>{trs}</table>
{rec_html}
<p style="font-size:12px;color:#666">NDCI مؤشر تقديري من القمر الصناعي وليس قياس كلوروفيل. التجمع "متكرر" إذا ظهر تجمع مؤهل ضمن {PERSIST_KM:.0f} كم في المشهد الصالح السابق.
التنبيه المؤكد يتطلب تكراراً في مشهدين متتاليين.</p></body></html>"""
    open(os.path.join(out_dir, "series_report.html"), "w", encoding="utf-8").write(html)


def run_series(a):
    import shutil
    from argparse import Namespace
    bbox = a.bbox or MIRFA["bbox"]
    intake = tuple(a.intake) if a.intake else MIRFA["intake"]
    name = a.aoi_name or MIRFA["name"]
    ok, msg = validate_aoi(bbox, intake)
    if not ok:
        sys.exit("ERROR: " + msg)
    os.makedirs(os.path.join(a.out, "scenes"), exist_ok=True)
    jobs = []     # (tag, scene_dir, downloader or None)
    if a.local_root:
        dirs = [os.path.join(a.local_root, d) for d in sorted(os.listdir(a.local_root))
                if os.path.exists(os.path.join(a.local_root, d, "meta.json"))]
        dirs.sort(key=lambda d: json.load(open(os.path.join(d, "meta.json")))["datetime"])
        jobs = [(os.path.basename(d), d, None) for d in dirs]
    else:
        items, days = _stac_search(bbox, (a.days,), a.max_cloud, _dr(a), a.collection)
        if not items:
            sys.exit(f"No scenes with cloud < {a.max_cloud}% in the last {a.days} days. Try --days 90 or --max-cloud 50.")
        best = {}
        for it in items:                       # one scene per calendar day (lowest cloud)
            d = it.properties["datetime"][:10]
            if d not in best or it.properties.get("eo:cloud_cover", 100) < best[d].properties.get("eo:cloud_cover", 100):
                best[d] = it
        chosen = [best[d] for d in sorted(best)][-a.max_scenes:]
        print(f"{len(items)} scene(s) found, analysing {len(chosen)}: {[i.properties['datetime'][:10] for i in chosen]}")
        for it in chosen:
            tag = it.properties["datetime"][:10]
            jobs.append((tag, os.path.join(a.work, f"s2_{tag}"), it))
    events = []
    for k, (tag, sdir, item) in enumerate(jobs):
        last = (k == len(jobs) - 1)
        try:
            if item is not None:
                download_item(item, bbox, name, intake, sdir)
            ns = Namespace(dir=sdir, out=os.path.join(a.out, "scenes", tag),
                           scl=(os.path.join(sdir, "SCL.tif") if os.path.exists(os.path.join(sdir, "SCL.tif")) else None),
                           intake=list(intake), aoi_name=name, no_map=not last)
            run_s2(ns)
            events.append(json.load(open(os.path.join(ns.out, "titan_edge_event.json"))))
            if last:
                shutil.copy(os.path.join(ns.out, "titan_edge_hab_map.html"), os.path.join(a.out, "latest_map.html"))
        except Exception as e:                  # one bad scene must not kill the series
            print(f"!! scene {tag} skipped: {e}")
        finally:
            if item is not None and not a.keep_data:
                shutil.rmtree(sdir, ignore_errors=True)
    if not events:
        sys.exit("No scene could be processed.")
    summary = analyze_series(events, intake)
    summary.update(aoi=name, intake=list(intake), bbox=bbox, generated_utc=datetime.now(timezone.utc).isoformat(),
                   parameters=dict(PARAMS, persist_km=PERSIST_KM, near_intake_km=NEAR_INTAKE_KM))
    json.dump(summary, open(os.path.join(a.out, "series_summary.json"), "w"), indent=2, ensure_ascii=False)
    import csv
    with open(os.path.join(a.out, "series_table.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        cols = ["date", "status", "usable", "ndci_p50", "ndci_p99", "ndci_max", "pixels_above_threshold",
                "qualifying_clusters", "persistent_clusters", "nearest_cluster_km", "cloud_pct", "valid_fraction"]
        w.writerow(cols)
        for r in summary["rows"]:
            w.writerow([r[c] for c in cols])
    build_series_report(a.out, summary, name, intake)
    print("\n==== SERIES RESULT ====")
    print("status :", summary["series_status"], "-", summary["reason"])
    print("trend  :", summary["trend"])
    for r in summary["rows"]:
        print(f'{r["date"]}  {r["status"]:<16} p99={r["ndci_p99"]}  max={r["ndci_max"]}  '
              f'qual={r["qualifying_clusters"]} persist={r["persistent_clusters"]} near_km={r["nearest_cluster_km"]}')


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("s2"); s.add_argument("--dir", required=True); s.add_argument("--out", required=True)
    s.add_argument("--scl")
    s.add_argument("--intake", nargs=2, type=float, metavar=("LAT", "LON"))
    s.add_argument("--aoi-name", dest="aoi_name")
    f = sub.add_parser("fetch", help="download latest clear Sentinel-2 scene and run (default: Mirfa)")
    f.add_argument("--out", default="out_mirfa"); f.add_argument("--dir", default="s2_data")
    f.add_argument("--bbox", nargs=4, type=float, metavar=("W", "S", "E", "N"))
    f.add_argument("--intake", nargs=2, type=float, metavar=("LAT", "LON"))
    f.add_argument("--aoi-name", dest="aoi_name")
    f.add_argument("--start"); f.add_argument("--end"); f.add_argument("--collection", default="sentinel-2-l2a")
    f.add_argument("--days", type=int, default=15); f.add_argument("--max-cloud", dest="max_cloud", type=float, default=20)
    r = sub.add_parser("series", help="multi-date monitoring: fetch several scenes, compare, trend, persistence")
    r.add_argument("--out", default="out_series"); r.add_argument("--work", default="s2_series")
    r.add_argument("--bbox", nargs=4, type=float, metavar=("W", "S", "E", "N"))
    r.add_argument("--intake", nargs=2, type=float, metavar=("LAT", "LON"))
    r.add_argument("--aoi-name", dest="aoi_name")
    r.add_argument("--start", help="replay a past period: YYYY-MM-DD"); r.add_argument("--end")
    r.add_argument("--collection", default="sentinel-2-l2a", help="e.g. sentinel-2-c1-l2a for older reprocessed scenes")
    r.add_argument("--days", type=int, default=60); r.add_argument("--max-cloud", dest="max_cloud", type=float, default=30)
    r.add_argument("--max-scenes", dest="max_scenes", type=int, default=8)
    r.add_argument("--local-root", dest="local_root"); r.add_argument("--keep-data", dest="keep_data", action="store_true")
    t = sub.add_parser("tanager"); t.add_argument("--event", required=True); t.add_argument("--scene", required=True)
    t.add_argument("--out", required=True); t.add_argument("--map-html", dest="map_html")
    a = ap.parse_args()
    {"s2": run_s2, "tanager": run_tanager, "fetch": run_fetch, "series": run_series}[a.cmd](a)
