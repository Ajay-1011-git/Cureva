/**
 * Finger articulation — the hand shapes the avatar's fingers actually form,
 * and the code that drives all thirty finger bones toward them.
 *
 * Until now nothing in this project touched a finger bone: loader.js didn't
 * even map them (see the FINGERS block there). The hands were rigid, slightly
 * splayed slabs, and no amount of arm motion fixes that — a real hand reshapes
 * continuously while its owner talks, and the eye reads a hand that doesn't as
 * plastic.
 *
 * WHICH AXIS CURLS A FINGER, and how that was actually settled
 * ------------------------------------------------------------
 * Every finger bone's local +Y runs distally (down the finger — confirmed from
 * the .glb: each joint's translation from its parent is pure +Y). So bending
 * happens about local X, and the only question is the sign:
 *
 *   CURL IS POSITIVE X, ON BOTH HANDS.
 *
 * Worth recording HOW that was established, because several plausible-looking
 * tests get it wrong and getting it wrong bends every joint inside-out:
 *
 *   - Inferring the palm normal from the thumb's direction, from the rig's
 *     rest rotations, or from where the hand mesh's soft tissue sits all gave
 *     answers, and two of the three gave the WRONG answer. Their margins were
 *     around a millimetre on a 180mm hand, i.e. noise. The finger-pad
 *     asymmetry test (palmar pad vs flat dorsal side) split 3-3 across fingers,
 *     because this model's fingers are near-cylindrical.
 *   - What settled it was rendering the hand from both sides and looking:
 *     from one side the fingernails are plainly visible, from the other they
 *     are not. Nails are dorsal. That fixes the palm normal with no inference
 *     at all, and against it all eight fingers of both hands agree at
 *     magnitude 1.000 that +X carries the fingertip toward the palm.
 *
 * This also matches the rig this vocabulary was calibrated against
 * (met4citizen's TalkingHead, same Mixamo bone naming, also +X), which is the
 * expected outcome — the earlier suspicion that this rig was inverted relative
 * to it was the artefact of a bad test, not a real difference.
 *
 * Note the fingertip-distance-to-wrist test is NOT valid here and was
 * discarded: folding a finger either way brings its tip nearer the wrist, so
 * it cannot distinguish curl from hyperextension. Distance to the THUMB TIP
 * does work, because the thumb opposes the fingers across the palm.
 *
 * The splay axis (Z) IS mirrored between hands, the usual convention for a
 * mirrored rig, so every shape below is written once and mirrored by `sign`.
 *
 * Calibration source for the joint ratios and the shape values: the measured
 * finger rotations in TalkingHead's gestureTemplates.
 */
import * as THREE from 'three'

const DEG = THREE.MathUtils.degToRad

export const FINGER_NAMES = ['Thumb', 'Index', 'Middle', 'Ring', 'Pinky']

/**
 * How much of a finger's nominal curl each joint takes.
 *
 * Not equal thirds: the middle phalanx closes furthest, the fingertip least.
 * A fist in the reference data reads ~1.41 / 1.90 / 0.54 radians across the
 * three index joints, i.e. roughly 1 : 1.35 : 0.38 — which is what makes a
 * closing hand curl in a spiral instead of collapsing like a hinge. Driving
 * all three joints equally is the single most common way procedural hands end
 * up looking like cheap claws.
 */
const JOINT_CURL = { 1: 1.0, 2: 1.32, 3: 0.38 }

/** Radians of curl at joint 1 for curl = 1.0 (a closed fist). */
const FULL_CURL = 1.45

/**
 * Per-finger fan, as a multiplier on the `spread` parameter.
 *
 * Splay is measured outward from the middle finger, which barely moves — the
 * index drifts one way, ring and pinky the other, and the pinky most of all.
 * The reference open palm shows exactly this gradient (z -0.087 / -0.082 /
 * -0.122 / -0.200 index->pinky). Fingers that splay uniformly look webbed.
 */
const FINGER_FAN = { Index: 0.45, Middle: 0.0, Ring: -0.55, Pinky: -1.0 }

/**
 * Small constant per-finger curl bias, applied on top of whatever a shape asks
 * for. Real fingers never sit at matching angles: the pinky and ring ride
 * curled a little more than the index even in a deliberately flat hand. This
 * is tiny and always on, and it is most of what stops a hand reading as a
 * glove stretched over a frame.
 */
const FINGER_BIAS = { Thumb: -0.04, Index: 0.0, Middle: 0.03, Ring: 0.09, Pinky: 0.16 }

