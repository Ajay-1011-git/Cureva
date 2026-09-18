/**
 * Amplitude-driven "talking" motion from TTS audio (T1.31 lip-sync
 * requirement). Uses the Web Audio API's AnalyserNode against the reply
 * audio element, per cureva-stage1-trd.md/architecture doc's design — but
 * drives a Head-bone rotation pulse rather than a jaw blendshape, because
 * this rig has neither a jaw bone nor any morph target (see loader.js's
 * module docstring for how that was confirmed). TalkingHead was evaluated
 * and rejected per the architecture doc (RPM-specific, not this rig either);
 * this stays consistent with that decision — no TalkingHead dependency here.
 */
import * as THREE from 'three'

const DEG = THREE.MathUtils.degToRad

export class SpeechAmplitude {
  constructor(audioEl) {
    this.audioEl = audioEl
    this.enabled = false
    this.level = 0
    try {
      const AudioContextCtor = window.AudioContext || window.webkitAudioContext
      this.ctx = new AudioContextCtor()
      this.source = this.ctx.createMediaElementSource(audioEl)
      this.analyser = this.ctx.createAnalyser()
      this.analyser.fftSize = 256
      this.source.connect(this.analyser)
      this.analyser.connect(this.ctx.destination)
      this.data = new Uint8Array(this.analyser.frequencyBinCount)
      this.enabled = true
    } catch (err) {
      // Web Audio can fail (autoplay policy, unsupported browser). Degrades
      // to a still avatar rather than throwing — never blocks the reply from
      // playing normally.
      console.warn('SpeechAmplitude: Web Audio unavailable, lip-sync disabled', err)
      this.enabled = false
    }
  }

  resume() {
    if (this.ctx && this.ctx.state === 'suspended') this.ctx.resume()
  }

  /** 0..1 current amplitude, smoothed. Call once per render frame. */
  update() {
    if (!this.enabled) return 0
    this.analyser.getByteTimeDomainData(this.data)
    let sumSquares = 0
    for (let i = 0; i < this.data.length; i++) {
      const v = (this.data[i] - 128) / 128
      sumSquares += v * v
    }
    const rms = Math.sqrt(sumSquares / this.data.length)
    this.level = this.level * 0.6 + Math.min(1, rms * 4) * 0.4    // smoothed
    return this.level
  }

  dispose() {
    try { this.source?.disconnect(); this.analyser?.disconnect(); this.ctx?.close() }
    catch { /* already closed */ }
  }
}

/** Apply the current amplitude as a small Head-bone rotation pulse, composed
 * on top of whatever gesture pose is already applied this frame. */
export function applySpeechMotion(bones, level) {
  if (level <= 0.02) return
  const head = bones.get('head')
  if (!head) return
  const pulse = new THREE.Quaternion().setFromEuler(
    new THREE.Euler(-level * DEG(4), 0, 0))
  head.quaternion.multiply(pulse)
}
