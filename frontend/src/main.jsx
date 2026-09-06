import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import 'flag-icons/css/flag-icons.min.css'
import './styles/theme.css'
import './styles/app.css'
import './styles/cosmos-account-validator-identity.css'
import './styles/cosmos-activity-badges.css'
import './styles/cosmos-detail-surfaces.css'
import { initializeTheme } from './utils/theme'
import { SelectedNetworkProvider } from './context/SelectedNetworkContext'

initializeTheme()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <SelectedNetworkProvider>
      <App />
    </SelectedNetworkProvider>
  </StrictMode>,
)
