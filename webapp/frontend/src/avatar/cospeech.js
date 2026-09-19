/**
 * Co-speech gesture — the arms, elbows, wrists and hands while she is talking.
 *
 * WHAT WAS WRONG BEFORE
 * ---------------------
 * Two generations of wrong, worth recording so neither comes back:
 *
 *  1. Sine waves times audio amplitude. Every joint moved continuously, in
 *     phase, for exactly as long as there was sound. That is swaying, not
 *     speaking.
 *  2. Then: real gesture PHASES, but the arm still moved as a rigid unit. The
 *     elbow never folded, the wrist never broke, and the forearm never rotated,
 *     so she swung a plank from the shoulder. Better timing, same mannequin.
 *
 * This version poses the arm ANATOMICALLY — shoulder flexion/abduction, elbow
 * flexion, forearm pronation/supination, wrist flexion and deviation — instead
 * of writing raw Euler offsets per bone and hoping.
 *
 * THE RIG MAPPING, MEASURED NOT ASSUMED
 * -------------------------------------
 * Anatomical angles are converted to this rig's local-axis rotations through
 * AXES below. Every entry was measured by perturbing one bone axis at a time
 * from the relaxed base and observing what actually moved (elbow angle, hand
 * displacement along the body's own forward/lateral/up axes, palm normal). The
 * non-obvious results:
 *
 *  - Shoulder ABDUCTION is -X on BOTH arms; it is NOT mirrored, unlike
 *    shoulder flexion (-Z right, +Z left). Mirroring it flings one arm across
 *    the body.
 *  - Forearm twist is ForeArm.Y and is perfectly clean: +-25 deg there changes
 *    elbow flexion by 0.0 deg and moves the hand 0mm, while rotating the palm
 *    the full 25 deg. Supination is +Y right, -Y left.
 *  - Wrist axial rotation is NOT used, because at a real wrist it barely
 *    exists — forearm rotation is what turns the palm over. Hand.Y does rotate
 *    on this rig, but using it would be faking anatomy the ForeArm already has.
 *  - ForeArm.Z is deliberately unused: it flexes the elbow 22 deg on the left
 *    arm but only 1.8 deg on the right, i.e. it is contaminated by the rig's
 *    asymmetric rest pose. ForeArm.X is clean and symmetric on both arms.
 *
 * The relaxed base stance already sits at 15.9 deg of elbow flexion with the
 * palms fully medial, so every angle below is converted to a DELTA from that.
 *
 * TIMING IS THE THING THAT MATTERS MOST
 * -------------------------------------
 * Phase durations here are measured values, not taste, and they are much
 * slower than the previous guesses (a 170ms stroke became ~340ms):
 *   - preparation begins ~753ms before its lexical affiliate, the stroke ~227ms
 *     before it, so preparation runs roughly 500ms
 *   - the active gesture phase averages ~340ms
 *   - post-stroke holds run ~570ms; holds overall average ~545ms
 *   - the gesture apex is tightly locked to the pitch peak
 * A live stream cannot see a word coming, so the honest approximation is to
 * start preparation on the rising edge of a prominent syllable and land the
 * apex inside it; what matters for realism is the phase DURATIONS, which are
 * used as measured.
 *
 * Numbers without a measured source — wrist flick amplitude, inter-joint lag in
 * conversation, how much the non-gesturing arm moves, rest dwell — are marked
 * TUNABLE where they appear. They are honest guesses, not findings.
 */
import * as THREE from 'three'
import { HAND_SHAPES, blendShapes, applyHandShape } from './hands.js'

const DEG = THREE.MathUtils.degToRad

/**
 * Anatomy already present in the relaxed base stance, measured on this rig.
 * Every gesture angle below is an ABSOLUTE anatomical target, so these get
 * subtracted to find the delta to apply. Treating the targets as deltas
 * instead doubles every shoulder angle — the arms end up over her head.
 */
const BASE_ELBOW = 15.9
const BASE_SH_FLEX = 33.1
const BASE_SH_ABD = 13.1

