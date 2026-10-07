import React, { useState, useEffect } from 'react';
import { Routes, Route, Link } from 'react-router-dom';
import AttendanceDashboard from './AttendanceDashboard.jsx';
import AuthHeader from './components/AuthHeader.jsx';
import LoginPage from './pages/LoginPage.jsx';
import { fetchDayRecords, fetchCoverage } from './api.js';
import logoUrl from './assets/tbl-logo.svg';
import { colors } from './theme.js';

export default function App() {
  const [records, setRecords] = useState(null);
  const [coverage, setCoverage] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        setLoading(true);
        const [recs, cov] = await Promise.all([fetchDayRecords(), fetchCoverage().catch(() => null)]);
        if (!cancelled) {
          setRecords(recs);
          setCoverage(cov);
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
  }, []);

  if (loading) {
    return <div style={{ fontFamily: 'sans-serif', padding: 40, color: '#6E786F' }}>Loading attendance data from API...</div>;
  }
  if (error) {
    return (
      <div style={{ fontFamily: 'sans-serif', padding: 40, color: '#A63D2F' }}>
        Could not load from API: {error}.<br />
        <span style={{ color: '#6E786F', fontSize: 13 }}>
          Is the API running at {import.meta.env.VITE_API_URL || '/api'}? Check <code>docker ps</code> and{' '}
          <code>curl http://localhost:8001/health</code>.
        </span>
      </div>
    );
  }
  if (!records || records.length === 0) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={
          <div style={{ fontFamily: "'IBM Plex Sans', sans-serif", background: colors.paper, minHeight: '100vh' }}>
            <div style={{ maxWidth: 1120, margin: '0 auto', padding: '16px 28px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: `2px solid ${colors.primary}` }}>
              <img src={logoUrl} alt="Technobrain" style={{ height: 46 }} />
              <AuthHeader />
            </div>
            <div style={{ padding: 40, color: '#6E786F' }}>No attendance data returned from API. Have you run the loader yet? <code>docker compose --profile tools run --rm loader</code> <Link to="/login" style={{ color: colors.slate }}>Go to login</Link></div>
          </div>
        } />
      </Routes>
    );
  }
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="*" element={<AttendanceDashboard records={records} coverage={coverage} />} />
    </Routes>
  );
}
