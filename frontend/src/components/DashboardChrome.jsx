import { Link } from 'react-router-dom';
import { serializeFilters } from '../filters.js';


export function DashboardNav({ tabs, activeTab, filters, months, today, onSwitchTab }) {
  const search = serializeFilters(filters, months, today).toString();
  return (
    <nav className="dashboard-subnav" aria-label="Dashboard views">
      {tabs.map(([path, label]) => {
        const active = path === activeTab || (path !== '/' && activeTab.startsWith(path));
        return (
          <Link key={path} to={{ pathname: path, search: search ? `?${search}` : '' }}
            onClick={(e) => { e.preventDefault(); onSwitchTab(path); }}
            className={`dashboard-subnav__link ${active ? 'dashboard-subnav__link--active' : ''}`}>
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
