import React, { lazy, Suspense, useState, useEffect } from 'react';
import { Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import AppHeader from './components/AppHeader.jsx';
import LoginPage from './pages/LoginPage.jsx';
import ChangePasswordPage from './pages/ChangePasswordPage.jsx';
import UsersPage from './pages/UsersPage.jsx';
import WfhPage from './pages/WfhPage.jsx';
import AdminAuditPage from './pages/AdminAuditPage.jsx';
import { fetchDayRecords, fetchCoverage, fetchEmployees, fetchTeams, syncNow } from './api.js';
import { bootSession, getCurrentUser, subscribe, clearSession } from './auth.js';
import { colors } from './theme.js';

const Dashboard = lazy(() => import('./Dashboard.jsx'));

export default function App() {
  const [user, setUser] = useState(null);
  const [booting, setBooting] = useState(true);
  const [records, setRecords] = useState(null);
  const [calMeta, setCalMeta] = useState({});
  const [calendarOk, setCalendarOk] = useState(true);
  const [coverage, setCoverage] = useState(null);
  const [roster, setRoster] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState(null);
  const [idleWarning, setIdleWarning] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    let cancelled = false;
    bootSession().then((u) => {
      if (!cancelled) {
        setUser(u);
        setBooting(false);
      }
    });
    const unsub = subscribe((u) => {
      if (!cancelled) {
        setUser(u);
        if (!u) navigate('/login', { replace: true });
      }
    });
    const onLogoutEvent = () => {
      if (!cancelled) {
        setUser(null);
        navigate('/login', { replace: true });
      }
    };
    window.addEventListener('auth:logout', onLogoutEvent);
    return () => { cancelled = true; unsub(); window.removeEventListener('auth:logout', onLogoutEvent); };
  }, []);

  useEffect(() => {
    if (!user) return undefined;
    let lastActivity = Date.now(); let warningTimer; let logoutTimer;
    const idleMinutes = 60; const warningSeconds = 60;
    const reset = () => {
      lastActivity = Date.now(); setIdleWarning(false); clearTimeout(warningTimer); clearTimeout(logoutTimer);
      if (!idleMinutes) return;
      warningTimer = setTimeout(() => setIdleWarning(true), Math.max(0, idleMinutes * 60000 - warningSeconds * 1000));
      logoutTimer = setTimeout(() => { handleLogout(); window.dispatchEvent(new CustomEvent('auth:logout', { detail: 'idle' })); }, idleMinutes * 60000);
    };
    const events = ['pointerdown', 'keydown', 'scroll', 'touchstart']; events.forEach((e) => window.addEventListener(e, reset, { passive: true })); reset();
    return () => { events.forEach((e) => window.removeEventListener(e, reset)); clearTimeout(warningTimer); clearTimeout(logoutTimer); };
  }, [user]);

  useEffect(() => {
    if (!user || user.must_change_password) return;
    let cancelled = false;
    async function load() {
      try {
        setLoading(true);
        const [dayData, cov, emps, teams] = await Promise.all([
          fetchDayRecords(),
          fetchCoverage().catch(() => null),
          fetchEmployees().catch(() => []),
          fetchTeams().catch(() => []),
        ]);
        const teamById = new Map((teams || []).map((t) => [t.id, t.name]));
        if (!cancelled) {
          setRecords(dayData.records);
          setCalMeta(dayData.calMeta || {});
          setCalendarOk(dayData.calendarOk !== false);
          setCoverage(cov);
          setRoster((emps || []).map((e) => ({
            id: e.id, name: e.name, team: teamById.get(e.current_team_id) || 'Unassigned',
          })));
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(e.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [user, refreshKey]);

  async function handleSyncNow() {
    setSyncing(true);
    setSyncMsg(null);
    try {
      const res = await syncNow();
      setRefreshKey((k) => k + 1);
      const p = res.poll || {};
      setSyncMsg(`Synced: poll ${p.status || '?'} (${p.written ?? 0} staging rows), ${res.promoted ?? 0} dashboard rows updated.`);
    } catch (e) {
      setSyncMsg(`Sync failed: ${e.message}`);
    } finally {
      setSyncing(false);
    }
  }

  function handleLogout() {
    clearSession();
    setUser(null);
    setRecords(null);
    setCoverage(null);
    setRoster([]);
  }

  if (booting) {
    return <div style={{ fontFamily: 'sans-serif', padding: 40, color: '#6E786F' }}>Signing in...</div>;
  }

  if (!user) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage onLogin={setUser} />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  if (user.must_change_password) {
    return (
      <ChangePasswordPage
        onChanged={(u) => setUser(u)}
        onLogout={handleLogout}
      />
    );
  }

  return (
    <>
    <AppHeader user={user} onLogout={handleLogout} />
    {idleWarning && <div role="alertdialog" aria-live="assertive" style={{ position: 'fixed', zIndex: 20, right: 24, bottom: 24, maxWidth: 360, padding: 18, borderRadius: 8, background: colors.panel, border: `1px solid ${colors.warn}`, boxShadow: '0 5px 20px rgba(0,0,0,.2)' }}>
      You will be signed out soon because of inactivity. Move or interact with the page to stay signed in.
    </div>}
    <Routes>
      <Route path="/login" element={<Navigate to="/" replace />} />
      <Route path="/users" element={
        user.role === 'Admin' ? (
          <div style={{ fontFamily: "'IBM Plex Sans', sans-serif", background: colors.paper, minHeight: '100vh' }}><UsersPage /></div>
        ) : (
          <Navigate to="/" replace />
        )
      } />
      {['/wfh', '/audit-log', '/auth-events'].map((path) => <Route key={path} path={path} element={user.role === 'Admin' ? <div style={{ fontFamily: "'IBM Plex Sans', sans-serif", background: colors.paper, minHeight: '100vh' }}>{path === '/wfh' ? <WfhPage /> : <AdminAuditPage kind={path === '/auth-events' ? 'events' : 'audit'} />}</div> : <Navigate to="/" replace />} />)}
      <Route path="*" element={
        loading ? (
          <div style={{ fontFamily: 'sans-serif', padding: 40, color: '#6E786F' }}>Loading attendance data from API...</div>
        ) : error ? (
          <div style={{ fontFamily: 'sans-serif', padding: 40, color: '#A63D2F' }}>
            Could not load from API: {error}.<br />
            <span style={{ color: '#6E786F', fontSize: 13 }}>
              Is the API running? Check <code>docker ps</code> and{' '}
              <code>curl http://localhost:8001/health</code>.
            </span>
          </div>
        ) : (
          <Suspense fallback={<div style={{ fontFamily: 'sans-serif', padding: 40, color: '#6E786F' }}>Loading dashboard...</div>}>
            <Dashboard records={records || []} calMeta={calMeta} calendarOk={calendarOk} coverage={coverage} roster={roster} user={user} onLogout={handleLogout}
              onSyncNow={handleSyncNow} syncing={syncing} syncMsg={syncMsg} />
          </Suspense>
        )
      } />
    </Routes>
    </>
  );
}
