/**
 * The six gesture poses Cureva's avatar switches between (T1.31), keyed to
 * exactly the closed enum in intake/models.py's AvatarTurnResponse.gesture:
 * idle, listening, concern_lean_in, explaining_gesture, reassure_nod,
 * farewell_wave.
 *
 * IMPORTANT, stated plainly rather than glossed over: the build instructions
 * ask for these to be "new short animation clips... recorded using the same
 * Kalidokit+MediaPipe webcam-capture authoring method already proven in
 * Setu" — i.e. six short mocap recordings from a live webcam session. That
 * requires a physical camera and a live capture session neither this build
 * environment nor this agent has access to. What is built here instead is a
 * PROCEDURAL substitute: each gesture is a small set of target bone
 * rotations (head tilt, arm lift, a wave cycle) that the render loop
 * interpolates toward and holds/animates in code — genuinely functional and
 * visibly distinct per gesture, but authored as keyframes, not captured from
 * a real performer. Swapping in real recorded clips later means replacing
 * the target-rotation tables below with a loaded AnimationClip per gesture;
 * everything else (the gesture prop, the switching logic) stays the same.
 */
import * as THREE from 'three'

const DEG = THREE.MathUtils.degToRad

/**
 * The relaxed conversational stance every pose is built on.
 *
 * This rig's REST pose is a T-pose — arms straight out horizontally — because
 * that is how the .glb was authored, not because it is a pose anyone would
 * hold. Leaving `idle: {}` meant the avatar stood there with its arms spread
 * like a scarecrow, and the small idle motion layered on top was invisible
 * against a silhouette that was already wrong.
 *
 * So every gesture starts from here: arms down at the sides, elbows very
 * slightly bent, shoulders dropped. Gesture poses below are offsets FROM this
 * stance, not from the T-pose.
 *
 * Angles were found by rendering and looking, not derived — see the note on
 * explaining_gesture about why the axes are not the obvious ones on this rig.
 */
export const RELAXED_BASE = {
  // Found by rendering candidate stances and looking at them, not derived.
  // Two things about this rig that guessing gets wrong:
  //   - Z is the TWIST axis for the arm bones. Rotating Z alone leaves the arm
  //     sticking straight out and just rolls the hand over.
  //   - X is the SWING axis, but a large X rotation on its own collapses the
  //     sleeve into the shoulder (the skin weights don't carry it) — at 74°
  //     the jacket crumpled into a cap sleeve and the hands read as detached.
  // X ~40° combined with Z ~-35° is what actually produces a natural drape:
  // the swing brings the arm down, the twist brings it in against the body.
  rightUpperArm: { x: DEG(40), y: 0, z: DEG(-35) },
  leftUpperArm: { x: DEG(40), y: 0, z: DEG(35) },
  // A straight arm reads as stiff; a small bend at the elbow settles it.
  rightLowerArm: { x: DEG(10), y: 0, z: DEG(-8) },
  leftLowerArm: { x: DEG(10), y: 0, z: DEG(8) },
  // Hands left at rest — any twist here splays the fingers outward on this rig.
  rightHand: { x: 0, y: 0, z: 0 },
  leftHand: { x: 0, y: 0, z: 0 },
  // Shoulders settle rather than sitting squared-up.
  rightShoulder: { x: DEG(2), y: 0, z: 0 },
  leftShoulder: { x: DEG(2), y: 0, z: 0 },
}

/** bone -> {x,y,z} target Euler offset from RELAXED_BASE, in radians. */
export const GESTURE_POSES = {
  idle: {},
  listening: {
    head: { x: DEG(6), y: DEG(4), z: 0 },
    neck: { x: DEG(2), y: 0, z: 0 },
  },
  concern_lean_in: {
    head: { x: DEG(9), y: 0, z: 0 },
    spine: { x: DEG(5), y: 0, z: 0 },
    chest: { x: DEG(4), y: 0, z: 0 },
    // Hands come forward slightly — the "tell me more" posture.
    rightUpperArm: { x: DEG(-12), y: 0, z: 0 },
    leftUpperArm: { x: DEG(-12), y: 0, z: 0 },
    rightLowerArm: { x: DEG(-16), y: DEG(-8), z: 0 },
    leftLowerArm: { x: DEG(-16), y: DEG(8), z: 0 },
  },
  explaining_gesture: {
    // Offsets FROM the relaxed stance. X-axis rotation is what moves the
    // upper-arm bone in the image plane on this rig — Y and Z rotate it
    // toward or away from the camera, which is invisible from a front view.
    // Found by rendering and looking, the same way the source loader.ts's
    // comments describe having to measure this rig rather than assume a
    // standard convention.
    head: { x: DEG(-4), y: 0, z: 0 },
    rightUpperArm: { x: DEG(-48), y: 0, z: DEG(-10) },
    rightLowerArm: { x: DEG(-26), y: DEG(-24), z: 0 },
    rightHand: { x: DEG(-10), y: 0, z: 0 },
  },
  reassure_nod: {
    // animated (a nod cycle), handled specially in the render loop below
    head: { x: 0, y: 0, z: 0 },
  },
  farewell_wave: {
    // Arm up and out from the relaxed stance, forearm waving (animated below).
    rightUpperArm: { x: DEG(-62), y: 0, z: DEG(-18) },
    rightLowerArm: { x: DEG(-34), y: DEG(-18), z: 0 },
  },
}

/** Gestures with a periodic component beyond a static held pose. */
export const ANIMATED_GESTURES = new Set(['reassure_nod', 'farewell_wave'])

const VALID = new Set(Object.keys(GESTURE_POSES))

/** An out-of-enum gesture coerces to idle client-side too — mirrors FR-18's
 * server-side coercion, so a frontend bug can't display a broken pose. */
export function safeGesture(g) {
  return VALID.has(g) ? g : 'idle'
}

/** Apply one gesture's target pose to the bone map, lerping from rest. Called
 * every frame with a 0..1 blend factor and elapsed time (for animated poses). */
export function applyGesture(bones, restPose, gestureName, blend, t) {
  const gesture = safeGesture(gestureName)
  const pose = GESTURE_POSES[gesture]

  for (const [role, bone] of bones) {
    const rest = restPose.get(role)
    if (!rest) continue
    // Every pose is the relaxed stance plus this gesture's offset from it.
    const base = RELAXED_BASE[role]
    const target = pose[role]
    const euler = new THREE.Euler(
      (base?.x ?? 0) + (target?.x ?? 0),
      (base?.y ?? 0) + (target?.y ?? 0),
      (base?.z ?? 0) + (target?.z ?? 0))
    let deltaQuat = new THREE.Quaternion().setFromEuler(euler)

    if (gesture === 'reassure_nod' && role === 'head') {
      const nod = Math.sin(t * 3.2) * DEG(8)
      deltaQuat = new THREE.Quaternion().setFromEuler(new THREE.Euler(nod, 0, 0))
    }
    if (gesture === 'farewell_wave' && role === 'rightLowerArm') {
      const wave = Math.sin(t * 6) * DEG(18)
      deltaQuat = new THREE.Quaternion().setFromEuler(new THREE.Euler(
        (base?.x ?? 0) + (target?.x ?? 0),
        (base?.y ?? 0) + (target?.y ?? 0) + wave,
        (base?.z ?? 0) + (target?.z ?? 0)))
    }

    const targetQuat = rest.quaternion.clone().multiply(deltaQuat)
    bone.quaternion.slerp(targetQuat, blend)
  }
}
