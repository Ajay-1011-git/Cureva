import { useMemo, useState } from 'react'
import Icon from '../../components/Icon.jsx'

/**
 * The forecast fan chart (T3.22).
 *
 * **The bands are real simulation output, not a curve drawn from the rate.**
 * `ForecastResult` ships `band_no_action`/`band_intervention` — the 10th, 50th
 * and 90th percentile of the cumulative deviation count across every rollout
 * that actually ran, at every remaining cut. Synthesising a spread here from
 * `rate_per_cut` would have been a picture of an assumption rather than of the
 * simulation, and the two are not the same claim.
 *
 * Form: one fan, one comparison line, one threshold. The no-action spread is
 * the subject, so it gets the band; drawing a second fan for the intervention
 * case would put two translucent shapes on top of each other and make both
 * unreadable. The intervention appears as its median line alone — emphasis,
 * not a second full series.
 *
 * Colour (validated, not eyeballed — the palette validator reports
 * ΔE 31.1 deutan / 35.8 normal between the two series, all checks pass):
 *   no-action    --cat-treatment  indigo   the path being warned about
 *   intervention --cat-integrity  green    the path if the site is visited
 *   threshold    --cat-safety     red      a limit, dashed AND labelled, so it
 *                                          is never carried by colour alone
 *
 * The validator warns that the green sits below 3:1 against white, which
 * obliges relief rather than a shrug: both series are direct-labelled at the
 * line end, and the whole chart has a table view carrying the same numbers.
 *
 * The assumptions render underneath, always, in full. NFR-3 applies to the
 * page and not only to the payload — a probability whose assumptions are one
 * hover away is a probability most people will read as a fact.
 */

// `right` holds the end labels. 92px was too narrow: "breach at 21" rendered
// past the viewBox edge, which the browser clips silently.
const PAD = { top: 18, right: 124, bottom: 38, left: 46 }
const W = 720
const H = 300
const LABEL_GAP = 13          // minimum vertical space between two end labels

function niceStep(value) {
  // A step a person would have chosen. Picking `yMax / 4` gave ticks of
  // 0, 13, 25, 38, 50 on the real S09 forecast — arithmetically correct and
  // unreadable, because nobody labels an axis in twelve-and-a-halves.
  const raw = value / 4
  const magnitude = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 1))))
  return [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= raw)
    || 10 * magnitude
}

/** Nudge labels apart so two that land on the same line stay readable. */
function spread(labels) {
  const sorted = [...labels].sort((a, b) => a.y - b.y)
  for (let i = 1; i < sorted.length; i += 1) {
    const gap = sorted[i].y - sorted[i - 1].y
    if (gap < LABEL_GAP) sorted[i].y = sorted[i - 1].y + LABEL_GAP
  }
  return labels
}

