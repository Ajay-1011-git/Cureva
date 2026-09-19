/**
 * Speech envelope + prosodic onset detection from the TTS audio (T1.31).
 *
 * Uses the Web Audio API's AnalyserNode against the reply audio element, per
 * cureva-stage1-trd.md/architecture doc's design. TalkingHead was evaluated
 * and rejected per the architecture doc (RPM-specific, not this rig); this
 * stays consistent with that — no TalkingHead dependency, though its measured
 * finger rotations were used as calibration data in hands.js.
 *
 * WHY THIS NOW REPORTS ONSETS AND NOT JUST A LEVEL
 * ------------------------------------------------
 * The old version returned one smoothed 0..1 amplitude, and the animation
 * multiplied sine waves by it. That is the wrong shape of signal for gesture,
 * and it is why the avatar read as wobbling rather than speaking: loudness is
 * continuous, but co-speech gesture is DISCRETE. People do not wave
 * proportionally to their own volume. They throw a short, sharp movement — a
 * beat — at prosodically prominent syllables, and hold still between them.
 *
 * So the analyser now reports two different things:
 *   - `level`, a smoothed envelope, for things that genuinely are continuous
 *     (how animated the posture is overall, how far the hands stay up).
 *   - `onset`, a discrete event fired on a rising edge of the fast envelope
 *     against its own recent baseline. That is the closest available proxy for
 *     a pitch accent without running full prosody analysis, and it is what
 *     gesture strokes get scheduled against in cospeech.js.
 *
 * Attack and release are deliberately asymmetric (fast attack, slow release):
 * a symmetric filter smears the syllable edges that the onset detector needs.
 */
import * as THREE from 'three'

const DEG = THREE.MathUtils.degToRad

/**
 * Minimum seconds between two detected onsets.
 *
 * Beat gestures in running speech top out around 4-5 per second; anything
 * faster is syllable-rate twitching, not gesture. 0.19s caps the detector at
 * roughly five per second and stops a single loud syllable registering as a
 * burst of beats across consecutive frames.
 */
const REFRACTORY = 0.19

