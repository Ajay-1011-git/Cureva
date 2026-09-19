/**
 * Geometry check for the forecast fan chart (T3.22).
 *
 * The palette validator checks colour; it does not check layout. This mirrors
 * `ForecastChart.jsx`'s scales exactly, runs them over REAL forecast rows from
 * a real period walk, and asserts the things that can only go wrong on screen:
 * points outside the plot box, a band clipped by the axis top, end labels
 * landing on top of each other, labels overflowing the viewBox, and axis ticks
 * that are not whole numbers.
 *
 * It caught all four of those on the first real dataset. It also writes
 * /tmp/chart.svg, which can be rasterised (`qlmanage -t -s 1400 -o /tmp`) and
 * looked at — which is how those four were confirmed by eye as well.
 *
 *   node tests/frontend/check_forecast_chart.mjs [rows.json]
 *
 * Regenerate the rows with:
 *   StudyWatch(...).run_period(); json.dump(watch.forecast_view(), ...)
 */
import fs from 'fs'
const src = process.argv[2] || '/tmp/forecast_rows.json'
if (!fs.existsSync(src)) {
  console.error(`no forecast rows at ${src} — generate them from a real run_period() first`)
  process.exit(2)
}
const rows = JSON.parse(fs.readFileSync(src,'utf8'))
// Same geometry constants as ForecastChart.jsx
const PAD={top:18,right:124,bottom:38,left:46}, W=720, H=300
const PADR=124, LABEL_GAP=13
const niceStep=v=>{const raw=v/4,m=Math.pow(10,Math.floor(Math.log10(Math.max(raw,1))))
  return [1,2,2.5,5,10].map(k=>k*m).find(s=>s>=raw)||10*m}
const spread=L=>{const s=[...L].sort((a,b)=>a.y-b.y)
  for(let i=1;i<s.length;i++){if(s[i].y-s[i-1].y<LABEL_GAP)s[i].y=s[i-1].y+LABEL_GAP}
  return L}
const T={treatment:'#4a3aa7',integrity:'#1baf7a',safety:'#c62828',
         hairSoft:'#e6e6ee',slate:'#8b8b8b',paper:'#ffffff',ink:'#151515'}

function chart(row){
  const f=row.forecast, cuts=f.band_cuts, b=f.band_no_action, iv=f.band_intervention
  const rawMax=Math.max(f.breach_threshold,...b.p90,...iv.p90)*1.08
  const step=niceStep(rawMax)
  const yMax=Math.max(step,Math.ceil(rawMax/step)*step)
  const plotW=W-PAD.left-PAD.right, plotH=H-PAD.top-PAD.bottom
  const x=i=>PAD.left+(cuts.length===1?plotW/2:(i/(cuts.length-1))*plotW)
  const y=v=>PAD.top+plotH-(Math.min(v,yMax)/yMax)*plotH
  const line=s=>s.map((v,i)=>`${i?'L':'M'}${x(i)},${y(v)}`).join(' ')
  const area=(lo,hi)=>[...hi.map((v,i)=>`${i?'L':'M'}${x(i)},${y(v)}`),
    ...lo.map((v,i)=>`L${x(lo.length-1-i)},${y(lo[lo.length-1-i])}`).slice(1),'Z'].join(' ')
  const ticks=[];for(let v=0;v<=yMax+1e-9;v+=step)ticks.push(Number(v.toFixed(2)))
  const endLabels=spread([
    {t:'no action',c:T.treatment,y:y(b.p50.at(-1))+4},
    {t:'intervene',c:T.integrity,y:y(iv.p50.at(-1))+4},
    {t:`breach at ${f.breach_threshold}`,c:T.safety,y:y(f.breach_threshold)+4}])
  return {ticks,endLabels,svg:`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">
<rect width="${W}" height="${H}" fill="${T.paper}"/>
<style>text{font-family:-apple-system,Helvetica,sans-serif}</style>
${ticks.map(t=>`<line x1="${PAD.left}" x2="${W-PAD.right}" y1="${y(t)}" y2="${y(t)}" stroke="${T.hairSoft}"/>
<text x="${PAD.left-8}" y="${y(t)+4}" text-anchor="end" font-size="11" fill="${T.slate}">${t}</text>`).join('')}
${cuts.map((c,i)=>`<text x="${x(i)}" y="${H-PAD.bottom+18}" text-anchor="middle" font-size="11" fill="${T.slate}">cut ${c}</text>`).join('')}
<path d="${area(b.p10,b.p90)}" fill="${T.treatment}" opacity="0.14"/>
<line x1="${PAD.left}" x2="${W-PAD.right}" y1="${y(f.breach_threshold)}" y2="${y(f.breach_threshold)}" stroke="${T.safety}" stroke-width="1.5" stroke-dasharray="5 4"/>
<path d="${line(b.p50)}" fill="none" stroke="${T.treatment}" stroke-width="2" stroke-linecap="round"/>
<path d="${line(iv.p50)}" fill="none" stroke="${T.integrity}" stroke-width="2" stroke-linecap="round"/>
${endLabels.map(l=>`<text x="${W-PAD.right+8}" y="${l.y}" font-size="11" font-weight="600" fill="${l.c}">${l.t}</text>`).join('')}
<text x="${PAD.left}" y="${H-6}" font-size="11" fill="${T.slate}">■ no action (10th–90th pct)   ■ after intervention   ┄ breach threshold</text>
</svg>`, yMax, y, x, f, cuts, b, iv}
}

