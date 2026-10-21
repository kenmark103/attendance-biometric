import { useEffect, useState } from 'react';
import { fetchDashboardMetrics } from '../api.js';

/**
 * Loads backend-owned dashboard metrics for the current filter scope.
 * A changing filter cancels the previous request so stale responses cannot
 * replace the metrics for the current view.
 */
export default function useDashboardMetrics({ day, dates, teams, shift, excludeNeverPunched }) {
  const [metrics, setMetrics] = useState(null);
  const metricsKey = [
    day || '', dates[0] || '', dates[dates.length - 1] || '',
    teams ? teams.join(',') : '', shift, excludeNeverPunched ? 'exclude' : '',
  ].join('|');

  useEffect(() => {
    const from = day || dates[0];
    const to = day || dates[dates.length - 1];
    if (!from || !to) return undefined;

    let cancelled = false;
    const controller = new AbortController();
    fetchDashboardMetrics({
      date_from: from,
      date_to: to,
      teams: teams ? teams.join(',') : undefined,
      shift: shift !== 'all' ? shift : undefined,
      exclude_never_punched: excludeNeverPunched || undefined,
    }, { signal: controller.signal })
      .then((result) => { if (!cancelled) setMetrics(result); })
      .catch((err) => {
        if (!cancelled && err.name !== 'AbortError') setMetrics(null);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [metricsKey]);

  return metrics;
}
