import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout.jsx'
import Atlas from './pages/Atlas.jsx'
import AvatarTest from './pages/AvatarTest.jsx'

/**
 * Route shell (T1.30).
 *
 * Only the shipped Atlas surface is routed. Work that is not finished is not
 * advertised here at all — not as a nav link, and not as a placeholder card
 * describing what it will eventually be. A card naming a feature that does not
 * exist is a promise the running app cannot keep, and anyone opening the demo
 * reads it as part of the product.
 *
 * Unknown paths redirect to /atlas rather than rendering nothing, so an old
 * deep link lands somewhere real instead of on a blank page.
 */
export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Atlas />} />
        <Route path="/atlas" element={<Atlas />} />
        <Route path="/avatar-test" element={<AvatarTest />} />
        <Route path="*" element={<Navigate to="/atlas" replace />} />
      </Route>
    </Routes>
  )
}
