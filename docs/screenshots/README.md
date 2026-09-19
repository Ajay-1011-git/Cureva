# Screenshots

## What is here

- **`forecast-fan-chart.svg` / `.png`** — the Act 4 fan chart, generated from
  a real period walk by `tests/frontend/check_forecast_chart.mjs`, which mirrors
  `ForecastChart.jsx`'s scales exactly and re-renders them over the real
  `forecast_view()` rows. It is the chart the page draws, not a mockup: site
  S09, breach threshold 21, the no-action median crossing it around cut 10
  while the intervention median stays below.

  That harness is also a layout test. It checks all 125 real forecast rows for
  points outside the plot box, clipped bands, colliding end labels, labels
  overflowing the viewBox, and non-integer axis ticks. It found four of those on
  the first run and they were fixed before this image was made.

## What is NOT here, and why

**No page screenshots.** They were not captured in the build environment, which
had no browser. Rather than ship an approximation of a page nobody looked at,
this file says so.

To capture them, with the backend and frontend running:

```bash
uvicorn webapp.server:app                 # terminal 1
cd webapp/frontend && npm run dev         # terminal 2
```

Then capture, at 1280×800 or wider:

| File | Page | What must be visible |
|---|---|---|
| `atlas.png` | `/atlas` | an answer with its cited records |
| `monitor-cycle.png` | `/monitor` | one cut's findings, split escalation-worthy vs watch-only |
| `monitor-gate.png` | `/monitor` | the human gate with a pending escalation |
| `watch-stats.png` | `/watch` | the stat row after a full period — including **0 tokens spent** |
| `watch-forecast.png` | `/watch` | the fan chart **with its assumptions block in frame** |
| `watch-artifacts.png` | `/watch` | one drafted memo, `template only` tag visible |
| `watch-explain.png` | `/watch` | the explain drawer, raw trace lines visible |
| `watch-report.png` | `/watch` | the report's opening — the four cross-cut findings |

Two of these are the point rather than decoration: `watch-forecast.png` must
show the assumptions (a probability whose assumptions are off-screen reads as a
fact), and `watch-explain.png` must show the raw trace lines (the claim is that
the answer *is* the file, so the file has to be in the picture).