/**
 * Anatomical angle -> (bone, local axis, sign). See the module note; these are
 * measurements of this specific rig, not a convention.
 *
 * `gain` corrects for a rotation that does not map 1:1 onto the anatomical
 * angle: 25 deg applied to ForeArm.X yields 22 deg of actual elbow flexion.
 */
const AXES = {
  right: {
    shoulderFlex: { bone: 'rightUpperArm', axis: 'z', sign: -1, gain: 1.00 },
    shoulderAbd:  { bone: 'rightUpperArm', axis: 'x', sign: -1, gain: 1.00 },
    // 1.06, not the 1.14 implied by the small-angle probe: the rotation-to-
    // flexion mapping is not linear, and at the 60-90 deg angles gestures
    // actually use, 1.14 overshot every target by a consistent ~4.5 deg.
    // Calibrated by posing each gesture and measuring the result.
    elbow:        { bone: 'rightLowerArm', axis: 'x', sign: +1, gain: 1.06 },
    twist:        { bone: 'rightLowerArm', axis: 'y', sign: +1, gain: 1.0 },
    wristFlex:    { bone: 'rightHand',     axis: 'x', sign: +1, gain: 1.0 },
    wristUlnar:   { bone: 'rightHand',     axis: 'z', sign: +1, gain: 1.0 },
  },
  left: {
    shoulderFlex: { bone: 'leftUpperArm',  axis: 'z', sign: +1, gain: 1.00 },
    // NOT mirrored — measured -X on both arms.
    shoulderAbd:  { bone: 'leftUpperArm',  axis: 'x', sign: -1, gain: 1.00 },
    elbow:        { bone: 'leftLowerArm',  axis: 'x', sign: +1, gain: 1.06 },
    twist:        { bone: 'leftLowerArm',  axis: 'y', sign: -1, gain: 1.0 },
    wristFlex:    { bone: 'leftHand',      axis: 'x', sign: +1, gain: 1.0 },
    wristUlnar:   { bone: 'leftHand',      axis: 'z', sign: -1, gain: 1.0 },
  },
}

/**
 * The gesture repertoire.
 *
 * Angles are anatomical degrees: `shoulderFlex` raises the arm forward,
 * `shoulderAbd` takes it out to the side, `elbow` is absolute flexion (0 =
 * straight), `twist` is positive for SUPINATION (palm turning up) and negative
 * for pronation, `wristExt` is positive for extension, `wristDev` positive for
 * ulnar deviation.
 *
 * Only non-emblematic gesticulation — nothing here means anything on its own,
 * which is the point. An avatar that fires emblems (OK sign, thumbs-up,
 * pointing) against words that do not match them is worse than a still one.
 *
 * WHY THE SHOULDER ANGLES ARE ~60-72 AND NOT THE 22-40 THE LITERATURE LISTS.
 * Those published figures are measured against an anatomically neutral hanging
 * arm. This rig's relaxed stance is not that: it already sits at 33 deg of
 * flexion, and transposing the published numbers onto it left the hand at
 * NAVEL height — the bottom edge of gesture space, half out of a camera framed
 * on the upper body. So the shoulder was solved for directly instead: these
 * values were found by sweeping flexion and measuring where the wrist actually
 * ends up, and they place the hand ~26-30cm in front of the torso at roughly
 * sternum height, which IS the centre-centre gesture space the same literature
 * describes. Position was trusted over angle convention because position is
 * what was verifiable here; the source tables are hand-authored and flagged
 * "validate by eye", and the shoulder/elbow covariation is explicitly unmeasured.
 * The elbow, twist and wrist figures ARE used as published — only the shoulder
 * needed re-solving.
 *
 * `weight` is how often each comes up. Heavily skewed toward small, low,
 * one-handed beats, because that is the distribution in calm explanatory
 * speech; the big two-handed shapes are a few times a paragraph, not a
 * few times a sentence.
 */
