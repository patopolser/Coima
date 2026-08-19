import { useQuery } from '@tanstack/react-query'
import { fetchChecks } from '../api/client'
import { useLang } from './useLang'

/**
 * Map of check key -> localized label, sourced from the /checks metadata.
 * Reuses the same react-query cache key the detail pages already populate
 * (['checks', lang]), so it does not trigger an extra request.
 */
export function useCheckLabels() {
  const { lang } = useLang()
  const { data } = useQuery({ queryKey: ['checks', lang], queryFn: fetchChecks })
  const map = {}
  ;(data || []).forEach(c => { map[c.key] = c.label })
  return map
}
