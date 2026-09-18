import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { loadAvatar, createScene } from './loader.js'
import { applyGesture, safeGesture } from './gestures.js'
import { SpeechAmplitude } from './speech.js'
import { applyIdleLife, applySpeakingMotion } from './idle.js'

/**
 * The avatar canvas (T1.31/T1.32). Loads avatar.glb once, mounts a three.js
 * renderer, and runs a render loop that:
 *   - lerps every mapped bone toward the current `gesture` prop's target pose
 *   - overlays an amplitude-driven head pulse while `audioEl` is playing
 * Idles (gesture="idle") by default.
 */
export default function AvatarCanvas({ gesture = 'idle', audioEl = null }) {
  const mountRef = useRef(null)
  const stateRef = useRef({ blend: 0 })
  const [status, setStatus] = useState('loading')
  const [report, setReport] = useState(null)
  const [speaking, setSpeaking] = useState(false)

  useEffect(() => {
    let renderer, animId, avatar, speechAmp
    let disposed = false

    async function init() {
      const el = mountRef.current
      if (!el) return
      const width = el.clientWidth || 480
      const height = el.clientHeight || 480

      try {
        avatar = await loadAvatar('/avatar.glb')
      } catch (err) {
        console.error('avatar load failed', err)
        setStatus('error')
        return
      }
      if (disposed) return

      setReport(avatar.report)
      const { scene, camera } = createScene(avatar, width, height)

      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false })
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
      renderer.setSize(width, height)
      el.innerHTML = ''
      el.appendChild(renderer.domElement)

      if (audioEl) speechAmp = new SpeechAmplitude(audioEl)

      // THREE.Clock is deprecated in three r18x; performance.now() is what
      // it wrapped anyway and avoids the console warning on every mount.
      let last = performance.now()
      const started = last
      const tick = () => {
        const now = performance.now()
        const dt = Math.min(0.1, (now - last) / 1000)   // clamp after a tab switch
        const t = (now - started) / 1000
        last = now

        // 1. the held gesture pose, eased in over ~350ms rather than snapping
        stateRef.current.blend = Math.min(1, stateRef.current.blend + dt / 0.35)
        applyGesture(avatar.bones, avatar.restPose, stateRef.current.gesture ?? 'idle',
          stateRef.current.blend, t)

        // 2. breathing and weight shift — always, so she is never frozen
        applyIdleLife(avatar.bones, t)

        // 3. co-speech head/hand/torso motion while the reply is actually
        //    playing, driven by the speech envelope so it tracks the words
        let level = 0
        if (speechAmp && audioEl && !audioEl.paused) {
          speechAmp.resume()
          level = speechAmp.update()
        }
        // Ease the speaking layer out rather than cutting it dead the instant
        // the audio ends.
        stateRef.current.speech = (stateRef.current.speech ?? 0) * 0.88 + level * 0.12
        applySpeakingMotion(avatar.bones, stateRef.current.speech, t)
        setSpeaking(stateRef.current.speech > 0.04)

        renderer.render(scene, camera)
        animId = requestAnimationFrame(tick)
      }
      tick()
      setStatus('ready')
    }

    init()
    return () => {
      disposed = true
      if (animId) cancelAnimationFrame(animId)
      speechAmp?.dispose()
      renderer?.dispose()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Gesture changes reset the blend so the transition eases in again.
  useEffect(() => {
    const safe = safeGesture(gesture)
    if (stateRef.current.gesture !== safe) {
      stateRef.current.gesture = safe
      stateRef.current.blend = 0
    }
  }, [gesture])

  return (
    <div className="avatar-canvas-wrap">
      <div ref={mountRef} className="avatar-canvas-mount" />
      {status === 'loading' && <div className="avatar-status">loading avatar…</div>}
      {status === 'error' && <div className="avatar-status avatar-status-error">avatar failed to load</div>}
      {speaking && <div className="avatar-speaking">speaking</div>}
      {report && (
        <div className="avatar-report">
          {report.mappedCount} bones mapped · {report.animationCount === 0 ? 'procedural gestures' : `${report.animationCount} clips`}
        </div>
      )}
    </div>
  )
}