const REPERTOIRE = [
  {
    // THE ONLY GESTURE CURRENTLY IN USE — see LOCKED_GESTURE below.
    //
    // A palm-up presenting hand: the canonical explanatory gesture, and the
    // most frequent open-palm orientation in narrative speech. Moderated
    // slightly from the `palm_up` entry it derives from (twist 45 rather than
    // 55, a little less shoulder) because it now plays on EVERY beat rather
    // than one in five, and the fully supinated version gets emphatic fast
    // when it is the only thing she ever does.
    name: 'explaining', weight: 1, hands: 'one', shape: 'open_palm',
    shoulderFlex: 68, shoulderAbd: 15, elbow: 82, twist: 45,
    wristExt: 13, wristDev: -7, dur: [0.9, 1.5],
  },
  {
    name: 'beat', weight: 30, hands: 'one', shape: 'loose_cup',
    shoulderFlex: 58, shoulderAbd: 12, elbow: 72, twist: 10,
    wristExt: 5, wristDev: -5, dur: [0.4, 0.9],
  },
  {
    // The most frequent meaningful gesture in explanatory speech: palm turned
    // up, presenting. Supination is what makes it read; without the forearm
    // twist this is just an arm in the air.
    name: 'palm_up', weight: 20, hands: 'one', shape: 'open_palm',
    shoulderFlex: 70, shoulderAbd: 16, elbow: 82, twist: 55,
    wristExt: 15, wristDev: -8, dur: [0.9, 1.5],
  },
  {
    name: 'cupped', weight: 14, hands: 'one', shape: 'loose_cup',
    shoulderFlex: 66, shoulderAbd: 12, elbow: 82, twist: 15,
    wristExt: 12, wristDev: -5, dur: [0.8, 1.4],
  },
  {
    // Palm down: damping, settling, "that's not in question". Pronation.
    name: 'palm_down', weight: 11, hands: 'one', shape: 'flat_hand',
    shoulderFlex: 66, shoulderAbd: 10, elbow: 88, twist: -60,
    wristExt: -10, wristDev: -5, dur: [0.8, 1.4],
  },
  {
    name: 'precision', weight: 9, hands: 'one', shape: 'precision',
    shoulderFlex: 70, shoulderAbd: 13, elbow: 80, twist: 20,
    wristExt: 10, wristDev: -8, dur: [0.7, 1.2],
  },
  {
    // Vertical palm, marking a boundary or an item in a list.
    name: 'vertical_palm', weight: 7, hands: 'one', shape: 'flat_hand',
    shoulderFlex: 72, shoulderAbd: 20, elbow: 75, twist: -10,
    wristExt: 0, wristDev: 8, dur: [0.7, 1.3],
  },
  {
    name: 'palm_up_both', weight: 5, hands: 'both', shape: 'open_palm',
    shoulderFlex: 68, shoulderAbd: 18, elbow: 84, twist: 50,
    wristExt: 14, wristDev: -6, dur: [1.0, 1.6],
  },
  {
    // Framing a region with both hands, palms facing inward.
    name: 'framing', weight: 4, hands: 'both', shape: 'loose_cup',
    shoulderFlex: 66, shoulderAbd: 26, elbow: 80, twist: 0,
    wristExt: 10, wristDev: 0, dur: [1.0, 1.6],
  },
]
const TOTAL_WEIGHT = REPERTOIRE.reduce((s, r) => s + r.weight, 0)

/**
 * Pin the repertoire to one gesture. She does this and only this while
 * speaking; the rest of the table below is kept because it is calibrated and
 * because variety is one line away — set this to null to restore weighted
 * random selection across all of it.
 *
 * Note this does NOT make her motionless or robotic: the phase machine still
 * runs preparation, stroke, hold and retraction at jittered durations, still
 * alternates which hand gestures, and still scales amplitude with how emphatic
 * the speech is. It is the same gesture each time, performed differently.
 */
const LOCKED_GESTURE = 'explaining'

function pickGesture(intensity) {
  if (LOCKED_GESTURE) {
    return REPERTOIRE.find((g) => g.name === LOCKED_GESTURE) ?? REPERTOIRE[0]
  }
  // Stronger beats bias toward the later (bigger) entries by sampling twice and
  // taking the larger — skews the distribution without a second table.
  let roll = Math.random() * TOTAL_WEIGHT
  if (intensity > 0.6) roll = Math.max(roll, Math.random() * TOTAL_WEIGHT)
  for (const entry of REPERTOIRE) {
    roll -= entry.weight
    if (roll <= 0) return entry
  }
  return REPERTOIRE[0]
}

