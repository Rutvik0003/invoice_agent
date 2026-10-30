import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, FileText, Loader2, XCircle } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { fetchHealth } from '@/lib/api'

function ModelRow({ name, configured }: { name: string; configured: boolean }) {
  return (
    <div className="flex items-center justify-between py-2">
      <span className="text-sm font-medium">{name}</span>
      {configured ? (
        <span className="flex items-center gap-1.5 text-sm text-green-700">
          <CheckCircle2 className="size-4" /> Configured
        </span>
      ) : (
        <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <XCircle className="size-4" /> API key missing
        </span>
      )}
    </div>
  )
}

export default function App() {
  const health = useQuery({ queryKey: ['health'], queryFn: fetchHealth })

  return (
    <main className="min-h-screen bg-muted/40 p-8">
      <div className="mx-auto max-w-md space-y-6">
        <div className="flex items-center gap-2">
          <FileText className="size-6" />
          <h1 className="text-xl font-semibold">Invoice Agent</h1>
          <Badge variant="secondary" className="ml-auto">
            Demo data — Zenith Retail Pvt Ltd
          </Badge>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>System status</CardTitle>
            <CardDescription>Backend health and configured AI models</CardDescription>
          </CardHeader>
          <CardContent>
            {health.isPending && (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" /> Checking backend…
              </p>
            )}
            {health.isError && (
              <p className="text-sm text-red-700">Backend unreachable: {health.error.message}</p>
            )}
            {health.data && (
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Status</span>
                  <Badge className="bg-green-600 text-white">{health.data.status}</Badge>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Version</span>
                  <span className="font-mono text-sm">{health.data.version}</span>
                </div>
                <div className="divide-y border-t">
                  <ModelRow name="Google Gemini" configured={health.data.models_configured.gemini} />
                  <ModelRow name="Groq" configured={health.data.models_configured.groq} />
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </main>
  )
}
