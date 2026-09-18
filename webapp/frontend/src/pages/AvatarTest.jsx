import { useState } from 'react'
import AvatarCanvas from '../avatar/AvatarCanvas.jsx'

const GESTURES = ['idle', 'listening', 'concern_lean_in', 'explaining_gesture',
                  'reassure_nod', 'farewell_wave']

/** Temporary test harness page for T1.31's VERIFY. Kept because the automated
 *  check drives it by `data-gesture-btn`; styled with the shared primitives so
 *  it does not sit in the app looking like a different product. */
export default function AvatarTest() {
  const [gesture, setGesture] = useState('idle')
  return (
    <div className="page-body">
      <div className="l-page">
        <div className="col-head">
          <h2>Avatar test harness</h2>
          <p>Drives each gesture directly, without a backend turn.</p>
        </div>
        <div className="card avatar-card" style={{ maxWidth: 460 }}>
          <AvatarCanvas gesture={gesture} />
        </div>
        <div className="u-row" style={{ marginTop: 16 }}>
          {GESTURES.map((g) => (
            <button key={g} className={`btn btn-sm ${g === gesture ? 'btn-primary' : 'btn-ghost'}`}
                    data-gesture-btn={g} onClick={() => setGesture(g)}>
              {g.replace(/_/g, ' ')}
            </button>
          ))}
        </div>
        <div className="t-caption t-quiet" style={{ marginTop: 12 }} data-current-gesture>
          {gesture}
        </div>
      </div>
    </div>
  )
}