/* ---------------------------------------------------------------- timing -- */

/**
 * Measured phase durations, in seconds. Preparation ~500ms comes from the gap
 * between preparation onset (~753ms before the affiliate) and stroke onset
 * (~227ms before it); the stroke is the ~340ms active phase; the post-stroke
 * hold is ~570ms. These being slow is the point — the previous 170ms stroke
 * was roughly half the measured value and read as a twitch.
 */
const PHASE = {
  prep:    { base: 0.50, jitter: 0.10 },
  stroke:  { base: 0.34, jitter: 0.06 },
  hold:    { base: 0.57, jitter: 0.22 },
  retract: { base: 0.60, jitter: 0.15 },
}
const dur = (p) => PHASE[p].base + (Math.random() - 0.5) * 2 * PHASE[p].jitter

/**
 * Proximal-to-distal lag. The shoulder leads, the elbow follows, the wrist
 * trails — a real limb is a chain, not a rigid body, and the distal joints are
 * partly dragged rather than driven.
 *
 * TUNABLE: no measurement exists for conversational gesture. The only hard
 * numbers are from overarm throwing (~26ms shoulder-to-elbow lead), a poor
 * domain match. Implemented as first-order followers rather than a delay line
 * because that also reproduces the partly-passive quality of the wrist.
 */
const LAG = { shoulder: 0.035, elbow: 0.075, wrist: 0.115 }

/* ---------------------------------------------------------------- easing -- */

const easeOutCubic = (x) => 1 - Math.pow(1 - x, 3)
const easeInOutCubic = (x) => x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2

/**
 * Frame-rate-independent exponential smoothing: move `cur` toward `target`
 * with time constant `tau`.
 *
 * This replaces the `x += (target - x) * Math.min(1, dt / tau)` form that was
 * used throughout. That form is not frame-rate independent — with tau = 0.045
 * it moves 37% of the way per frame at 60fps but 73% at 30fps, so the same
 * animation is visibly snappier on a slower machine and any dropped frame
 * lands as a jolt. `1 - exp(-dt/tau)` is the correct step and behaves
 * identically at any frame rate, including after a long stall.
 */
function approach(cur, target, tau, dt) {
  return cur + (target - cur) * (1 - Math.exp(-dt / Math.max(1e-4, tau)))
}

/**
 * The stroke's velocity profile: accelerates, overshoots slightly, settles.
 * That overshoot is what the eye reads as effort, and therefore as a body
 * rather than an interpolation.
 *
 * Smootherstep, not easeOutCubic. easeOutCubic is at its STEEPEST at x=0
 * (derivative 3), so the stroke began at maximum speed — while preparation,
 * which eases out, had just decelerated to a stop. The hand therefore drifted
 * into position and then snapped, a velocity step of a couple of hundred
 * deg/s within one frame. Smootherstep leaves from rest with zero first and
 * second derivative, so preparation flows into the stroke instead of colliding
 * with it, and it still peaks higher in the middle than the old curve did.
 */
function smootherstep(x) {
  return x * x * x * (x * (x * 6 - 15) + 10)
}
function strokeProfile(x) {
  return smootherstep(Math.min(1, x * 1.15)) + Math.sin(Math.PI * Math.min(1, x)) * 0.085
}

/* ----------------------------------------------------------------- state -- */

export function createCoSpeechState() {
  return {
    phase: 'rest',
    phaseT: 0,
    phaseDur: 0,
    reach: 0,            // 0..1 how far into the gesture the arm is
    reachFrom: 0,
    lagged: { shoulder: 0, elbow: 0, wrist: 0 },   // proximal-to-distal chain
    beat: 0,
    beatTarget: 0,       // the beat is smoothed toward this, never assigned
    // Per-arm authority, eased rather than switched. A gesture unit can change
    // which hand is working while the previous one is still raised; stepping
    // the weights teleported the pose from one arm to the other.
    armW: { left: 0.18, right: 0.18 },
    levelSmooth: 0,      // for continuous motion; raw level is too jagged
    gesture: REPERTOIRE[0],
    hand: 'right',
    lastHand: 'left',
    shape: 'relaxed',
    prevShape: 'relaxed',
    shapeBlend: 1,
    intensity: 0,
    intensityTarget: 0,
    unitBeats: 0,
    sinceStroke: 99,
    restDwell: 0,        // enforced quiet time before a new unit may start
    energy: 0,
    level: 0,
  }
}

