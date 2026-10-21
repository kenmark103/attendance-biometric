import { Link } from 'react-router-dom';
import logoUrl from '../assets/tbl-logo.svg';
import { colors } from '../theme.js';
import AuthHeader from './AuthHeader.jsx';
import { serializeFilters } from '../filters.js';


export function DashboardHeader({ user, onLogout }) {
  return (
    <header style={{ marginBottom: 0, padding: '24px 0 18px', borderBottom: `2px solid ${colors.primary}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 24, flexWrap: 'wrap' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
        <img alt="Technobrain" src={logoUrl} style={{ height: 46, width: 'auto', display: 'block', flexShrink: 0 }} />
        <div style={{ width: 1, height: 32, background: colors.line, flexShrink: 0 }} />
        <h1 style={{ fontFamily: "'Fraunces', Georgia, serif", fontWeight: 700, fontSize: 24, margin: 0, lineHeight: 1.2, color: colors.slate, whiteSpace: 'nowrap' }}>
          Attendance Dashboard
        </h1>
      </div>
      <AuthHeader user={user} onLogout={onLogout} />
    </header>
  );
}


export function DashboardNav({ tabs, activeTab, filters, months, today, onSwitchTab }) {
  const search = serializeFilters(filters, months, today).toString();
  return (
    <nav style={{ display: 'flex', gap: 4, borderBottom: `1px solid ${colors.line}` }} aria-label="Views">
      {tabs.map(([path, label]) => {
        const active = path === activeTab || (path !== '/' && activeTab.startsWith(path));
        return (
          <Link key={path} to={{ pathname: path, search: search ? `?${search}` : '' }}
            onClick={(e) => { e.preventDefault(); onSwitchTab(path); }}
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
  );
}
