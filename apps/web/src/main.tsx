import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MsalProvider } from '@azure/msal-react'
import './index.css'
import './i18n'
import App from './App.tsx'
import { msalInstance } from './auth/msal'

const queryClient = new QueryClient()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MsalProvider instance={msalInstance}>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </MsalProvider>
  </StrictMode>,
)
