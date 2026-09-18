import { useState } from 'react'
import AvatarCanvas from '../avatar/AvatarCanvas.jsx'

/** Temporary test harness page for T1.31's VERIFY. Removed / folded into
 * Atlas.jsx proper at T1.32. */
export default function AvatarTest() {
  const [gesture, setGesture] = useState('idle')
  return (
    <div>
      <h1>Avatar test</h1>
      <AvatarCanvas gesture={gesture} />
      <div style={{ marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {['idle', 'listening', 'concern_lean_in', 'explaining_gesture', 'reassure_nod', 'farewell_wave'].map(g => (
          <button key={g} data-gesture-btn={g} onClick={() => setGesture(g)}>{g}</button>
        ))}
      </div>
      <div data-current-gesture>{gesture}</div>
    </div>
  )
}
