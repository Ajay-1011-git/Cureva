import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { loadAvatar, createScene } from './loader.js'
import { applyGesture, beginGestureTransition, safeGesture } from './gestures.js'
import { SpeechAmplitude, SyntheticSpeech } from './speech.js'
import { applyIdleLife } from './idle.js'
import { createCoSpeechState, updateCoSpeech, applyCoSpeech } from './cospeech.js'
import Icon from '../components/Icon.jsx'

/**
 * The avatar canvas (T1.31/T1.32). Loads avatar.glb once, mounts a three.js
 * renderer, and runs a render loop that composes three layers, in this order,
 * each one multiplying onto what the previous wrote:
 *
 *   1. gestures.js  — the held pose for the current `gesture` prop
 *   2. idle.js      — breathing and weight shift, always running
 *   3. cospeech.js  — beat gestures of the arms and fingers while `audioEl`
 *                     is playing, driven by prosodic onsets in that audio
 *
 * Order matters: the co-speech layer is last because it owns the arms during
 * speech and writes the finger bones outright. Idles (gesture="idle") by
 * default, and with no `audioEl` layer 3 simply rests.
 */
export default function AvatarCanvas({ gesture = 'idle', audioEl = null,
                                       engaged = false, speaking = false }) {
  const mountRef = useRef(null)
  const stateRef = useRef({ blend: 0 })
  const [status, setStatus] = useState('loading')
  const [report, setReport] = useState(null)
  const [showSpeaking, setShowSpeaking] = useState(false)

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

      // The co-speech gesture state machine. Lives for the life of the canvas;
      // it carries phase, which hand is up and how far, across frames.
      const cs = createCoSpeechState()
      stateRef.current.cospeech = cs
      // Stand-in envelope for when the real one cannot be heard. See
      // SyntheticSpeech in speech.js for the four ways that happens.
      const synth = new SyntheticSpeech()

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

        // 2. breathing and weight shift — always, so she is never frozen.
        //    The idle arm swing yields as the arms come up to gesture, so the
        //    two layers don't fight over the same bones.
        applyIdleLife(avatar.bones, t, 1 - Math.min(1, cs.reach * 1.2))

        // 3. co-speech gesture: discrete beats keyed to prosodic onsets in the
        //    reply audio, with real preparation/stroke/hold/retraction phases.
        //    See cospeech.js for why this is not amplitude-driven wobble.
        //    Is she speaking at all? Either the reply audio is rolling, or the
        //    caller says so explicitly (the test harness, or a degraded turn
        //    with no audio to play).
        const audioRolling = !!(audioEl && !audioEl.paused && !audioEl.ended)
        const isSpeaking = audioRolling || stateRef.current.speakingProp

        //    Prefer the real envelope. But an audio element can be "playing"
        //    while the analyser returns digital silence — a suspended
        //    AudioContext under the autoplay policy does exactly that — so if
        //    no signal arrives for half a second while she is supposed to be
        //    talking, fall back rather than standing still.
        let env
        if (speechAmp?.enabled && audioRolling) {
          speechAmp.resume()
          const level = speechAmp.update(dt)
          stateRef.current.dead = level < 0.02
            ? (stateRef.current.dead ?? 0) + dt
            : 0
          env = stateRef.current.dead > 0.5
            ? null
            : { level, onset: speechAmp.onset,
                onsetStrength: speechAmp.onsetStrength,
                silentFor: speechAmp.silentFor }
        } else {
          stateRef.current.dead = 0
        }
        if (!env) {
          const level = synth.update(dt, isSpeaking)
          env = { level, onset: synth.onset, onsetStrength: synth.onsetStrength,
                  silentFor: synth.silentFor }
        }

        updateCoSpeech(cs, env, dt)
        applyCoSpeech(avatar.bones, avatar.restPose, cs, t)
        const level = env.level

        // Ease the badge out rather than flickering it off between syllables.
        stateRef.current.speech = (stateRef.current.speech ?? 0) * 0.88 + level * 0.12
        // Only touch React state when the flag actually flips. This ran every
        // frame; React bails out on an identical value, but around the
        // threshold it re-rendered continuously for no reason.
        const wantBadge = stateRef.current.speech > 0.04 || cs.reach > 0.05
        if (wantBadge !== stateRef.current.badge) {
          stateRef.current.badge = wantBadge
          setShowSpeaking(wantBadge)
        }

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
            // Finger sample too: proves the hand layer is actually driving
            // bones, which is the thing that was silently absent before.
            const f = avatar.bones.get('rightIndex2')
            return { headX: h?.quaternion.x ?? 0, headY: h?.quaternion.y ?? 0,
                     chestY: c?.position.y ?? 0, indexX: f?.quaternion.x ?? 0,
                     // Elbow flexion offset of whichever arm is gesturing —
                     // the quickest check that the co-speech layer is live.
                     elbowDeg: (() => {
                       const side = cs.hand === 'left' ? 'left' : 'right'
                       const b = avatar.bones.get(`${side}LowerArm`)
                       if (!b) return 0
                       return THREE.MathUtils.radToDeg(
                         new THREE.Euler().setFromQuaternion(b.quaternion).x)
                     })(),
                     phase: cs.phase, reach: cs.reach, hand: cs.hand,
                     shape: cs.shape, frames: stateRef.current.frames ?? 0 }
          },
          cospeech: cs,
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
  useEffect(() => { stateRef.current.speakingProp = speaking }, [speaking])

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

      {showSpeaking && (
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