/**
 * Should this detected onset actually produce a stroke?
 *
 * The most important number in the file. Speakers beat on a MINORITY of
 * prominent syllables; gesturing on every one looks like conducting. The
 * probability rises with prominence, decays as a unit accumulates beats, and is
 * suppressed during the post-retraction rest dwell.
 */
function acceptOnset(state, strength) {
  if (state.sinceStroke < 0.30) return false
  if (state.phase === 'rest' && state.restDwell > 0) return false
  // Preparation and the stroke itself are not interruptible. The hand is
  // already on its way up to deliver; a syllable landing mid-flight does not
  // restart the gesture, it waits for the stroke that is already coming.
  //
  // Two separate bugs came from allowing it. Onsets during preparation chained
  // straight into the stroke and cut preparation to ~0.37s against a measured
  // ~0.5s. Onsets during a STROKE reset its clock to zero, which dropped the
  // beat envelope sin(pi*x) from its peak straight back to 0 in a single frame
  // — a visible hitch right at the most conspicuous moment of the gesture.
  // Beats chain from the hold, which is where a real one chains from anyway.
  if (state.phase === 'prep' || state.phase === 'stroke') return false
  const base = state.unitBeats === 0 ? 0.52 : 0.40
  const fatigue = Math.max(0, 1 - state.unitBeats * 0.13)
  return Math.random() < base * fatigue * (0.45 + strength * 0.85)
}

function beginStroke(state, strength) {
  const entry = pickGesture(strength)
  // Only restart the finger blend if the hand is actually changing shape.
  // Resetting it unconditionally snapped the fingers to the shape they were
  // still travelling toward, which popped whenever a stroke began mid-blend.
  if (entry.shape !== state.shape) {
    state.prevShape = state.shape
    state.shapeBlend = 0
  }

  if (state.phase === 'rest' || state.phase === 'retract') {
    // A fresh gesture unit: pick a gesture, a hand, and prepare.
    state.unitBeats = 0
    state.gesture = entry
    state.shape = entry.shape
    if (entry.hands === 'both') {
      state.hand = 'both'
    } else {
      // Alternate, but not strictly — strict alternation is its own tell.
      // Measured work says bimanual symmetry is speaker-specific and should
      // not be assumed, so the default is one working hand.
      //
      // ONLY swap hands once the previous arm is nearly down, though. A new
      // unit can begin during retraction, and switching then collapsed the old
      // arm's weight from 1 to 0.18 while it was still most of the way up —
      // yanking it down at ~180 deg/s on top of the retraction already in
      // progress, which was the single worst jolt in the whole animation.
      // Nobody hands a gesture over mid-air; they finish putting the arm down.
      // Gate on where the arm ACTUALLY is, not on `reach`. Reach is the
      // command; the joints trail it through the proximal-to-distal filters,
      // so at reach 0.185 the elbow was still 42% raised and swapping there
      // still dropped it hard. The lagged chain is the real arm position.
      const settled = Math.max(state.lagged.shoulder,
                               state.lagged.elbow,
                               state.lagged.wrist) < 0.18
      state.hand = (settled && Math.random() < 0.72)
        ? (state.lastHand === 'right' ? 'left' : 'right')
        : state.lastHand
      state.lastHand = state.hand
    }
    state.phase = 'prep'
    state.phaseDur = dur('prep') * (1 - strength * 0.15)
  } else {
    // Mid-unit: the hand is already up, so skip preparation and beat from
    // where it is. Gesture-unit chaining — within a run of speech the hand
    // does not return to rest between beats.
    state.unitBeats += 1
    state.phase = 'stroke'
    state.phaseDur = dur('stroke') * (1 - strength * 0.12)
    // Later beats may reshape the hand but stay in the same region.
    if (Math.random() < 0.35) {
      state.shape = entry.shape
      state.gesture = { ...state.gesture, shape: entry.shape }
    }
  }

  state.reachFrom = state.reach
  state.phaseT = 0
  // A TARGET, approached over ~0.12s. Assigning intensity outright stepped the
  // head-nod amplitude on every stroke.
  state.intensityTarget = Math.max(state.intensityTarget * 0.55, 0.35 + strength * 0.65)
  state.sinceStroke = 0
}

