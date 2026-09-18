import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout.jsx'
import Atlas from './pages/Atlas.jsx'
import StagePlaceholder from './pages/StagePlaceholder.jsx'
import AvatarTest from './pages/AvatarTest.jsx'

/**
 * Route shell (T1.30). /atlas has real content (T1.32); /monitor and /watch
 * are placeholder cards until Stage 2/3 exist — this repo never imports code
 * from a stage that doesn't exist yet, per cureva-architecture.md's import
 * direction rule (stage2 imports stage1, never the reverse).
 */
export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Atlas />} />
        <Route path="/atlas" element={<Atlas />} />
        <Route path="/avatar-test" element={<AvatarTest />} />
        <Route path="/monitor" element={
          <StagePlaceholder stage="Stage 2" title="Monitor" description="ReviewCrew — the Tribunal, human-gate escalation. Built in Stage 2." />
        } />
        <Route path="/watch" element={
          <StagePlaceholder stage="Stage 3" title="Watch" description="StudyWatch — forecast fan chart, surveillance report. Built in Stage 3." />
        } />
      </Route>
    </Routes>
  )
}
