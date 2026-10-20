// Dashboard shell: header, nav tabs (links), sticky filter bar, routes.
// URL query string is the single source of truth for filters.
import React, { useMemo, useState, useEffect } from 'react';
import { Routes, Route, Link, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import logoUrl from './assets/tbl-logo.svg';
import { colors } from './theme.js';
import { fetchDashboardMetrics } from './api.js';
import AuthHeader from './components/AuthHeader.jsx';
import FilterBar from './components/FilterBar.jsx';
import Overview from './views/Overview.jsx';
import Teams, { TeamDetail } from './views/Teams.jsx';
import Employees from './views/Employees.jsx';
import Exceptions from './views/Exceptions.jsx';
import DataHealth from './views/DataHealth.jsx';
import LeaveImport from './views/LeaveImport.jsx';
import {
  todayNairobi, leaveLoadedFor, adaptMetrics,
  shortDateISO, dayAndShortISO, isWeekendISO,
} from './metrics.js';
import {
  parseFilters, serializeFilters, rangeDates, teamMaps, defaultFilters,
} from './filters.js';

const TABS = [
  ['/', 'Overview'],
  ['/teams', 'Teams'],
  ['/employees', 'Employees'],
  ['/exceptions', 'Exceptions'],
  ['/data-health', 'Data health'],
  ['/leave', 'Leave data'],
];

const SPECIFIC_DEFAULTS = { view: 'list', q: '', type: 'all', sort: '', allteams: false, group: '' };

// Rendered before the metrics request resolves / if it fails.
const EMPTY_AGG = {
  employees: [], daily: [], teams: [], headcount: 0, attendanceRate: null,
  isProvisional: false, provisionalDays: 0, noDataDays: 0, presentDays: 0,
  onLeaveDays: 0, absentDays: 0, unverifiedDays: 0, leaveConflictDays: 0,
  missingCheckouts: 0, neverPunchedCount: 0, avgHours: null, biometricDays: 0,
};

export function LeaveBanner() {
  return (
    <div style={{
      border: `1px solid #c58a1b`, background: '#fbf3dc', borderRadius: 4,
      padding: '9px 14px', fontSize: 13, marginBottom: 16, color: colors.ink,
    }}>
      Leave data has not been loaded from Zoho. Absences are shown as &ldquo;No record&rdquo; and are not reconciled with approved leave.
    </div>
  );
}

export function scopeCaptionLine(caption, extra) {
  return (
    <div style={{ fontSize: 12, color: colors.muted, marginBottom: 24 }}>
      Figures above reflect: <strong style={{ color: colors.ink }}>{caption}</strong>
      {extra && <> · {extra}</>}. Public holidays are excluded from the rate calculations. Weekend dates carry no expected shift and are excluded from rates.
    </div>
  );
}

export default function Dashboard({ records, calMeta, calendarOk, coverage, roster, user, onLogout, onSyncNow, syncing, syncMsg }) {
  const today = useMemo(() => todayNairobi(), []);
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();

  const months = useMemo(() => [...new Set(records.map((r) => r.date.slice(0, 7)))].sort(), [records]);
  const teamNames = useMemo(() => [...new Set(records.map((r) => r.team || 'Unassigned'))].sort(), [records]);
  const { slugToName } = useMemo(() => teamMaps(teamNames), [teamNames]);

  const filters = parseFilters(searchParams.toString(), months, slugToName, today);

  function update(patch, opts = {}) {
    const dflt = defaultFilters(months, today);
    const next = { ...filters, ...patch };
    const base = opts.reset ? new URLSearchParams() : new URLSearchParams(searchParams.toString());
    for (const k of ['month', 'range', 'day', 'shift', 'teams', 'nopunch']) base.delete(k);
    // month change resets range/day unless explicitly given
    if (patch.month !== undefined && patch.month !== filters.month && patch.range === undefined && !opts.reset) {
      next.range = next.month === today.slice(0, 7) ? rangeDefaultForMonth(next.month, today) : 'whole';
      next.day = '';
    }
    const shared = serializeFilters(next, months, today, dflt);
    for (const [k, v] of shared) base.set(k, v);
    for (const k of Object.keys(SPECIFIC_DEFAULTS)) {
      const v = next[k];
      if (v === undefined || v === SPECIFIC_DEFAULTS[k] || v === '' || v === false) base.delete(k);
      else base.set(k, String(v));
    }
    navigate({ pathname: opts.path || location.pathname, search: base.toString() ? `?${base}` : '' }, { replace: !!opts.replace });
  }

  function switchTab(path) {
    // shared filters preserved; view-specific params dropped
    const shared = serializeFilters(filters, months, today);
    navigate({ pathname: path, search: shared.toString() ? `?${shared}` : '' });
  }

  const dates = useMemo(() => rangeDates(filters.month, filters.range), [filters.month, filters.range]);
  const scopeDates = filters.day ? [filters.day] : dates;

  const teamSet = useMemo(() => {
    if (!filters.teams) return null;
    return new Set(filters.teams.map((s) => slugToName.get(s)).filter(Boolean));
  }, [filters.teams, slugToName]);

  const rows = useMemo(() => {
    const inScope = new Set(scopeDates);
    return records.filter((r) =>
      inScope.has(r.date) &&
      (!teamSet || teamSet.has(r.team || 'Unassigned')) &&
      (filters.shift === 'all' || (r.assignedShift || r.matchedShift || '').toLowerCase() === filters.shift));
  }, [records, scopeDates, teamSet, filters.shift]);

  // Team membership: latest snapshot team wins, roster team as fallback.
  const rosterInScope = useMemo(() => {
    const latest = new Map();
    for (const r of records) {
      const prev = latest.get(r.employeeId);
      if (!prev || prev.date < r.date) latest.set(r.employeeId, r);
    }
    return roster
      .map((e) => ({ ...e, team: (latest.get(e.id)?.team) || e.team || 'Unassigned' }))
      .filter((e) => !teamSet || teamSet.has(e.team));
  }, [roster, records, teamSet]);

  const leaveLoaded = leaveLoadedFor(scopeDates, coverage?.leave_by_month ?? []);
  const leaveActive = !!(coverage?.leave_coverage?.through_date);
  const ctx = useMemo(() => ({
    today,
    leaveLoaded: leaveLoaded || leaveActive,
    leaveActive,
    coverageThrough: coverage?.leave_coverage?.through_date || null,
    coveredDates: new Set((coverage?.per_date ?? []).filter((d) => d.count > 0).map((d) => d.date)),
    trustZoho: coverage?.trust_zoho_presence !== false,
    calMeta: calMeta || {},
    excludeNeverPunched: filters.nopunch,
  }), [today, leaveLoaded, leaveActive, coverage, calMeta, filters.nopunch]);
  const [metrics, setMetrics] = useState(null);

  const metricsKey = [
    filters.day || '', dates[0] || '', dates[dates.length - 1] || '',
    filters.teams ? filters.teams.join(',') : '', filters.shift,
    filters.nopunch ? 'exclude' : '',
  ].join('|');

  useEffect(() => {
    const from = filters.day || dates[0];
    const to = filters.day || dates[dates.length - 1];
    if (!from || !to) return undefined;
    let cancelled = false;
    fetchDashboardMetrics({
      date_from: from,
      date_to: to,
      teams: filters.teams ? filters.teams.join(',') : undefined,
      shift: filters.shift !== 'all' ? filters.shift : undefined,
      exclude_never_punched: filters.nopunch || undefined,
    }).then((m) => { if (!cancelled) setMetrics(m); })
      .catch(() => { if (!cancelled) setMetrics(null); });
    return () => { cancelled = true; };
  }, [metricsKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const agg = useMemo(() => adaptMetrics(metrics) || EMPTY_AGG, [metrics]);

  const daily = useMemo(() => (agg.daily || []).map((d) => ({
    ...d,
    label: dayAndShortISO(d.date),
    full: `${dayAndShortISO(d.date)} ${shortDateISO(d.date).split(' ')[0]}`,
    weekend: isWeekendISO(d.date),
  })), [agg.daily]);

  const teamHeadcounts = useMemo(() => {
    const m = {};
    for (const e of agg.employees) m[e.team] = (m[e.team] || 0) + 1;
    return m;
  }, [agg.employees]);

  const daysInView = useMemo(() => dates.map((date) => {
    const hol = rows.find((r) => r.date === date)?.isHoliday;
    return { date, weekend: isWeekendISO(date), holiday: !!hol };
  }), [dates, rows]);

  const activeTab = '/' + (location.pathname.split('/')[1] || '');
  const isAdmin = user?.role === 'admin';
  const visibleTabs = TABS.filter(([path]) => path !== '/leave' || isAdmin);

  const scope = {
    filters, months, teamNames, slugToName, today, dates, scopeDates, rows,
    rosterInScope, leaveLoaded, leaveActive, isAdmin, calendarOk, ctx, agg, daily, teamHeadcounts, daysInView,
    apiTeams: agg.teams, coverage, update, switchTab,
  };

  return (
    <div style={{
      background: colors.paper, color: colors.ink, minHeight: '100vh',
      fontFamily: "'IBM Plex Sans', 'Helvetica Neue', Arial, sans-serif",
      padding: '0 28px 48px', boxSizing: 'border-box',
    }}>
      <div style={{ maxWidth: 1280, margin: '0 auto' }}>
        <header style={{ marginBottom: 0, padding: '24px 0 18px', borderBottom: `2px solid ${colors.primary}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 24, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
            <img src={logoUrl} alt="Technobrain" style={{ height: 46, width: 'auto', display: 'block', flexShrink: 0 }} />
            <div style={{ width: 1, height: 32, background: colors.line, flexShrink: 0 }} />
            <h1 style={{ fontFamily: "'Fraunces', Georgia, serif", fontWeight: 700, fontSize: 24, margin: 0, lineHeight: 1.2, color: colors.slate, whiteSpace: 'nowrap' }}>
              Attendance Dashboard
            </h1>
          </div>
          <AuthHeader user={user} onLogout={onLogout} />
        </header>

        {leaveActive && calendarOk === false && (
          <div style={{
            border: '1px solid #c58a1b', background: '#fbf3dc', borderRadius: 4,
            padding: '9px 14px', fontSize: 13, marginBottom: 16, color: colors.ink,
          }}>
            Leave overlay failed to load — days are shown unverified. Check the API and refresh.
          </div>
        )}

        <nav style={{ display: 'flex', gap: 4, borderBottom: `1px solid ${colors.line}` }} aria-label="Views">
          {visibleTabs.map(([path, label]) => {
            const active = path === activeTab || (path !== '/' && activeTab.startsWith(path));
            return (
              <Link key={path} to={{ pathname: path, search: serializeFilters(filters, months, today).toString() ? `?${serializeFilters(filters, months, today)}` : '' }}
                onClick={(e) => { e.preventDefault(); switchTab(path); }}
                style={{
                  fontSize: 13.5, padding: '10px 16px', textDecoration: 'none',
                  borderBottom: active ? `2px solid ${colors.select}` : '2px solid transparent',
                  color: active ? colors.select : colors.muted, fontWeight: active ? 600 : 500,
                }}>
                {label}
              </Link>
            );
          })}
        </nav>

        <FilterBar filters={filters} months={months} teams={teamNames} teamHeadcounts={teamHeadcounts}
          daysInView={daysInView} today={today} onChange={update} neverPunchedCount={agg.neverPunchedCount}
          onSyncNow={onSyncNow} syncing={syncing} syncMsg={syncMsg} />

        <Routes>
          <Route path="/" element={<Overview scope={scope} />} />
          <Route path="/teams" element={<Teams scope={scope} />} />
          <Route path="/teams/:teamSlug" element={<TeamDetail scope={scope} />} />
          <Route path="/employees" element={<Employees scope={scope} />} />
          <Route path="/employees/:employeeId" element={<Employees scope={scope} />} />
          <Route path="/exceptions" element={<Exceptions scope={scope} />} />
          <Route path="/data-health" element={<DataHealth scope={scope} />} />
          <Route path="/leave" element={isAdmin
            ? <LeaveImport scope={scope} />
            : <Navigate to={{ pathname: '/', search: location.search }} replace />} />
          <Route path="*" element={<Navigate to={{ pathname: '/', search: location.search }} replace />} />
        </Routes>
      </div>
    </div>
  );
}

function rangeDefaultForMonth(month, today) {
  return month === today.slice(0, 7)
    ? (Number(today.slice(8, 10)) <= 15 ? 'h1' : 'h2')
    : 'whole';
}
