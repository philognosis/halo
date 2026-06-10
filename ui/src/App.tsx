import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Shell from './layout/Shell'
import Dashboard from './pages/Dashboard'
import ChatPage from './pages/ChatPage'
import PeoplePage from './pages/PeoplePage'
import PersonDetailPage from './pages/PersonDetailPage'
import OpportunitiesPage from './pages/OpportunitiesPage'
import TeamsPage from './pages/TeamsPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Shell />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/people" element={<PeoplePage />} />
          <Route path="/people/:id" element={<PersonDetailPage />} />
          <Route path="/opportunities" element={<OpportunitiesPage />} />
          <Route path="/teams" element={<TeamsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
