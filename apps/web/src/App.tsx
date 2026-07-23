import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL

interface HealthResponse {
  status: string
}

async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/health`)
  if (!response.ok) {
    throw new Error(`health check failed: ${response.status}`)
  }
  return response.json()
}

function App() {
  const { t } = useTranslation()
  const { data, error, isLoading } = useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
  })

  return (
    <main>
      <h1>{t('app.title', 'Smart VMS')}</h1>
      {isLoading && <p>{t('health.checking', 'Checking core-api…')}</p>}
      {error && <p role="alert">{t('health.error', 'core-api unreachable')}</p>}
      {data && <p>{t('health.status', 'core-api status: {{status}}', { status: data.status })}</p>}
    </main>
  )
}

export default App