export default function ForecastChart({ rows }) {
  const [siteKey, setSiteKey] = useState(null)
  const [asTable, setAsTable] = useState(false)
  const [hover, setHover] = useState(null)

  // One row per site: the escalation carrying that site's highest-risk
  // forecast. A site with six escalations has one forecast; showing it six
  // times would imply six findings where there is one.
  const bySite = useMemo(() => {
    const out = new Map()
    for (const row of rows || []) {
      const key = row.site || 'study-wide'
      const seen = out.get(key)
      if (!seen || row.forecast.breach_probability > seen.forecast.breach_probability) {
        out.set(key, row)
      }
    }
    return [...out.values()].sort(
      (a, b) => b.forecast.breach_probability - a.forecast.breach_probability)
  }, [rows])

  const active = bySite.find((r) => (r.site || 'study-wide') === siteKey) || bySite[0]

  if (!active) {
    return (
      <div className="card watch-empty">
        <Icon name="pulse" size={18} />
        <p className="t-body">
          No forecast yet. Run the period — a forecast is produced only for a
          site that actually had an escalation put to the medical monitor, so
          there is nothing to draw until then.
        </p>
      </div>
    )
  }

  const f = active.forecast
  const cuts = f.band_cuts || []
  const band = f.band_no_action || {}
  const interv = f.band_intervention || {}
  const hasBands = cuts.length > 0 && Array.isArray(band.p50) && band.p50.length === cuts.length

  const rawMax = Math.max(
    f.breach_threshold || 0,
    ...(band.p90 || [0]),
    ...(interv.p90 || [0]),
  ) * 1.08
  const step = niceStep(rawMax)
  const yMax = Math.max(step, Math.ceil(rawMax / step) * step)

  const plotW = W - PAD.left - PAD.right
  const plotH = H - PAD.top - PAD.bottom
  const x = (i) => PAD.left + (cuts.length === 1 ? plotW / 2 : (i / (cuts.length - 1)) * plotW)
  const y = (v) => PAD.top + plotH - (Math.min(v, yMax) / yMax) * plotH

  const line = (series) => series.map((v, i) => `${i ? 'L' : 'M'}${x(i)},${y(v)}`).join(' ')
  const area = (lo, hi) => [
    ...hi.map((v, i) => `${i ? 'L' : 'M'}${x(i)},${y(v)}`),
    ...lo.map((v, i) => `L${x(lo.length - 1 - i)},${y(lo[lo.length - 1 - i])}`).slice(1),
    'Z',
  ].join(' ')

  const ticks = []
  for (let v = 0; v <= yMax + 1e-9; v += step) ticks.push(Number(v.toFixed(2)))

  // The three right-hand labels are positioned from their own series, so on a
  // forecast where the intervention line happens to sit near the threshold
  // they land on top of each other — measured at 9.8px apart on the real S09
  // data. Nudged apart here rather than left to overlap.
  const hasInterv = Array.isArray(interv.p50) && interv.p50.length === cuts.length
  const endLabels = spread([
    { key: 'noaction', text: 'no action', cls: 'wc-endlabel-noaction',
      y: y(band.p50[band.p50.length - 1]) + 4 },
    ...(hasInterv ? [{ key: 'interv', text: 'intervene', cls: 'wc-endlabel-interv',
      y: y(interv.p50[interv.p50.length - 1]) + 4 }] : []),
    { key: 'threshold', text: `breach at ${f.breach_threshold}`,
      cls: 'wc-threshold-label', y: y(f.breach_threshold) + 4 },
  ])

  return (
    <div className="watch-forecast">
      <div className="watch-toolbar">
        <div className="watch-sitepicker" role="tablist" aria-label="Site">
          {bySite.slice(0, 8).map((row) => {
            const key = row.site || 'study-wide'
            const on = key === (active.site || 'study-wide')
            return (
              <button key={key} role="tab" aria-selected={on}
                      className={`watch-sitetab${on ? ' is-on' : ''}`}
                      onClick={() => setSiteKey(key)}>
                {key}
                <span className="watch-sitetab-p">
                  {Math.round(row.forecast.breach_probability * 100)}%
                </span>
              </button>
            )
          })}
        </div>
        <span className="u-grow" />
        <button className="btn btn-ghost btn-sm" onClick={() => setAsTable((v) => !v)}>
          <Icon name={asTable ? 'graph' : 'layers'} size={14} />
          {asTable ? 'Show chart' : 'Show numbers'}
        </button>
      </div>

      <div className="watch-headline">
        <strong>{active.site || 'Study-wide'}</strong> — {f.headline ?? active.headline}
        <div className="watch-figures">
          <span><b>{Math.round(f.breach_probability * 100)}%</b> if nothing changes</span>
          <span><b>{Math.round(f.breach_probability_with_intervention * 100)}%</b> after intervening</span>
          <span>
            {f.median_breach_cut != null
              ? <>typically breaching around <b>cut {f.median_breach_cut}</b></>
              : <>no simulated rollout reached the threshold</>}
          </span>
          <span className="t-quiet">{f.rollouts_run} rollouts · rate {f.rate_per_cut}/cut</span>
        </div>
      </div>

      {!hasBands && (
        <div className="notice notice-warn">
          <Icon name="alert" size={15} />
          <span>This forecast carries no simulated trajectories, so no fan is
            drawn. The figures above still hold.</span>
        </div>
      )}

      {hasBands && !asTable && (
        <figure className="watch-chart">
          <svg viewBox={`0 0 ${W} ${H}`} role="img"
               aria-label={`Simulated cumulative protocol deviations for ${active.site || 'the study'} from cut ${cuts[0]} to ${cuts[cuts.length - 1]}, with a breach threshold of ${f.breach_threshold}.`}
               onMouseLeave={() => setHover(null)}>
            {/* grid — recessive, behind everything */}
            {ticks.map((t) => (
              <g key={t}>
                <line className="wc-grid" x1={PAD.left} x2={W - PAD.right}
                      y1={y(t)} y2={y(t)} />
                <text className="wc-tick" x={PAD.left - 8} y={y(t) + 4}
                      textAnchor="end">{t}</text>
              </g>
            ))}
            {cuts.map((c, i) => (
              <text key={c} className="wc-tick" x={x(i)} y={H - PAD.bottom + 18}
                    textAnchor="middle">cut {c}</text>
            ))}

            {/* the fan: p10–p90 of the no-action rollouts */}
            <path className="wc-band" d={area(band.p10, band.p90)} />

            {/* the threshold: a limit, dashed and labelled */}
            <line className="wc-threshold" x1={PAD.left} x2={W - PAD.right}
                  y1={y(f.breach_threshold)} y2={y(f.breach_threshold)} />


            {/* medians */}
            <path className="wc-line wc-line-noaction" d={line(band.p50)} />
            {hasInterv && <path className="wc-line wc-line-interv" d={line(interv.p50)} />}

            {/* direct labels — the relief the contrast warning obliges */}
            {endLabels.map((l) => (
              <text key={l.key} className={`wc-endlabel ${l.cls}`}
                    x={W - PAD.right + 8} y={l.y}>{l.text}</text>
            ))}

            {/* hover targets, wider than the marks they select */}
            {cuts.map((c, i) => (
              <rect key={c} className="wc-hit" x={x(i) - plotW / (2 * Math.max(1, cuts.length - 1))}
                    y={PAD.top} width={plotW / Math.max(1, cuts.length - 1)} height={plotH}
                    onMouseEnter={() => setHover(i)} />
            ))}
            {hover != null && (
              <g className="wc-cross">
                <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + plotH} />
                <circle cx={x(hover)} cy={y(band.p50[hover])} r="4.5"
                        className="wc-dot wc-dot-noaction" />
                {hasInterv && (
                  <circle cx={x(hover)} cy={y(interv.p50[hover])} r="4.5"
                          className="wc-dot wc-dot-interv" />
                )}
              </g>
            )}
          </svg>

          {hover != null && (
            <div className="wc-tip" style={{ left: `${(x(hover) / W) * 100}%` }}>
              <div className="wc-tip-head">cut {cuts[hover]}</div>
              <div className="wc-tip-row">
                <i className="wc-swatch wc-swatch-noaction" />no action
                <b>{band.p50[hover]}</b>
                <span className="t-quiet">({band.p10[hover]}–{band.p90[hover]})</span>
              </div>
              {Array.isArray(interv.p50) && (
                <div className="wc-tip-row">
                  <i className="wc-swatch wc-swatch-interv" />intervene
                  <b>{interv.p50[hover]}</b>
                  <span className="t-quiet">({interv.p10[hover]}–{interv.p90[hover]})</span>
                </div>
              )}
            </div>
          )}

          <figcaption className="wc-legend">
            <span><i className="wc-swatch wc-swatch-noaction" />No action — median, shaded 10th–90th percentile</span>
            <span><i className="wc-swatch wc-swatch-interv" />After intervention — median</span>
            <span><i className="wc-swatch wc-swatch-threshold" />Breach threshold</span>
          </figcaption>
        </figure>
      )}

      {hasBands && asTable && (
        <div className="u-scroll">
          <table className="watch-table">
            <caption className="t-caption">
              Simulated cumulative deviations for {active.site || 'the study'},
              from {f.rollouts_run} rollouts. Median with 10th–90th percentile.
            </caption>
            <thead>
              <tr><th>Cut</th><th>No action</th><th>After intervention</th><th>Threshold</th></tr>
            </thead>
            <tbody>
              {cuts.map((c, i) => (
                <tr key={c}>
                  <td>{c}</td>
                  <td>{band.p50[i]} <span className="t-quiet">({band.p10[i]}–{band.p90[i]})</span></td>
                  <td>{interv.p50?.[i] ?? '—'} <span className="t-quiet">
                    {interv.p10 ? `(${interv.p10[i]}–${interv.p90[i]})` : ''}</span></td>
                  <td>{f.breach_threshold}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Always on screen, never behind a hover. */}
      <div className="watch-assumptions">
        <h4 className="t-eyebrow"><Icon name="alert" size={13} /> What this forecast assumes</h4>
        <ul>
          {(f.assumptions || []).map((a, i) => <li key={i} className="t-body-sm">{a}</li>)}
        </ul>
        <p className="t-caption t-quiet">
          Attached to escalation <span className="t-mono">{active.escalation_id}</span>
          {' '}({active.code}), put to the medical monitor at cut {active.asked_cut}
          {' '}and answered <strong>{active.decision}</strong>. A forecast is only ever
          produced for a decision someone actually had to make.
        </p>
      </div>
    </div>
  )
}