let failures=0
for (const r of rows) {
  const c=chart(r)
  const probs=check(r,c)
  if (probs.length) {
    failures+=1
    console.log(`FAIL ${r.site||'study'} — ${probs.join('; ')}`)
  }
}
const row=rows[0]
const {svg,yMax,y,f,cuts,b,iv,ticks,endLabels}=chart(row)
fs.writeFileSync('/tmp/chart.svg',svg)

function check(row,{yMax,y,f,cuts,b,iv,ticks,endLabels}){
  const plotTop=PAD.top, plotBot=H-PAD.bottom, out=[]
  const all=[...b.p10,...b.p50,...b.p90,...iv.p50,f.breach_threshold]
  if(!all.every(v=>y(v)>=plotTop-0.01&&y(v)<=plotBot+0.01)) out.push('a point falls outside the plot box')
  if(yMax<Math.max(...b.p90)) out.push('yMax clips the p90 band')
  const ys=endLabels.map(l=>l.y)
  for(let i=0;i<ys.length;i++)for(let j=i+1;j<ys.length;j++)
    if(Math.abs(ys[i]-ys[j])<12) out.push(`end labels collide (${Math.abs(ys[i]-ys[j]).toFixed(1)}px)`)
  const widest=Math.max(...endLabels.map(l=>l.t.length))*6.2
  if(W-PAD.right+8+widest>W) out.push(`right labels overflow by ${(W-PAD.right+8+widest-W).toFixed(0)}px`)
  if(ticks.some(t=>Math.abs(t-Math.round(t))>1e-9)) out.push('axis ticks are not whole numbers')
  if(b.p50.some((v,i)=>v<b.p10[i]||v>b.p90[i])) out.push('median falls outside its own p10-p90 band')
  return out
}

// --- geometry checks the validator does NOT cover (step 7) ---
const plotTop=PAD.top, plotBot=H-PAD.bottom
const all=[...b.p10,...b.p50,...b.p90,...iv.p50,f.breach_threshold]
const issues=[]
if(!all.every(v=>y(v)>=plotTop-0.01&&y(v)<=plotBot+0.01)) issues.push('a point falls outside the plot box')
if(yMax<Math.max(...b.p90)) issues.push('yMax clips the p90 band')
const labelYs=endLabels.map(l=>l.y)
const pairs=[[0,1],[0,2],[1,2]]
pairs.forEach(([i,j])=>{ if(Math.abs(labelYs[i]-labelYs[j])<12) issues.push(`end labels ${i}/${j} collide (${Math.abs(labelYs[i]-labelYs[j]).toFixed(1)}px apart)`) })
if(ticks.some(t=>Math.abs(t-Math.round(t))>1e-9)) issues.push('axis ticks are not whole numbers')
const widest=Math.max(...endLabels.map(l=>l.t.length))*6.2
if(W-PAD.right+8+widest>W) issues.push(`right labels overflow the viewBox by ${(W-PAD.right+8+widest-W).toFixed(0)}px`)
console.log(`site ${row.site}  threshold ${f.breach_threshold}  yMax ${yMax}  cuts ${cuts.join(',')}`)
console.log(`p90 top value ${Math.max(...b.p90)} -> y=${y(Math.max(...b.p90)).toFixed(1)} (plot ${plotTop}..${plotBot})`)
console.log(`ticks: ${ticks.join(', ')}`)
console.log(`end-label y: ${endLabels.map(l=>`${l.t} ${l.y.toFixed(1)}`).join(' | ')}`)
console.log(issues.length?`GEOMETRY ISSUES:\n  - ${issues.join('\n  - ')}`:'geometry OK (sample row)')
console.log(`\n${rows.length} forecast row(s) checked, ${failures} with layout problems`)
console.log(failures? 'FAIL' : 'ALL PASS')
process.exit(failures?1:0)
