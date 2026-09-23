import React, { useState, useEffect } from 'react';
import AttendanceDashboard from './AttendanceDashboard.jsx';
import { fetchDayRecords } from './api.js';

export default function App() {
  const [records, setRecords] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        setLoading(true);
        const recs = await fetchDayRecords();
        if (!cancelled) {
          setRecords(recs);
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
    return <div style={{ fontFamily: 'sans-serif', padding: 40, color: '#6E786F' }}>No attendance data returned from API. Have you run the loader yet? <code>docker compose --profile tools run --rm loader</code></div>;
  }
  return <AttendanceDashboard records={records} />;
}