/**
 * The shape vocabulary.
 *
 * `curl` is per finger, 0 (straight) .. 1 (fully closed). `spread` fans the
 * fingers apart. `thumbOut` abducts the thumb away from the palm — the thumb
 * gets its own parameter because its base joint rotates on a different axis
 * from the fingers and reads wrong if driven by the same curl value.
 *
 * These are the handshapes that actually turn up in unscripted conversational
 * speech. Deliberately NO emblems (no OK sign, no thumbs-up, no pointing at
 * the listener): those carry specific meanings, and a clinical interviewer
 * flashing them at random intervals against words that don't match would be
 * worse than a still hand, not better.
 */
export const HAND_SHAPES = {
  // Hanging at the side. The baseline; gravity-curled, thumb resting in.
  relaxed: {
    curl: { Thumb: 0.18, Index: 0.22, Middle: 0.26, Ring: 0.30, Pinky: 0.34 },
    spread: 0.10, thumbOut: 0.12,
  },
  // The workhorse. Fingers softly curved, as if loosely holding an apple —
  // this is where hands actually live during ordinary talking.
  loose_cup: {
    curl: { Thumb: 0.26, Index: 0.34, Middle: 0.38, Ring: 0.44, Pinky: 0.50 },
    spread: 0.28, thumbOut: 0.30,
  },
  // Palm presented, fingers long. "Here's the situation." The single most
  // common meaningful gesture in explanatory speech.
  open_palm: {
    curl: { Thumb: 0.10, Index: 0.10, Middle: 0.08, Ring: 0.12, Pinky: 0.16 },
    spread: 0.55, thumbOut: 0.62,
  },
  // Fingers extended and held together, not fanned. The palm-down "settle
  // down" hand and the vertical "boundary" hand both use this — in both the
  // flatness IS the signal, so spread stays low.
  flat_hand: {
    curl: { Thumb: 0.14, Index: 0.12, Middle: 0.10, Ring: 0.12, Pinky: 0.15 },
    spread: 0.06, thumbOut: 0.22,
  },
  // Fingers splayed, everything extended. Reserved for the strongest beats.
  // Nothing goes to zero: a measured relaxed hand still carries ~0.15-0.25 of
  // curl at every joint, and fingers snapped perfectly straight are the single
  // clearest "this is a posed model" tell.
  spread_wide: {
    curl: { Thumb: 0.10, Index: 0.09, Middle: 0.08, Ring: 0.10, Pinky: 0.13 },
    spread: 1.0, thumbOut: 0.85,
  },
  // Thumb and index nearly meeting, the rest folded away. The "one specific
  // thing" hand — pairs with precise or qualifying words.
  //
  // thumbOut is NEGATIVE here, which is the one place in this table it is:
  // negative adducts the thumb ACROSS the palm instead of abducting it away,
  // which is what opposition actually is. It matters because with the other
  // fingers curled, an abducted thumb stands proud of the fist and the whole
  // hand reads as a THUMBS-UP — an emblem, and an evaluative one for a
  // clinical interviewer to flash at an arbitrary moment. Caught by rendering
  // the pose and looking at it.
  //
  // Measured by thumb-tip to index-tip distance: the original 0.34 gave 75mm
  // (clearly not a pinch), simply reducing it to 0.16 gave 64mm (better, still
  // not one), and -0.30 gives 29mm, which reads as a pinch. Index curl is
  // raised to 0.70 to bring the finger out to meet the thumb rather than
  // asking the thumb to travel the whole way.
  precision: {
    curl: { Thumb: 0.50, Index: 0.70, Middle: 0.62, Ring: 0.72, Pinky: 0.78 },
    spread: 0.12, thumbOut: -0.30,
  },
  // Loosely closed. A soft emphasis beat — never a clenched fist, which on a
  // clinician reads as anger.
  soft_fist: {
    curl: { Thumb: 0.50, Index: 0.68, Middle: 0.72, Ring: 0.74, Pinky: 0.76 },
    spread: 0.05, thumbOut: 0.18,
  },
  // Index a little longer than the rest, hand soft — indicating without
  // pointing. Marks a step or an item, not a person.
  soft_index: {
    curl: { Thumb: 0.30, Index: 0.08, Middle: 0.52, Ring: 0.62, Pinky: 0.68 },
    spread: 0.18, thumbOut: 0.28,
  },
}

export const SHAPE_NAMES = Object.keys(HAND_SHAPES)

/** Blend two shapes. Used to ease between handshapes across a gesture phase. */
export function blendShapes(a, b, k) {
  const out = { curl: {}, spread: 0, thumbOut: 0 }
  for (const f of FINGER_NAMES) {
    out.curl[f] = a.curl[f] + (b.curl[f] - a.curl[f]) * k
  }
  out.spread = a.spread + (b.spread - a.spread) * k
  out.thumbOut = a.thumbOut + (b.thumbOut - a.thumbOut) * k
  return out
}

