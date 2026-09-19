/**
 * Continuous, low-amplitude body motion — the difference between a 3D model
 * and something that reads as alive.
 *
 * Two layers, composed on top of whatever gesture pose is active:
 *
 *  1. BREATHING — a slow chest/spine rise and fall that never stops, even at
 *     rest. A perfectly still figure reads as a frozen asset within about two
 *     seconds; this is the single cheapest fix for that.
 *  2. SWAY + BLINK-SCALE WEIGHT SHIFT — a very slow drift of the hips and
 *     spine on a different period from the breath, so the two never line up
 *     into an obvious loop.
 *
 * Speaking motion USED to be a third layer here — sine waves multiplied by the
 * audio amplitude. It has been removed, not moved: continuous amplitude-driven
 * wobble is the wrong model for co-speech gesture, which is discrete and
 * phase-structured. See cospeech.js, which replaces it.
 *
 * Everything here is deliberately small in amplitude. Overdone idle motion
 * reads as drunk rather than alive, and this figure is meant to be a calm
 * clinical interviewer.
 *
 * Amplitudes are in radians via DEG(); periods are in seconds. They are
 * mutually prime-ish on purpose so the composite never visibly repeats.
 */
import * as THREE from 'three'

const DEG = THREE.MathUtils.degToRad

/** Rotate a bone by (x,y,z) radians on top of its current orientation. */
function addRotation(bone, x, y, z) {
  if (!bone) return
  bone.quaternion.multiply(
    new THREE.Quaternion().setFromEuler(new THREE.Euler(x, y, z)))
}

/**
 * Offset a bone from its rest POSITION, in bone-local units.
 *
 * Rotation alone turned out not to be enough to make breathing read: a couple
 * of degrees at the chest is a sub-pixel change at the shoulders from a
 * camera framed on the upper body. Actually lifting the chest and hips a
 * little is what the eye picks up as breathing. Rest positions are captured
 * once so this composes rather than drifting frame over frame.
 */
const restPositions = new WeakMap()
function addOffset(bone, fx, fy, fz) {
  if (!bone) return
  let rest = restPositions.get(bone)
  if (!rest) {
    rest = { v: bone.position.clone(), len: bone.position.length() || 1 }
    restPositions.set(bone, rest)
  }
  // Offsets are FRACTIONS of the bone's own rest length, not absolute units.
  // Absolute numbers are meaningless across rigs and dangerous on this one:
  // the chest bone's local offset is 0.86, so an absolute 0.9 doubled the
  // torso and threw the whole figure out of frame. A fraction is safe
  // wherever the model came from and whatever scale it was exported at.
  const L = rest.len
  bone.position.set(rest.v.x + fx * L, rest.v.y + fy * L, rest.v.z + fz * L)
}

/**
 * Breathing + weight shift. Always runs.
 * @param {Map} bones humanoid-role -> THREE.Bone
 * @param {number} t   elapsed seconds
 * @param {number} armDamp 0..1 scale on the idle arm swing; the co-speech
 *   layer drives this to 0 as the arms come up, so idle drift and gesture do
 *   not fight over the same bones.
 */
export function applyIdleLife(bones, t, armDamp = 1) {
  // Breath: ~4.2s cycle, a resting adult rate. Rotation AND a small vertical
  // lift — rotation alone is a sub-pixel change at this camera distance, which
  // is why the first version was mathematically present and invisible.
  const phase = t * (2 * Math.PI / 4.2)
  const breath = Math.sin(phase)
  const breathLag = Math.sin(phase - 0.5)

  // ~1.5% of the chest bone's length: real quiet breathing is under 1% of
  // body height, and this is on top of the rotation below.
  addOffset(bones.get('chest'), 0, breath * 0.015, 0)
  addOffset(bones.get('hips'), 0, breath * 0.004, 0)
  addRotation(bones.get('chest'), breath * DEG(3.4), 0, 0)
  addRotation(bones.get('upperChest'), breath * DEG(2.6), 0, 0)
  addRotation(bones.get('leftShoulder'), breathLag * DEG(4.0), 0, breathLag * DEG(-2.5))
  addRotation(bones.get('rightShoulder'), breathLag * DEG(4.0), 0, breathLag * DEG(2.5))
  addRotation(bones.get('neck'), breath * DEG(-1.8), 0, 0)

  // Weight shift: much slower, on hips and spine, so the whole figure moves as
  // one rather than the head drifting on a static body.
  const sway = Math.sin(t * (2 * Math.PI / 11))
  const sway2 = Math.sin(t * (2 * Math.PI / 7) + 1.1)
  addOffset(bones.get('hips'), sway * 0.006, 0, 0)
  addRotation(bones.get('hips'), 0, sway * DEG(4.5), sway2 * DEG(2.6))
  addRotation(bones.get('spine'), 0, sway * DEG(-2.2), sway2 * DEG(-1.6))

  // Head: never perfectly still above the neck.
  addRotation(bones.get('head'),
    Math.sin(t * (2 * Math.PI / 6.3) + 0.4) * DEG(3.6),
    Math.sin(t * (2 * Math.PI / 9.1)) * DEG(6.5),
    Math.sin(t * (2 * Math.PI / 13)) * DEG(2.4))

  // Arms swing gently, on periods that don't match the breath so nothing ever
  // looks like it is on a loop.
  //
  // `armDamp` fades this out as the arms come up to gesture. The idle swing is
  // right for arms hanging at the sides and wrong for arms held in gesture
  // space — left at full strength it fights the stroke and smears the hold,
  // which is precisely the wobble this rewrite set out to remove.
  const armDrift = Math.sin(t * (2 * Math.PI / 8.5)) * armDamp
  const armDrift2 = Math.sin(t * (2 * Math.PI / 6.7) + 2.2) * armDamp
  addRotation(bones.get('leftUpperArm'), armDrift * DEG(3.4), 0, armDrift2 * DEG(2.4))
  addRotation(bones.get('rightUpperArm'), -armDrift * DEG(3.4), 0, -armDrift2 * DEG(2.4))
  addRotation(bones.get('leftLowerArm'), armDrift2 * DEG(3.2), 0, 0)
  addRotation(bones.get('rightLowerArm'), -armDrift2 * DEG(3.2), 0, 0)
}
