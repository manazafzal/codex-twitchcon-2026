# Mind Atlas performance and visual checks

Measured with **Chromium 154.0.8037.57 built on Debian GNU/Linux 13 (trixie)**, headless Linux, CPU SwiftShader, `?scale=.5`. The field buffer is 960×540, the effects layer is 1920×1080, and the stage is 1920×1080. Chrome uses `--use-angle=swiftshader --enable-unsafe-swiftshader`; all page assets are local. The measured scene uses explicitly labelled mock traces, not trained-model evidence.

## Playback timing

120 actual requestAnimationFrame intervals, sampled without per-frame screenshots or DevTools commands:

| Mean frame | Measured playback | 95th percentile |
| --- | --- | --- |
| 725.11 ms | 1.38 fps | 2001.66 ms |

This software renderer is CPU-bound. **Hardware-GPU 60 fps is unverified.** The 30 fps film cadence is a virtual output rate and is not a playback-speed claim. The scale governor reduces resolution by .125 after a 60-frame mean above 22 ms, stopping at .5; this measurement starts at that minimum. Canvas-only rendering is available with `?nogl`.

## Screenshots and pixel checks

Five scenes captured at 1920×1080. The brightness limit is 0.5% of pixels with every RGB channel at least 250.

| Scene | Renderer | Bright pixels | Console errors |
| --- | --- | --- | --- |
| war | gl | 0.1522% | 0 |
| attack | gl | 0.2048% | 0 |
| immune | gl | 0.2961% | 0 |
| telepathy | gl | 0.1849% | 0 |
| reveal | gl | 0.0673% | 0 |

Transparent capture: **93.86%** of pixels have alpha below 255 (minimum 90%). Quarter-size left-column contrast: **4.79:1** (minimum 4.5:1). Contrast compares the 99th-percentile glyph-interior luminance with the 20th-percentile adjacent ground in the left answer region; antialiased boundaries are excluded. This is a raster region check, not a guarantee for arbitrary OBS footage.

Browser tests also verify every canvas has an accessible label, computed text sizes are at least 17 stage pixels, and full Mind Share and ridge labels fit without overflow. Long-name coverage includes Time Travel. Five screenshots plus [transparent](screenshots/transparent.png) and [quarter-size](screenshots/quarter.png) captures are in [screenshots/](screenshots/).

## Deterministic film

Two fresh Chrome runs each captured 600 lossless frames over 20 virtual seconds at 30 output fps. Every PNG hash matched: **True**. Sequence SHA-256: `33d86c6405cf7b3b4d25b5d9a38507e07b15cee65adc29e239748aafb8612051`. [Full frame hashes](film-hashes.json).

## Reproduce

```sh
make check
python -m tools.measure_overlay
python -m tools.film --verify --output /tmp/nous.mp4
```

The scripts enable development fixtures only within their process. To view them separately: `NOUS_DEV_FIXTURES=1 nous demo --mock`, then open `/fixture.html?scene=war` (also attack, immune, telepathy, reveal). Use `backend=tiny` for captured random-init model states and text. No test downloads a browser, font, model or JavaScript dependency.

Not verified: trained-model visuals, hardware GPU performance, OBS composition over actual stream footage, and live Twitch viewing. The requested milestone geometry and 17 px minimum supersede SPEC §15's previous layout and type minimum.
