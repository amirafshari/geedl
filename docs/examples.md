# Examples

!!! info "Coming soon"
    Phase 2 of the docs rollout will expand this page with a prose walkthrough
    for each example YAML. For now, browse the raw configs in the repo:

The repository ships with ready-to-run example configs in [`examples/`](https://github.com/amirafshari/geedl/tree/master/examples):

| File | What it does |
|---|---|
| [`ndvi-only.yaml`](https://github.com/amirafshari/geedl/blob/master/examples/ndvi-only.yaml) | Sentinel-2 NDVI time series, no source bands. |
| [`rgb-only.yaml`](https://github.com/amirafshari/geedl/blob/master/examples/rgb-only.yaml) | True-colour Sentinel-2 RGB composites. |
| [`full-band-only.yaml`](https://github.com/amirafshari/geedl/blob/master/examples/full-band-only.yaml) | All Sentinel-2 surface-reflectance bands, no indices. |
| [`water-ndwi.yaml`](https://github.com/amirafshari/geedl/blob/master/examples/water-ndwi.yaml) | Optical water detection via NDWI. |
| [`oil-spill-osfc.yaml`](https://github.com/amirafshari/geedl/blob/master/examples/oil-spill-osfc.yaml) | Oil-spill false-colour composite. |
| [`s1-rgb-ratio.yaml`](https://github.com/amirafshari/geedl/blob/master/examples/s1-rgb-ratio.yaml) | Sentinel-1 VV/VH ratio false-colour RGB. |
| [`s1-rtc.yaml`](https://github.com/amirafshari/geedl/blob/master/examples/s1-rtc.yaml) | Sentinel-1 radiometric terrain-corrected backscatter. |
| [`s1-sar-urban.yaml`](https://github.com/amirafshari/geedl/blob/master/examples/s1-sar-urban.yaml) | Sentinel-1 SAR urban false-colour. |
| [`sentinel1-scene.yaml`](https://github.com/amirafshari/geedl/blob/master/examples/sentinel1-scene.yaml) | Single-date scene mode with nearest-date fallback. |

Each config is a complete, runnable job — drop it in your project and run:

```bash
geedl plan -c examples/ndvi-only.yaml
geedl run  -c examples/ndvi-only.yaml
```