/**
 * Per-finger arrival delay, in "shape units".
 *
 * When a hand changes shape the fingers do not arrive together — the motion
 * runs across the hand, thumb and index leading, pinky trailing by something
 * like 50-70ms. Staggering the blend factor per finger is cheap and is the
 * difference between a hand that reshapes and a hand that snaps between two
 * models of itself.
 */
const FINGER_LAG = { Thumb: 0.0, Index: 0.06, Middle: 0.13, Ring: 0.20, Pinky: 0.28 }

/**
 * Write one hand's finger bones, interpolating between two shapes.
 *
 * Takes BOTH shapes rather than a single pre-blended one so the per-finger
 * stagger can be applied where it belongs — to the interpolation between the
 * two handshapes. Blending the shapes first and then staggering would scale
 * the fingers toward the rest pose mid-transition, i.e. the hand would flatten
 * out on its way from one shape to the next instead of travelling between
 * them.
 *
 * @param {Map}    bones    humanoid role -> THREE.Bone
 * @param {Map}    restPose role -> {quaternion, position}
 * @param {'left'|'right'} side
 * @param {object} from     shape being left  {curl, spread, thumbOut}
 * @param {object} to       shape being formed
 * @param {number} blend    0..1 progress from `from` to `to`
 * @param {number} t        elapsed seconds, for the always-on finger micro-drift
 * @param {number} weight   0..1 authority of the whole layer over the rest pose
 */
export function applyHandShape(bones, restPose, side, from, to, blend, t, weight = 1) {
  // Splay mirrors between hands; curl does not. See the module note.
  const sign = side === 'left' ? 1 : -1
  // Phase offset so the two hands never drift in lockstep.
  const handPhase = side === 'left' ? 0 : 2.4
  const b = Math.max(0, Math.min(1, blend))

  FINGER_NAMES.forEach((finger, fi) => {
    // Stagger: fingers further from the thumb lag behind the shape change.
    const denom = 1 - FINGER_LAG[finger]
    const staggered = Math.max(0, Math.min(1, (b - FINGER_LAG[finger]) / (denom || 1)))
    const f = staggered * staggered * (3 - 2 * staggered)
    const k = weight

    // This finger's own position along the transition.
    const curlV = from.curl[finger] + (to.curl[finger] - from.curl[finger]) * f
    const spreadV = from.spread + (to.spread - from.spread) * f
    const thumbOutV = from.thumbOut + (to.thumbOut - from.thumbOut) * f
    const shape = { spread: spreadV, thumbOut: thumbOutV }

    // Micro-drift: every finger carries its own slow, tiny tremor. Always on,
    // even at rest — a completely motionless finger is the tell.
    const drift = Math.sin(t * (0.7 + fi * 0.19) + handPhase + fi * 1.7) * DEG(1.4)

    const curl = (curlV + FINGER_BIAS[finger]) * FULL_CURL

    for (const joint of [1, 2, 3]) {
      const role = `${side}${finger}${joint}`
      const bone = bones.get(role)
      const rest = restPose.get(role)
      if (!bone || !rest) continue

      let x, y = 0, z = 0

      if (finger === 'Thumb') {
        // The thumb's base joint swings on Z (abduction away from the palm)
        // and rolls on Y; only its two outer joints curl like a finger. Driving
        // the thumb off the finger curl alone folds it flat across the palm,
        // which is the classic broken-procedural-hand look.
        if (joint === 1) {
          x = curl * 0.35
          z = sign * shape.thumbOut * DEG(38)
          y = sign * shape.thumbOut * DEG(-14)
        } else {
          x = curl * JOINT_CURL[joint] * 0.55
        }
      } else {
        // Curl is POSITIVE X on this rig — see the module note.
        x = curl * JOINT_CURL[joint]
        if (joint === 1) {
          // Splay lives at the knuckle only; fanning the outer joints bends
          // fingers sideways halfway along, which no hand does.
          z = sign * shape.spread * FINGER_FAN[finger] * DEG(11)
          y = sign * shape.spread * FINGER_FAN[finger] * DEG(5)
        }
      }

      x += drift * (joint === 1 ? 1 : 0.5)

      const offset = new THREE.Quaternion().setFromEuler(new THREE.Euler(x * k, y * k, z * k))
      bone.quaternion.copy(rest.quaternion).multiply(offset)
    }
  })
}
