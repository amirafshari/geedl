---
title: geedl — Earth Engine, locally
template: home.html
hide:
  - navigation
  - toc
---

<div class="geedl-talk" markdown>

<span class="geedl-talk__eyebrow">No code. No SDK. Just words.</span>

## Describe what you want. Run one command. { .geedl-talk__title }

Drop the [README](https://github.com/amirafshari/geedl#readme) into any coding agent's context — Claude Code, Cursor, Codex, Aider, ChatGPT. Then ask in plain English. The agent writes the YAML. You run `geedl`.

<div class="geedl-chat" markdown>

<div class="geedl-chat__msg geedl-chat__msg--user" markdown>
<div class="geedl-chat__who">You</div>

> I need a monthly NDVI and NDWI time series over my farm in Tuscany for all of 2023. Shapefile is at `data/tuscany.shp`. Sentinel-2, mask clouds and shadows, output COGs, drop the source bands. Run 24 tiles in parallel.

</div>

<div class="geedl-chat__msg geedl-chat__msg--agent" markdown>
<div class="geedl-chat__who">Your agent → <code>job.yaml</code></div>

```yaml
job_name: tuscany_ndvi_ndwi_2023

roi:
  path: data/tuscany.shp

dataset:
  name: sentinel-2
  bands:
    select: []                  # drop source bands, keep only indices
  indices:
    - {name: NDVI}
    - {name: NDWI}
  cloud_mask:
    enabled: true
    mask_shadow: true

date:
  start: "2023-01-01"
  end:   "2023-12-31"

composite:
  strategy: median
  window:
    type: calendar_month
    label_format: "%Y-%m"

output:
  dir: ./output
  format: COG
  dtype: float32
  structure:
    separate_indices: true      # one GeoTIFF per index

pipeline:
  concurrency: 24
```

</div>

<div class="geedl-chat__msg geedl-chat__msg--user" markdown>
<div class="geedl-chat__who">You</div>

```bash
geedl plan -c job.yaml && geedl run -c job.yaml
```

</div>

</div>

That's the whole loop. Need to change sensor? *"Switch to Landsat 8 with the same indices."* Need a different window? *"Make it 16-day composites anchored on the window start."* Need urban detection from SAR? *"Give me Sentinel-1 SAR_URBAN false-color for the first week of May."* The agent edits the YAML. You re-run `geedl`.

??? question "Why does this work so well with agents?"

    The repo ships with a [`CLAUDE.md`](https://github.com/amirafshari/geedl/blob/master/.claude/CLAUDE.md) that documents every config field, every module boundary, and every non-negotiable constraint — atomic writes, plugin-only indices, Sentinel-1-must-be-mosaic, and the rest. An agent reading it has the full schema **and** the full set of rules — so it doesn't hallucinate fields or pick physically wrong composite strategies. Drop the README and `CLAUDE.md` into your agent's context and you get one-shot, correct configs.

</div>

<div class="geedl-cta" markdown>

[Get started →](getting-started.md){ .geedl-btn .geedl-btn--primary }
[Browse examples](examples.md){ .geedl-btn .geedl-btn--ghost }

</div>
