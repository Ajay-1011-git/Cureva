/**
 * Continuous, low-amplitude body motion — the difference between a 3D model
 * and something that reads as alive.
 *
 * Three layers, composed on top of whatever gesture pose is active:
 *
 *  1. BREATHING — a slow chest/spine rise and fall that never stops, even at
 *     rest. A perfectly still figure reads as a frozen asset within about two
 *     seconds; this is the single cheapest fix for that.
 *  2. SWAY + BLINK-SCALE WEIGHT SHIFT — a very slow drift of the hips and
 *     spine on a different period from the breath, so the two never line up
 *     into an obvious loop.
 *  3. SPEAKING MOTION — while audio is playing, the head nods and turns
 *     slightly with the speech envelope, and the arms make small co-speech
 *     gestures. Real people move their hands when they talk; an avatar whose
 *     arms hang dead while its voice plays looks like a puppet with a
 *     soundtrack.
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
 * Breathing + weight shift. Always runs.
 * @param {Map} bones humanoid-role -> THREE.Bone
 * @param {number} t   elapsed seconds
 */
export function applyIdleLife(bones, t) {
  // Breath: ~4.5s cycle, the resting adult rate. Chest expands, shoulders
  // lift a touch behind it, head rides along very slightly.
  const breath = Math.sin(t * (2 * Math.PI / 4.5))
  addRotation(bones.get('chest'), breath * DEG(1.1), 0, 0)
  addRotation(bones.get('upperChest'), breath * DEG(0.8), 0, 0)
  addRotation(bones.get('leftShoulder'), breath * DEG(0.9), 0, 0)
  addRotation(bones.get('rightShoulder'), breath * DEG(0.9), 0, 0)
  addRotation(bones.get('neck'), breath * DEG(-0.5), 0, 0)

  // Weight shift: much slower, and on the hips/spine so the whole figure
  // moves as one rather than the head drifting on a static body.
  const sway = Math.sin(t * (2 * Math.PI / 11))
  const sway2 = Math.sin(t * (2 * Math.PI / 7) + 1.1)
  addRotation(bones.get('hips'), 0, sway * DEG(1.4), sway2 * DEG(0.7))
  addRotation(bones.get('spine'), 0, sway * DEG(-0.6), sway2 * DEG(-0.4))

  // Micro head motion — people are never perfectly still above the neck.
  addRotation(bones.get('head'),
    Math.sin(t * (2 * Math.PI / 6.3) + 0.4) * DEG(1.2),
    Math.sin(t * (2 * Math.PI / 9.1)) * DEG(1.8),
    Math.sin(t * (2 * Math.PI / 13)) * DEG(0.8))

  // Arms hang with a slight, slow life of their own.
  const armDrift = Math.sin(t * (2 * Math.PI / 8.5))
  addRotation(bones.get('leftUpperArm'), armDrift * DEG(0.8), 0, 0)
  addRotation(bones.get('rightUpperArm'), -armDrift * DEG(0.8), 0, 0)
}

/**
 * Co-speech motion, applied only while the reply audio is playing.
 *
 * `level` is the smoothed 0..1 speech envelope from SpeechAmplitude. Driving
 * the motion from the envelope rather than a free-running clock is what makes
 * it look connected to the words: the head and hands move when there is sound
 * and settle when there isn't, which is what listeners actually key on.
 */
export function applySpeakingMotion(bones, level, t) {
  if (level <= 0.01) return

  // Head: a small nod on the envelope plus a slower turn, so emphasis lands
  // with the voice instead of ticking metronomically.
  addRotation(bones.get('head'),
    -level * DEG(4.5) + Math.sin(t * 5.5) * level * DEG(1.6),
    Math.sin(t * 2.3) * level * DEG(3.5),
    Math.sin(t * 3.1) * level * DEG(1.2))
  addRotation(bones.get('neck'), -level * DEG(1.8), Math.sin(t * 2.3) * level * DEG(1.2), 0)

  // Hands: small co-speech beats. Both arms, slightly out of phase, lifting
  // from the elbow more than the shoulder — which is how people actually
  // gesture in conversation rather than semaphoring from the shoulder.
  const beat = Math.sin(t * 3.4)
  const beat2 = Math.sin(t * 3.4 + 2.0)
  addRotation(bones.get('rightUpperArm'), -level * DEG(7) + beat * level * DEG(3), 0, 0)
  addRotation(bones.get('rightLowerArm'), -level * DEG(10), beat * level * DEG(7), 0)
  addRotation(bones.get('rightHand'), beat * level * DEG(5), 0, 0)

  addRotation(bones.get('leftUpperArm'), -level * DEG(5) + beat2 * level * DEG(2.5), 0, 0)
  addRotation(bones.get('leftLowerArm'), -level * DEG(7), beat2 * level * DEG(-5), 0)
  addRotation(bones.get('leftHand'), beat2 * level * DEG(4), 0, 0)

  // The torso answers the gesture slightly — otherwise the arms look bolted
  // to a mannequin.
  addRotation(bones.get('chest'), level * DEG(1.2), beat * level * DEG(1.5), 0)
  addRotation(bones.get('spine'), 0, beat * level * DEG(0.8), 0)
}
