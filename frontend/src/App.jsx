import React, { useState, useEffect } from 'react';
import { Routes, Route, Link, Navigate, useNavigate } from 'react-router-dom';
import Dashboard from './Dashboard.jsx';
import AuthHeader from './components/AuthHeader.jsx';
import LoginPage from './pages/LoginPage.jsx';
import ChangePasswordPage from './pages/ChangePasswordPage.jsx';
import UsersPage from './pages/UsersPage.jsx';
import { fetchDayRecords, fetchCoverage, fetchEmployees, fetchTeams, syncNow } from './api.js';
import { bootSession, getCurrentUser, subscribe, clearSession } from './auth.js';
import logoUrl from './assets/tbl-logo.svg';
import { colors } from './theme.js';

function TopBar({ user, onLogout }) {
  return (
    <div style={{ maxWidth: 1120, margin: '0 auto', padding: '16px 28px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: `2px solid ${colors.primary}` }}>
      <img src={logoUrl} alt="Technobrain" style={{ height: 46 }} />
      <AuthHeader user={user} onLogout={onLogout} />
    </div>
  );
}

export default function App() {
  const [user, setUser] = useState(null);
  const [booting, setBooting] = useState(true);
  const [records, setRecords] = useState(null);
  const [coverage, setCoverage] = useState(null);
  const [roster, setRoster] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState(null);
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
    if (!user || user.must_change_password) return;
    let cancelled = false;
    async function load() {
      try {
        setLoading(true);
        const [recs, cov, emps, teams] = await Promise.all([
          fetchDayRecords(),
          fetchCoverage().catch(() => null),
          fetchEmployees().catch(() => []),
          fetchTeams().catch(() => []),
        ]);
        const teamById = new Map((teams || []).map((t) => [t.id, t.name]));
        if (!cancelled) {
          setRecords(recs);
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
    <Routes>
      <Route path="/login" element={<Navigate to="/" replace />} />
      <Route path="/users" element={
        user.role === 'admin' ? (
          <div style={{ fontFamily: "'IBM Plex Sans', sans-serif", background: colors.paper, minHeight: '100vh' }}>
            <TopBar user={user} onLogout={handleLogout} />
            <UsersPage />
          </div>
        ) : (
          <Navigate to="/" replace />
        )
      } />
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
          <Dashboard records={records || []} coverage={coverage} roster={roster} user={user} onLogout={handleLogout}
            onSyncNow={handleSyncNow} syncing={syncing} syncMsg={syncMsg} />
        )
      } />
    </Routes>
  );
}
