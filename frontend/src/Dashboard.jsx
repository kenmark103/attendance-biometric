// Dashboard shell: header, nav tabs (links), sticky filter bar, routes.
// URL query string is the single source of truth for filters.
import React, { useMemo, useState, useEffect } from 'react';
import { Routes, Route, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { colors } from './theme.js';
import { DashboardNav } from './components/DashboardChrome.jsx';
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
import useDashboardMetrics from './hooks/useDashboardMetrics.js';

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

export default function Dashboard({ records, calMeta, calendarOk, coverage, roster, user, onSyncNow, syncing, syncMsg }) {
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
      next.range = 'whole';
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
  const metrics = useDashboardMetrics({
    day: filters.day,
    dates,
    teams: filters.teams,
    shift: filters.shift,
    excludeNeverPunched: filters.nopunch,
  });

  const agg = useMemo(() => adaptMetrics(metrics) || EMPTY_AGG, [metrics]);

  const backendDays = useMemo(() => {
    const out = new Map();
    for (const employee of agg.employees || []) {
      for (const day of employee.days || []) {
        out.set(`${employee.id}|${day.date}`, day);
      }
    }
    return out;
  }, [agg.employees]);

  const ctx = useMemo(() => ({
    today,
    leaveLoaded: leaveLoaded || leaveActive,
    leaveActive,
    coverageThrough: coverage?.leave_coverage?.through_date || null,
    coveredDates: new Set((coverage?.per_date ?? []).filter((d) => d.count > 0).map((d) => d.date)),
    trustZoho: coverage?.trust_zoho_presence !== false,
    calMeta: calMeta || {},
    backendDays,
    excludeNeverPunched: filters.nopunch,
  }), [today, leaveLoaded, leaveActive, coverage, calMeta, backendDays, filters.nopunch]);

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
  const isAdmin = user?.role === 'Admin';
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
      padding: '0 0 48px', boxSizing: 'border-box',
    }}>
      <div className="app-page-container">
        <h1 className="dashboard-page-title">Attendance Dashboard</h1>

        {leaveActive && calendarOk === false && (
          <div style={{
            border: '1px solid #c58a1b', background: '#fbf3dc', borderRadius: 4,
            padding: '9px 14px', fontSize: 13, marginBottom: 16, color: colors.ink,
          }}>
            Leave overlay failed to load — days are shown unverified. Check the API and refresh.
          </div>
        )}

        <DashboardNav tabs={visibleTabs} activeTab={activeTab} filters={filters}
          months={months} today={today} onSwitchTab={switchTab} />

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
