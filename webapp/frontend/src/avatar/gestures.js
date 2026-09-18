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

/** bone -> {x,y,z} target Euler offset from rest, in radians. */
export const GESTURE_POSES = {
  idle: {},
  listening: {
    head: { x: DEG(6), y: DEG(4), z: 0 },
    neck: { x: DEG(2), y: 0, z: 0 },
  },
  concern_lean_in: {
    head: { x: DEG(10), y: 0, z: 0 },
    spine: { x: DEG(4), y: 0, z: 0 },
    chest: { x: DEG(3), y: 0, z: 0 },
  },
  explaining_gesture: {
    // Confirmed empirically (not assumed): on this rig's rest orientation,
    // X-axis rotation moves the upper-arm bone in the image plane -- Y and Z
    // rotate it toward/away from camera (invisible from a front view). This
    // was found by trying axes and inspecting real screenshots, the same way
    // the source loader.ts's own comments describe having to measure this
    // rig's actual pose rather than assume a standard convention.
    head: { x: DEG(-4), y: 0, z: 0 },
    rightUpperArm: { x: DEG(-70), y: 0, z: 0 },
    rightLowerArm: { x: DEG(-30), y: DEG(-20), z: 0 },
  },
  reassure_nod: {
    // animated (a nod cycle), handled specially in the render loop below
    head: { x: 0, y: 0, z: 0 },
  },
  farewell_wave: {
    rightUpperArm: { x: 0, y: 0, z: DEG(-70) },
    rightLowerArm: { x: 0, y: DEG(-30), z: 0 },
    // animated (a wave cycle), handled specially in the render loop below
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
    const target = pose[role]
    const euler = new THREE.Euler(target?.x ?? 0, target?.y ?? 0, target?.z ?? 0)
    let deltaQuat = new THREE.Quaternion().setFromEuler(euler)

    if (gesture === 'reassure_nod' && role === 'head') {
      const nod = Math.sin(t * 3.2) * DEG(8)
      deltaQuat = new THREE.Quaternion().setFromEuler(new THREE.Euler(nod, 0, 0))
    }
    if (gesture === 'farewell_wave' && role === 'rightLowerArm') {
      const wave = Math.sin(t * 6) * DEG(18)
      deltaQuat = new THREE.Quaternion().setFromEuler(
        new THREE.Euler(0, target.y + wave, 0))
    }

    const targetQuat = rest.quaternion.clone().multiply(deltaQuat)
    bone.quaternion.slerp(targetQuat, blend)
  }
}