/**
 * Advance the gesture state machine one frame.
 *
 * @param {object} state from createCoSpeechState()
 * @param {object} env   { level, onset, onsetStrength, silentFor }
 * @param {number} dt    seconds
 */
export function updateCoSpeech(state, env, dt) {
  state.phaseT += dt
  state.sinceStroke += dt
  state.restDwell = Math.max(0, state.restDwell - dt)
  state.shapeBlend = Math.min(1, state.shapeBlend + dt / 0.28)

  // How animated the delivery has been lately; scales gesture size so a quiet
  // aside is not gestured at the same amplitude as an emphatic point.
  const target = env.level > 0.06 ? Math.min(1, env.level * 1.8) : 0
  state.energy = approach(state.energy, target, 0.9, dt)

  if (env.onset && acceptOnset(state, env.onsetStrength)) {
    beginStroke(state, env.onsetStrength)
  }

  const done = state.phaseT >= state.phaseDur
  switch (state.phase) {
    case 'prep': {
      state.beatTarget = 0
      // smootherstep, not easeOutCubic, for the same reason as the stroke —
      // and it matters more here. Preparation can begin DURING retraction,
      // when reach is already moving downward; easeOutCubic's steep start
      // reversed that velocity within a single frame. Leaving from rest makes
      // the hand turn around smoothly instead of bouncing.
      const k = smootherstep(Math.min(1, state.phaseT / state.phaseDur))
      // Preparation arrives at ~72% of full reach: in position, not yet
      // delivered. The remaining 28% is the stroke itself.
      state.reach = state.reachFrom + (0.72 - state.reachFrom) * k
      if (done) {
        state.phase = 'stroke'
        state.phaseT = 0
        state.phaseDur = dur('stroke')
        state.reachFrom = state.reach
        state.unitBeats += 1
      }
      break
    }
    case 'stroke': {
      const x = Math.min(1, state.phaseT / state.phaseDur)
      state.reach = state.reachFrom + (1 - state.reachFrom) * strokeProfile(x)
      // The beat: a short sharp accent peaking early in the stroke, gone by the
      // end of it. This is the part you actually see.
      state.beatTarget = Math.sin(Math.PI * x) * (0.6 + state.intensity * 0.4)
      if (done) {
        state.phase = 'hold'
        state.phaseT = 0
        state.phaseDur = dur('hold') + state.intensity * 0.12
        state.reachFrom = state.reach
      }
      break
    }
    case 'hold': {
      state.beatTarget = 0
      // Settles very slightly rather than freezing — a held hand still drifts.
      state.reach = state.reachFrom * (1 - 0.03 * Math.min(1, state.phaseT / 0.4))
      // Retract once the hold is over AND the voice has stopped. While she is
      // still talking the hand stays up waiting for the next beat, which is
      // what a gesture unit actually does.
      const quiet = env.silentFor > 0.42 || env.level < 0.04
      if (done && (quiet || state.phaseT > 1.8)) {
        state.phase = 'retract'
        state.phaseT = 0
        state.phaseDur = dur('retract') * (quiet ? 1 : 1.2)
        state.reachFrom = state.reach
      }
      break
    }
    case 'retract': {
      const k = easeInOutCubic(Math.min(1, state.phaseT / state.phaseDur))
      state.reach = state.reachFrom * (1 - k)
      state.beatTarget = 0
      if (done) {
        state.phase = 'rest'
        state.reach = 0
        state.beatTarget = 0
        state.unitBeats = 0
        state.prevShape = state.shape
        state.shape = 'relaxed'
        state.shapeBlend = 0
        // Hands genuinely rest between gesture units. TUNABLE: no measured
        // dwell time exists, so it is randomised rather than fixed — a
        // constant gap is as obvious as no gap at all.
        state.restDwell = 0.5 + Math.random() * 1.5
      }
      break
    }
    default:
      state.reach = Math.max(0, state.reach - dt)
      state.beatTarget = 0
  }

  // Proximal-to-distal chain: each joint follows the one above it.
  for (const joint of ['shoulder', 'elbow', 'wrist']) {
    const tau = LAG[joint]
    state.lagged[joint] = tau <= 0
      ? state.reach
      : approach(state.lagged[joint], state.reach, tau, dt)
  }

  // Everything below is smoothed rather than assigned. Each of these used to
  // be a step, and each step was a visible jolt:
  //   - the beat snapped to 0 whenever a stroke began while the previous one
  //     was still decaying
  //   - intensity jumped on every stroke, and it scales the head nod
  //   - the arm weights switched outright when the gesturing hand changed,
  //     teleporting the pose across the body
  //   - raw envelope level drove the head directly, so the head inherited
  //     every syllable-rate wobble in the audio
  state.beat = approach(state.beat, state.beatTarget, 0.05, dt)
  state.intensityTarget *= Math.max(0, 1 - dt / 3.0)
  state.intensity = approach(state.intensity, state.intensityTarget, 0.12, dt)
  for (const side of ['left', 'right']) {
    const active = state.hand === 'both' || state.hand === side
    state.armW[side] = approach(state.armW[side], active ? 1 : 0.18, 0.28, dt)
  }
  state.level = env.level
  state.levelSmooth = approach(state.levelSmooth, env.level, 0.22, dt)
  return state
}

