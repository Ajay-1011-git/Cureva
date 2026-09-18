import { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import gsap from 'gsap'
import Icon from './Icon.jsx'
import { familyOf, intFor, labelFor, CODE_BLURB } from '../lib/findingCodes.js'

/**
 * Act 2 — the finding graph in 3D.
 *
 * Seeded at backend startup by running every detector across the study, so it
 * shows the real picture (~190 findings) on first load; a conversation then
 * adds to it visibly.
 *
 * Three decisions worth stating, because the obvious versions all look wrong:
 *
 *  - **Connected clusters get a sphere each, placed on a Fibonacci shell.**
 *    A force simulation was the first instinct and is the wrong tool: with
 *    ~190 nodes it costs frames to converge and lands somewhere slightly
 *    different every reload, which makes it useless for narrating a demo
 *    twice in a row. This is deterministic and instant.
 *  - **Isolated findings are packed into a thin outer shell, not scattered
 *    through the volume.** Spreading 150 unconnected VISIT_OUT_OF_WINDOW dots
 *    evenly reads as a pattern that isn't there — the eye finds structure in
 *    uniform noise. Pushing them to a halo says what is true: these are real
 *    findings with no relationship to anything else, and the structure in the
 *    middle is the part that means something.
 *  - **Colour carries the family, not the code.** Twelve hues cannot survive
 *    an all-pairs colour-blindness check, and in a rotating 3D scene any two
 *    nodes can end up side by side, so all-pairs is the honest test. Five
 *    validated hues plus a reserved neutral; the code name is always one
 *    hover away and always on the filter chip. See lib/findingCodes.js.
 *
 * The scene is lit like the rest of the product — daylight on paper, a light
 * fog so distance reads as depth rather than as a smaller dot.
 */

const SURFACE = 0xf5f5f5

/** Deterministic cluster layout. Returns finding_id -> THREE.Vector3. */
function layout3d(nodes, clusters) {
  const pos = new Map()
  const connected = clusters.filter((c) => c.length > 1)
                            .sort((a, b) => b.length - a.length)
  const singles = clusters.filter((c) => c.length === 1).map((c) => c[0])

  // Connected groups: Fibonacci shell so they spread evenly without lining up.
  const golden = Math.PI * (3 - Math.sqrt(5))
  connected.forEach((cluster, ci) => {
    const n = Math.max(connected.length, 1)
    const y = n === 1 ? 0 : 1 - (ci / (n - 1)) * 2
    const rad = Math.sqrt(Math.max(0, 1 - y * y))
    const theta = golden * ci
    const shell = 26 + Math.min(18, cluster.length * 0.9)
    const gx = Math.cos(theta) * rad * shell
    const gy = y * shell * 0.62
    const gz = Math.sin(theta) * rad * shell

    // Members sit on a small sphere around their group's centre.
    const r = 3.2 + Math.min(9, cluster.length * 0.55)
    cluster.forEach((id, i) => {
      const yy = cluster.length === 1 ? 0 : 1 - (i / (cluster.length - 1)) * 2
      const rr = Math.sqrt(Math.max(0, 1 - yy * yy))
      const th = golden * i
      pos.set(id, new THREE.Vector3(
        gx + Math.cos(th) * rr * r, gy + yy * r, gz + Math.sin(th) * rr * r))
    })
  })

  // Unconnected findings: a thin outer halo, deliberately not filling the
  // volume between the clusters.
  singles.forEach((id, i) => {
    const y = singles.length === 1 ? 0 : 1 - (i / (singles.length - 1)) * 2
    const rad = Math.sqrt(Math.max(0, 1 - y * y))
    const th = golden * i
    const shell = 62 + (i % 4) * 2.2
    pos.set(id, new THREE.Vector3(
      Math.cos(th) * rad * shell, y * shell * 0.55, Math.sin(th) * rad * shell))
  })

  nodes.forEach((n, i) => {
    if (!pos.has(n.finding_id)) {
      pos.set(n.finding_id, new THREE.Vector3(i % 20 - 10, (i % 7) - 3, (i % 13) - 6))
    }
  })
  return pos
}

export default function FindingGraph3D({ snapshot, subject, newIds,
                                         codeFilter, onSelect, selectedId }) {
  const mountRef = useRef(null)
  const stateRef = useRef({})
  const [hover, setHover] = useState(null)
  const builtOnce = useRef(false)

  const pos = useMemo(
    () => layout3d(snapshot.nodes, snapshot.clusters), [snapshot])

  // ---- one-time scene setup
  useEffect(() => {
    const el = mountRef.current
    if (!el) return
    const width = el.clientWidth || 720
    const height = el.clientHeight || 520

    const scene = new THREE.Scene()
    scene.background = new THREE.Color(SURFACE)
    // Distance reads as haze rather than as a smaller dot, which is what makes
    // the outer halo look like a shell instead of a scatter of specks.
    scene.fog = new THREE.Fog(SURFACE, 118, 300)

    const camera = new THREE.PerspectiveCamera(48, width / height, 0.1, 2000)
    camera.position.set(0, 26, 132)

    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setSize(width, height)
    el.innerHTML = ''
    el.appendChild(renderer.domElement)

    // Daylight on paper: a cool sky above, the page's own tint bouncing back
    // from below, and one soft key so spheres still read as spheres.
    scene.add(new THREE.HemisphereLight(0xffffff, 0xd7e6f5, 2.1))
    const key = new THREE.DirectionalLight(0xffffff, 1.5)
    key.position.set(40, 70, 90)
    scene.add(key)
    const fill = new THREE.DirectionalLight(0xdce9f6, 0.7)
    fill.position.set(-60, -20, -40)
    scene.add(fill)

    const group = new THREE.Group()
    scene.add(group)

    const raycaster = new THREE.Raycaster()
    raycaster.params.Points = { threshold: 2 }
    const pointer = new THREE.Vector2()

    Object.assign(stateRef.current, {
      scene, camera, renderer, group, raycaster, pointer,
      drag: null, rotX: 0.15, rotY: 0, zoom: 132, auto: true,
    })

    // --- interaction: drag to orbit, wheel to zoom, click to select
    const onDown = (e) => {
      stateRef.current.drag = { x: e.clientX, y: e.clientY, moved: false }
      stateRef.current.auto = false
    }
    const onMove = (e) => {
      const st = stateRef.current
      const rect = renderer.domElement.getBoundingClientRect()
      pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1
      pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1
      if (st.drag) {
        const dx = e.clientX - st.drag.x
        const dy = e.clientY - st.drag.y
        if (Math.abs(dx) + Math.abs(dy) > 3) st.drag.moved = true
        st.rotY += dx * 0.005
        st.rotX = Math.max(-1.2, Math.min(1.2, st.rotX + dy * 0.004))
        st.drag.x = e.clientX
        st.drag.y = e.clientY
      }
    }
    const onUp = () => {
      const st = stateRef.current
      if (st.drag && !st.drag.moved && st.hovered) st.onSelect?.(st.hovered)
      else if (st.drag && !st.drag.moved) st.onSelect?.(null)
      st.drag = null
    }
    const onWheel = (e) => {
      e.preventDefault()
      const st = stateRef.current
      st.zoom = Math.max(40, Math.min(320, st.zoom + e.deltaY * 0.12))
    }
    renderer.domElement.addEventListener('pointerdown', onDown)
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    renderer.domElement.addEventListener('wheel', onWheel, { passive: false })

    let raf
    const tick = () => {
      const st = stateRef.current
      if (st.auto) st.rotY += 0.0016            // slow drift until touched
      group.rotation.y = st.rotY
      group.rotation.x = st.rotX
      camera.position.setLength(st.zoom)
      camera.lookAt(0, 0, 0)

      // hover test
      if (st.pickables?.length) {
        raycaster.setFromCamera(pointer, camera)
        const hit = raycaster.intersectObjects(st.pickables, false)[0]
        const id = hit?.object?.userData?.finding_id ?? null
        if (id !== st.hovered) {
          // Lift the node the pointer is on, and put the previous one back.
          if (st.hoveredMesh) gsap.to(st.hoveredMesh.scale, {
            x: st.hoveredMesh.userData.r, y: st.hoveredMesh.userData.r,
            z: st.hoveredMesh.userData.r, duration: 0.25, ease: 'power2.out' })
          st.hovered = id
          st.hoveredMesh = hit?.object || null
          if (st.hoveredMesh) {
            const r = st.hoveredMesh.userData.r * 1.55
            gsap.to(st.hoveredMesh.scale, { x: r, y: r, z: r, duration: 0.25, ease: 'back.out(2)' })
          }
          setHover(id)
          renderer.domElement.style.cursor = id ? 'pointer' : 'grab'
        }
      }
      renderer.render(scene, camera)
      raf = requestAnimationFrame(tick)
    }
    tick()

    const onResize = () => {
      const w = el.clientWidth || width
      const h = el.clientHeight || height
      camera.aspect = w / h
      camera.updateProjectionMatrix()
      renderer.setSize(w, h)
    }
    window.addEventListener('resize', onResize)

    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', onResize)
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      renderer.domElement.removeEventListener('pointerdown', onDown)
      renderer.domElement.removeEventListener('wheel', onWheel)
      renderer.dispose()
    }
  }, [])

  // keep the click handler current without rebuilding the scene
  useEffect(() => { stateRef.current.onSelect = onSelect }, [onSelect])

  // ---- rebuild the geometry whenever the data or filter changes
  useEffect(() => {
    const st = stateRef.current
    if (!st.group) return
    const { group } = st
    // A hovered mesh from the previous build is about to be disposed; drop the
    // reference first or the next hover tween writes to a dead object.
    st.hoveredMesh = null
    while (group.children.length) {
      const c = group.children.pop()
      c.geometry?.dispose?.()
      c.material?.dispose?.()
    }

    const shown = snapshot.nodes.filter((n) => !codeFilter || n.code === codeFilter)
    const shownIds = new Set(shown.map((n) => n.finding_id))
    const pickables = []

    // edges first, so nodes draw over them
    const edgePoints = []
    snapshot.edges.forEach((e) => {
      if (!shownIds.has(e.from_finding_id) || !shownIds.has(e.to_finding_id)) return
      const a = pos.get(e.from_finding_id)
      const b = pos.get(e.to_finding_id)
      if (a && b) edgePoints.push(a.x, a.y, a.z, b.x, b.y, b.z)
    })
    if (edgePoints.length) {
      const g = new THREE.BufferGeometry()
      g.setAttribute('position', new THREE.Float32BufferAttribute(edgePoints, 3))
      group.add(new THREE.LineSegments(g, new THREE.LineBasicMaterial({
        color: 0x9aa4b2, transparent: true, opacity: 0.5, fog: true })))
    }

    const sphere = new THREE.SphereGeometry(1, 16, 13)
    const meshes = []
    shown.forEach((n) => {
      const p = pos.get(n.finding_id)
      if (!p) return
      const isSubject = n.usubjid === subject
      const isNew = newIds.has(n.finding_id)
      const isSelected = n.finding_id === selectedId
      const marked = isSubject || isNew || isSelected
      const hub = snapshot.centrality[n.finding_id] || 0
      const r = 1.25 + Math.min(2.2, hub * 26) + (isSubject ? 0.7 : 0)

      // On a light surface, emphasis is opacity and size — not glow. An
      // emissive node on white just looks washed out, which reads as *less*
      // important rather than more.
      const mat = new THREE.MeshStandardMaterial({
        color: intFor(n.code),
        roughness: 0.52,
        metalness: 0.0,
        transparent: true,
        opacity: marked ? 1 : 0.82,
      })
      const mesh = new THREE.Mesh(sphere, mat)
      mesh.position.copy(p)
      mesh.scale.setScalar(r)
      mesh.userData = { finding_id: n.finding_id, r }
      group.add(mesh)
      pickables.push(mesh)
      meshes.push(mesh)

      // A ring marks anything belonging to the current subject, anything the
      // conversation just added, and whatever is selected — the three things
      // a viewer needs to find instantly. Obsidian for "this subject", the
      // accent for "said just now", so the two never blur together.
      if (marked) {
        const ring = new THREE.Mesh(
          new THREE.SphereGeometry(1, 16, 13),
          new THREE.MeshBasicMaterial({
            color: isNew ? 0x2597d0 : isSelected ? 0x070709 : 0x60606c,
            transparent: true, opacity: isNew ? 0.4 : 0.26, wireframe: true, fog: true }))
        ring.position.copy(p)
        ring.scale.setScalar(r * 2.1)
        group.add(ring)
      }
    })
    st.pickables = pickables

    // Pop the nodes in from the centre outward the first time the graph
    // appears. On a filter change the set is already familiar, so it just
    // fades — re-staggering 190 spheres every time you click a chip would be
    // a performance you have to sit through rather than information.
    if (meshes.length) {
      if (!builtOnce.current) {
        builtOnce.current = true
        gsap.from(meshes.map((m) => m.scale), {
          x: 0, y: 0, z: 0, duration: 0.85, ease: 'back.out(1.6)',
          stagger: { amount: 0.9, from: 'center' },
        })
      } else {
        gsap.from(meshes.map((m) => m.material), {
          opacity: 0, duration: 0.35, ease: 'power2.out',
        })
      }
    }
  }, [snapshot, pos, subject, newIds, codeFilter, selectedId])

  const hoveredNode = hover && snapshot.nodes.find((n) => n.finding_id === hover)
  const hoveredFamily = hoveredNode && familyOf(hoveredNode.code)

  return (
    <div className="graph-stage">
      <div ref={mountRef} className="graph-mount" data-testid="finding-graph-3d" />

      <div className="graph-hud">
        <Icon name="layers" size={12} />
        drag to rotate · scroll to zoom · click a node
      </div>

      {hoveredNode && (
        <div className="graph-hover">
          <span className="graph-hover-code">
            <i style={{ background: hoveredFamily.color }} />
            {labelFor(hoveredNode.code)}
          </span>
          <div className="graph-hover-meta">
            {hoveredFamily.label} · {hoveredNode.usubjid || hoveredNode.site}
            {CODE_BLURB[hoveredNode.code] && <> — {CODE_BLURB[hoveredNode.code]}</>}
          </div>
        </div>
      )}
    </div>
  )
}
