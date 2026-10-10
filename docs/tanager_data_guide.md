# Tanager data guide (as used by this repository)

## HDF5 layout

```
HDFEOS/GRIDS/HYP/Data Fields/
├── surface_reflectance   (bands, rows, cols) float32   main cube (426 bands, 380–2500 nm)
├── beta_cloud_mask       (rows, cols) uint8
├── beta_cirrus_mask      (rows, cols) uint8
├── nodata_pixels         (rows, cols) uint8
└── … aerosol_optical_depth, column_water_vapour, sensor_zenith, sun_zenith
```

Files are typically 1–5 GB. The loader (`src/space_twin/tanager_loader.py`) reads only the four bands it needs into memory (strided reads only when averaging full spectra), then builds `valid = nodata == 0 & cloud == 0 & cirrus == 0` and sets invalid or negative reflectance to NaN.

## Wavelengths

Stored in the STAC item, in micrometres, under `assets[<sr_key>]["bands"][i]["eo:center_wavelength"]` (the `eo:` prefix matters). `<sr_key>` is `ortho_sr_hdf5` when present, else `basic_sr_hdf5`. The loader converts to nm and picks the band nearest 560, 665, 708 and 860 nm. It raises if the band count differs from the wavelength count.

## Bands excluded from spectra

Water-vapour windows 1350–1450 nm and 1800–1950 nm, and everything above 2450 nm (noisy SWIR edge), are set to NaN before averaging spectra (`tanager_loader.BAD_RANGES`).

## Placement caveat

The loader places a scene on the map from its STAC `bbox` (north-up ortho product), so positions are **approximate**. A `basic_sr_hdf5` product is not north-up and its position is unreliable; the scene metadata says so.

## Reference spectra for the drone rescan

`reference_spectra()` returns the mean spectrum of water pixels with NDCI ≤ the scene median (clean) and ≥ the 99th percentile (suspect). These replace the illustrative library in `titan_air_drone`, giving a real bloom-vs-clean contrast. They do not identify species, and in a scene without an anomaly the "suspect" spectrum is just the top 1 % of ordinary variation, not a bloom.

## Licence and attribution

Tanager data are CC BY 4.0. Any use or redistribution must carry: *"Tanager STAC Data, available at www.planet.com/data/stac © [YEAR] Planet Labs PBC. All Rights Reserved."* where YEAR is the capture year in the scene ID (e.g. `20250223` → 2025). Prefix "Adapted from…" for adapted material.
