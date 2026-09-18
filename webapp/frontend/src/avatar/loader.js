/**
 * Avatar loading + humanoid bone mapping (T1.31).
 *
 * PORTED, NOT REWRITTEN, from the Setu/Gestura repo's frontend/avatar/loader.ts
 * — the bone-name mapping table and isolated-scene setup below are the same
 * logic, translated from TypeScript to plain JS for this Vite+React project.
 *
 * Two things differ from what cureva-architecture.md / cureva-stage1-trd.md
 * assumed ("Kalidokit + three-vrm, reused wholesale"), discovered only by
 * actually inspecting the reused asset rather than trusting the doc:
 *
 *  1. avatar.glb is a plain glTF with NO VRM extension and NO VRMHumanoid
 *     metadata — @pixiv/three-vrm has nothing to load here. This is exactly
 *     the rig Gestura's own loader.ts describes: Sketchfab bone names with
 *     numeric suffixes ("LeftHand_18"), an A-pose (not T-pose), manually
 *     mapped via BONE_MAP below. Ported as-is; a real VRM asset would use
 *     @pixiv/three-vrm's own loader instead, which is why that package is
 *     still in package.json even though this file doesn't call it.
 *  2. The rig has ZERO morph targets (confirmed by parsing the .glb's own
 *     JSON chunk — meshes carry no extras.targetNames at all) and no jaw
 *     bone (only Head/Neck). "Jaw-open blendshape driven by TTS audio
 *     amplitude" cannot be built on this specific asset because the
 *     blendshape it would drive does not exist. The amplitude-driven talking
 *     motion in `speech.js` drives a subtle Head-bone rotation instead — the
 *     closest available proxy on this rig, not the originally-designed
 *     approach. A VRM avatar with real jaw/mouth blendshapes would use those.
 */
import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'

/** Mixamo/Unity bone name (numeric suffix stripped) -> humanoid role. */
const BONE_MAP = {
  Hips: 'hips', Spine: 'spine', Spine1: 'chest', Spine2: 'upperChest',
  Neck: 'neck', Head: 'head',
  LeftShoulder: 'leftShoulder', LeftArm: 'leftUpperArm', LeftForeArm: 'leftLowerArm', LeftHand: 'leftHand',
  RightShoulder: 'rightShoulder', RightArm: 'rightUpperArm', RightForeArm: 'rightLowerArm', RightHand: 'rightHand',
  LeftUpLeg: 'leftUpperLeg', LeftLeg: 'leftLowerLeg', LeftFoot: 'leftFoot', LeftToeBase: 'leftToes',
  RightUpLeg: 'rightUpperLeg', RightLeg: 'rightLowerLeg', RightFoot: 'rightFoot', RightToeBase: 'rightToes',
}

/** `LeftHand_18` -> `LeftHand`. Sketchfab appends `_<n>` to every bone. */
export function stripSuffix(name) {
  return name.replace(/_\d+$/, '')
}

const REQUIRED = ['hips', 'spine', 'neck', 'head', 'leftUpperArm', 'rightUpperArm']

/** Load the .glb and build the humanoid bone map. No lights, no animation —
 * isolated load first, same ordering discipline as the source loader.ts. */
export async function loadAvatar(url) {
  const gltf = await new GLTFLoader().loadAsync(url)
  const gltfScene = gltf.scene
  gltfScene.updateMatrixWorld(true)

  const bones = new Map()
  const unmappedBones = []
  let boneCount = 0

  gltfScene.traverse((object) => {
    if (!object.isBone) return
    boneCount += 1
    const humanoid = BONE_MAP[stripSuffix(object.name)]
    if (humanoid) bones.set(humanoid, object)
    else unmappedBones.push(object.name)
  })

  const restPose = new Map()
  for (const [name, bone] of bones) {
    restPose.set(name, { quaternion: bone.quaternion.clone(), position: bone.position.clone() })
  }

  const box = new THREE.Box3().setFromObject(gltfScene)
  const size = box.getSize(new THREE.Vector3())
  const head = bones.get('head')
  const hips = bones.get('hips')
  const upright = !!head && !!hips &&
    head.getWorldPosition(new THREE.Vector3()).y > hips.getWorldPosition(new THREE.Vector3()).y

  return {
    gltfScene,
    bones,
    restPose,
    report: {
      boneCount,
      mappedCount: bones.size,
      missingRequired: REQUIRED.filter((b) => !bones.has(b)),
      unmappedBones,
      height: size.y,
      upright,
      animationCount: gltf.animations.length,
    },
  }
}

/** Scene + camera framed on the loaded avatar. Ported from createIsolatedScene. */
export function createScene(avatar, width, height) {
  const scene = new THREE.Scene()
  // Transparent, so the CSS daylight wash behind the canvas shows through and
  // she is lit by the same sky the rest of the page uses. A painted scene
  // background here would punch a flat rectangle into that gradient.
  scene.background = null
  scene.add(avatar.gltfScene)
  // Hemisphere rather than flat ambient: white from above, the page's sky tint
  // bouncing up from below, which keeps her from looking cut out on white.
  scene.add(new THREE.HemisphereLight(0xffffff, 0xd7e6f5, 2.4))
  const key = new THREE.DirectionalLight(0xffffff, 1.9)
  key.position.set(1, 3, 4)
  scene.add(key)
  const rim = new THREE.DirectionalLight(0xcfe2f2, 0.8)
  rim.position.set(-2, 1.4, -3)
  scene.add(rim)

  const box = new THREE.Box3().setFromObject(avatar.gltfScene)
  const centre = box.getCenter(new THREE.Vector3())
  const span = box.getSize(new THREE.Vector3()).y || 1

  const camera = new THREE.PerspectiveCamera(35, width / height, 0.01, 100)
  // Framed on the upper body/head, the visible part in a chat-avatar layout.
  camera.position.set(centre.x, centre.y + span * 0.28, centre.z + span * 0.9)
  camera.lookAt(centre.x, centre.y + span * 0.22, centre.z)
  return { scene, camera }
}