/* ------------------------------------------------------------------ apply -- */

/** Accumulate an anatomical angle (degrees) onto a per-bone Euler offset map. */
function addAngle(out, side, name, degrees) {
  if (!degrees) return
  const a = AXES[side][name]
  const slot = out[a.bone] || (out[a.bone] = { x: 0, y: 0, z: 0 })
  slot[a.axis] += DEG(degrees * a.gain * a.sign)
}

/**
 * Resolve one arm's anatomical angles for this frame and write them.
 *
 * `w` scales the whole arm: 1 for the gesturing hand, a fraction for the other.
 * TUNABLE: the non-gesturing arm's share has no measured value; 0.18 keeps it
 * alive without it looking like an unintended second gesture.
 */
function poseArm(out, side, g, state, w) {
  const L = state.lagged
  const energy = 0.70 + state.energy * 0.30
  const sh = L.shoulder * w * energy
  const el = L.elbow * w * energy
  const wr = L.wrist * w * energy
  const beat = state.beat * w

  // Shoulder angles are absolute anatomical targets, so the delta is measured
  // from where the relaxed stance already holds the arm. Note how SMALL these
  // deltas are: the relaxed base is already at 33 deg of flexion, and a
  // conversational gesture only asks for ~22-40. Almost all of the visible
  // movement is the elbow folding, which is anatomically correct — you do not
  // raise your shoulder to gesture in front of your chest, you bend your arm.
  addAngle(out, side, 'shoulderFlex', (g.shoulderFlex - BASE_SH_FLEX) * sh)
  addAngle(out, side, 'shoulderAbd', (g.shoulderAbd - BASE_SH_ABD) * sh)

  // Elbow is absolute flexion, so the delta is measured from the flexion the
  // relaxed stance already has. Interpolating the ANGLE rather than the bone
  // rotation is what makes the elbow fold rather than swing.
  addAngle(out, side, 'elbow', (g.elbow - BASE_ELBOW) * el + 9 * beat)

  // Forearm rotation — the axis that turns the palm over, and the one most
  // procedural avatars leave out entirely.
  addAngle(out, side, 'twist', g.twist * el)

  // Wrist. Flexion and deviation are COUPLED in a real wrist: extension pairs
  // with radial deviation, flexion with ulnar. Driving the two axes
  // independently is what produces the broken-doll wrist.
  const ext = g.wristExt * wr - 18 * beat          // TUNABLE: flick amplitude
  const dev = g.wristDev * wr - 0.35 * ext
  addAngle(out, side, 'wristFlex', -ext)
  addAngle(out, side, 'wristUlnar', dev)

  // The shoulder itself lifts a little as the arm comes up; without it the arm
  // reads as hinged to a fixed block.
  const shoulder = side === 'left' ? 'leftShoulder' : 'rightShoulder'
  const slot = out[shoulder] || (out[shoulder] = { x: 0, y: 0, z: 0 })
  slot.x += DEG(-5) * sh
  slot.z += DEG(3) * sh * (side === 'left' ? -1 : 1)
}