export class SpeechAmplitude {
  constructor(audioEl) {
    this.audioEl = audioEl
    this.enabled = false
    this.level = 0        // slow, smoothed envelope (0..1)
    this.fast = 0         // fast envelope, follows syllable edges
    this.baseline = 0     // slow-moving floor the fast envelope is judged against
    this.onset = false    // true for exactly one frame when a beat is detected
    this.onsetStrength = 0
    this.sinceOnset = 99
    this.silentFor = 99   // seconds of continuous near-silence
    try {
      const AudioContextCtor = window.AudioContext || window.webkitAudioContext
      this.ctx = new AudioContextCtor()
      this.source = this.ctx.createMediaElementSource(audioEl)
      this.analyser = this.ctx.createAnalyser()
      this.analyser.fftSize = 512
      this.analyser.smoothingTimeConstant = 0.4
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

  /**
   * Advance the envelope one frame. Call once per render frame with dt.
   * Returns the smoothed level; `onset`/`onsetStrength` are read off `this`.
   */
  update(dt = 0.016) {
    this.onset = false
    this.onsetStrength = 0
    if (!this.enabled) return 0

    this.analyser.getByteTimeDomainData(this.data)
    let sumSquares = 0
    for (let i = 0; i < this.data.length; i++) {
      const v = (this.data[i] - 128) / 128
      sumSquares += v * v
    }
    const rms = Math.min(1, Math.sqrt(sumSquares / this.data.length) * 4)

    // Fast envelope: snaps up on an attack, falls away gently. The asymmetry
    // is the point — it preserves the leading edge of a stressed syllable,
    // which a symmetric smoother rounds off into nothing.
    const prevFast = this.fast
    const step = (tau) => 1 - Math.exp(-dt / tau)     // frame-rate independent
    this.fast = rms > this.fast
      ? this.fast + (rms - this.fast) * step(0.012)
      : this.fast + (rms - this.fast) * step(0.09)

    // Slow baseline: what "normal loudness" has been over the last second or
    // so. Judging onsets against this instead of a fixed threshold is what
    // keeps detection working for both a quiet and a loud delivery.
    this.baseline += (this.fast - this.baseline) * step(0.55)

    this.level = this.level + (rms - this.level) * step(0.11)

    this.sinceOnset += dt
    this.silentFor = this.level < 0.05 ? this.silentFor + dt : 0

    // An onset is a rising edge that clears the recent baseline by a margin.
    // All three conditions matter: `rising` rejects the decay side of a
    // syllable, the baseline margin rejects steady-state loudness, and the
    // absolute floor rejects room noise between phrases.
    const rising = this.fast > prevFast + 0.006
    const prominent = this.fast > this.baseline * 1.18 + 0.035
    if (rising && prominent && this.fast > 0.08 && this.sinceOnset > REFRACTORY) {
      this.onset = true
      // How much this peak stands out, not how loud it is — a strong beat in
      // quiet speech should still read as a strong beat.
      this.onsetStrength = Math.max(0, Math.min(1,
        (this.fast - this.baseline) * 2.6 + this.fast * 0.45))
      this.sinceOnset = 0
    }

    return this.level
  }

  dispose() {
    try { this.source?.disconnect(); this.analyser?.disconnect(); this.ctx?.close() }
    catch { /* already closed */ }
  }
}

/**
 * A stand-in speech envelope for when the real one is unavailable.
 *
 * This exists because gating ALL gesture on prosodic onsets turned out to be
 * far too brittle. Every one of these leaves the avatar completely still:
 *   - the backend is in degraded mode, so there is no reply audio at all
 *   - the browser's autoplay policy leaves the AudioContext suspended, so the
 *     analyser returns digital silence while the audio element claims to be
 *     playing
 *   - `createMediaElementSource` throws and lip-sync is disabled
 *   - the avatar-test page, which has no audio element by design
 * In each case the old behaviour was an avatar that breathed and did nothing
 * else, which is indistinguishable from the bug it was supposed to fix.
 *
 * So when we know she is speaking but cannot hear how, this generates beats on
 * a plausible syllable clock instead. The gesture is then correctly
 * phase-structured but NOT prosody-locked — strictly worse than the real
 * thing, and only ever a fallback. `isSynthetic` is exposed so callers can
 * tell the difference.
 */
export class SyntheticSpeech {
  constructor() {
    this.isSynthetic = true
    this.t = 0
    this.nextBeat = 0.2
    this.level = 0
    this.onset = false
    this.onsetStrength = 0
    this.silentFor = 99
  }

  update(dt, speaking) {
    this.onset = false
    this.onsetStrength = 0
    if (!speaking) {
      this.level *= 0.9
      this.silentFor += dt
      return this.level
    }
    this.silentFor = 0
    this.t += dt
    // A syllable-rate envelope so the continuous parts (posture, head motion)
    // still have something sensible to scale against.
    //
    // A raised cosine, NOT `abs(sin)`. Rectifying a sine puts a corner at every
    // zero crossing — three per second here — and this value scales head
    // rotation, so those corners came out as a rhythmic twitch of the head.
    // `0.5 - 0.5*cos` has the same shape and period with a continuous
    // derivative everywhere.
    this.level = 0.30 + 0.34 * (0.5 - 0.5 * Math.cos(this.t * Math.PI * 3.0))
    if (this.t >= this.nextBeat) {
      this.onset = true
      this.onsetStrength = 0.45 + Math.random() * 0.45
      // ~2.4-3.6 per second, jittered — a regular beat is its own tell.
      this.nextBeat = this.t + 0.28 + Math.random() * 0.14
    }
    return this.level
  }

  dispose() { /* nothing to release */ }
}

/** Apply the current amplitude as a small Head-bone rotation pulse, composed
 * on top of whatever gesture pose is already applied this frame.
 *
 * Kept for the case where the co-speech layer is disabled; the richer head
 * motion during speech lives in cospeech.js. This rig has no jaw bone and no
 * morph targets (see loader.js), so a head pulse remains the only available
 * proxy for mouth movement. */
export function applySpeechMotion(bones, level) {
  if (level <= 0.02) return
  const head = bones.get('head')
  if (!head) return
  const pulse = new THREE.Quaternion().setFromEuler(
    new THREE.Euler(-level * DEG(4), 0, 0))
  head.quaternion.multiply(pulse)
}
