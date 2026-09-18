import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { loadAvatar, createScene } from './loader.js'
import { applyGesture, beginGestureTransition, safeGesture } from './gestures.js'
import { SpeechAmplitude } from './speech.js'
import { applyIdleLife, applySpeakingMotion } from './idle.js'
import Icon from '../components/Icon.jsx'

/**
 * The avatar canvas (T1.31/T1.32). Loads avatar.glb once, mounts a three.js
 * renderer, and runs a render loop that:
 *   - lerps every mapped bone toward the current `gesture` prop's target pose
 *   - overlays an amplitude-driven head pulse while `audioEl` is playing
 * Idles (gesture="idle") by default.
 */
export default function AvatarCanvas({ gesture = 'idle', audioEl = null,
                                       engaged = false }) {
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
      stateRef.current.bones = avatar.bones
      const { scene, camera } = createScene(avatar, width, height)

      // alpha, because createScene() leaves the scene background null and lets
      // the CSS gradient behind the canvas be the sky.
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
      renderer.setClearAlpha(0)
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

        // 1. the held gesture pose. 0.9s and smoothstepped, not 0.35s linear —
        //    a gesture arriving with the reply used to land as a lurch.
        stateRef.current.blend = Math.min(1, stateRef.current.blend + dt / 0.9)
        //    The attentive lean settles in over ~2.5s once engaged, so it
        //    reads as leaning in rather than flinching.
        const wantLean = stateRef.current.engaged ? 1 : 0
        const leanStep = dt / 2.5
        const lean = stateRef.current.lean ?? 0
        stateRef.current.lean = lean + Math.max(-leanStep,
          Math.min(leanStep, wantLean - lean))
        applyGesture(avatar.bones, avatar.restPose, stateRef.current.gesture ?? 'idle',
          stateRef.current.blend, t, stateRef.current.lean)

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

        stateRef.current.frames = (stateRef.current.frames ?? 0) + 1
        renderer.render(scene, camera)
        animId = requestAnimationFrame(tick)
      }
      tick()
      setStatus('ready')

      // Dev-only handle so the animation can be inspected from a test or the
      // console — proving the loop is actually driving bones, not just that
      // the canvas exists. Never referenced by application code.
      if (import.meta.env.DEV) {
        window.__cureva_avatar = {
          bones: avatar.bones,
          sample: () => {
            const h = avatar.bones.get('head')
            const c = avatar.bones.get('chest')
            return { headX: h?.quaternion.x ?? 0, headY: h?.quaternion.y ?? 0,
                     chestY: c?.position.y ?? 0, frames: stateRef.current.frames ?? 0 }
          },
        }
      }
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

  // A gesture change eases out of wherever the bones actually are right now,
  // rather than restarting from whatever the last interpolation left behind.
  useEffect(() => {
    const safe = safeGesture(gesture)
    if (stateRef.current.gesture !== safe) {
      stateRef.current.gesture = safe
      stateRef.current.blend = 0
      stateRef.current.bones && beginGestureTransition(stateRef.current.bones)
    }
  }, [gesture])

  useEffect(() => { stateRef.current.engaged = engaged }, [engaged])

  return (
    <div className="avatar-canvas-wrap">
      <div ref={mountRef} className="avatar-canvas-mount" />

      <span className="avatar-badge">
        <Icon name="user" size={12} />
        Atlas
      </span>

      {status === 'loading' && (
        <div className="avatar-status">
          <span className="ask-thinking"><i /><i /><i /></span> loading avatar…
        </div>
      )}
      {status === 'error' && (
        <div className="avatar-status avatar-status-error">
          <Icon name="alert" size={15} /> avatar failed to load
        </div>
      )}

      {speaking && (
        <span className="avatar-badge avatar-badge-right is-speaking">
          <span className="wave"><i /><i /><i /><i /><i /></span>
          speaking
        </span>
      )}

      {report && (
        <div className="avatar-report">
          {report.mappedCount} bones mapped · {report.animationCount === 0 ? 'procedural gestures' : `${report.animationCount} clips`}
        </div>
      )}
    </div>
  )
}