/**
 * Write the co-speech layer onto the bones.
 *
 * Composes ON TOP of whatever gestures.js wrote for the arms (it multiplies
 * offsets), but writes the finger bones outright from the rest pose via
 * hands.js — the gesture layer has no finger poses of its own.
 *
 * @param {number} t elapsed seconds, for the always-on micro-motion
 */
export function applyCoSpeech(bones, restPose, state, t) {
  const g = state.gesture
  const out = {}

  for (const side of ['left', 'right']) {
    // Eased weight, not a switch — see updateCoSpeech. Two-handed gestures are
    // never quite symmetric either; a few percent of difference kills the
    // mirror-image look.
    poseArm(out, side, g, state, state.armW[side] * (side === 'left' ? 0.94 : 1))
  }

  for (const [role, e] of Object.entries(out)) {
    const bone = bones.get(role)
    if (!bone) continue
    bone.quaternion.multiply(
      new THREE.Quaternion().setFromEuler(new THREE.Euler(e.x, e.y, e.z)))
  }

  // ---- hands ----
  const from = HAND_SHAPES[state.prevShape] ?? HAND_SHAPES.relaxed
  const base = HAND_SHAPES[state.shape] ?? HAND_SHAPES.relaxed

  // A stroke firms the hand at its peak and loosens it after — small, but it is
  // the difference between fingers that are posed and fingers that are doing
  // something.
  const tightened = {
    curl: {}, spread: base.spread * (1 + state.beat * 0.12), thumbOut: base.thumbOut,
  }
  for (const f of Object.keys(base.curl)) {
    tightened.curl[f] = Math.min(1, base.curl[f] + state.beat * 0.10)
  }

  const blend = easeOutCubic(state.shapeBlend)
  for (const side of ['left', 'right']) {
    // Driven by the same eased weight as the arm, so a hand that stops
    // gesturing relaxes its fingers over the same ~0.28s that its arm drops
    // rather than releasing them instantly.
    const w = state.armW[side]
    const target = blendShapes(HAND_SHAPES.relaxed, tightened,
      Math.min(1, 0.22 + 0.78 * ((w - 0.18) / 0.82)))
    applyHandShape(bones, restPose, side, from, target, blend, t, 1)
  }

  // ---- head, neck, torso ----
  // Head beats co-occur with hand beats; that coupling is much of why gesture
  // reads as connected to speech rather than layered over it.
  // The head nod IS the hand beat, rather than a separate impulse that was
  // set outright on every stroke. Driving both from one smoothed value keeps
  // head and hand genuinely coupled and removes a second source of jolt.
  const nod = state.beat * state.intensity
  const lv = state.levelSmooth
  addRotation(bones.get('head'),
    DEG(5.5) * nod + Math.sin(t * 1.9) * lv * DEG(1.4),
    Math.sin(t * 1.3) * lv * DEG(2.6),
    DEG(-2.2) * nod * (state.hand === 'left' ? -1 : 1))
  addRotation(bones.get('neck'), DEG(2.2) * nod, Math.sin(t * 1.3) * lv * DEG(1.0), 0)

  // The torso answers the gesture — arms that move without any torso response
  // look bolted on.
  const twist = state.hand === 'both' ? 0 : (state.hand === 'left' ? 1 : -1)
  const r = state.lagged.shoulder
  addRotation(bones.get('chest'), DEG(1.6) * r, DEG(2.4) * r * twist, 0)
  addRotation(bones.get('spine'), DEG(0.8) * r, DEG(1.4) * r * twist, 0)
}

/** Rotate a bone by (x,y,z) radians on top of its current orientation. */
function addRotation(bone, x, y, z) {
  if (!bone) return
  bone.quaternion.multiply(
    new THREE.Quaternion().setFromEuler(new THREE.Euler(x, y, z)))
}
