import React, { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import logoUrl from '../assets/tbl-logo.svg';
import { logout } from '../auth.js';

const primaryItems = [
  { to: '/', label: 'Dashboard', exact: true },
  { to: '/wfh', label: 'Work from home' },
  { to: '/users', label: 'Users' },
];

function isActive(pathname, item) {
  return item.exact ? pathname === '/' : pathname === item.to || pathname.startsWith(`${item.to}/`);
}

function initials(user) {
  const source = (user?.display_name || '').trim();
  if (source) {
    const parts = source.split(/\s+/).filter(Boolean);
    return `${parts[0][0]}${parts[1]?.[0] || ''}`.toUpperCase();
  }
  return (user?.email || '?')[0].toUpperCase();
}

function MenuLink({ to, children, onNavigate }) {
  return <Link role="menuitem" className="app-menu__item" to={to} onClick={onNavigate}>{children}</Link>;
}

export default function AppHeader({ user, onLogout }) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const [systemOpen, setSystemOpen] = useState(false);
  const [userOpen, setUserOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const rootRef = useRef(null);
  const systemTriggerRef = useRef(null);
  const userTriggerRef = useRef(null);
  const admin = user?.role === 'Admin';
  const displayName = user?.display_name || user?.email || '';
  const systemActive = pathname === '/audit-log' || pathname === '/auth-events';

  const closeMenus = () => { setSystemOpen(false); setUserOpen(false); setMobileOpen(false); };

  useEffect(() => {
    closeMenus();
  }, [pathname]);

  useEffect(() => {
    function onPointerDown(event) {
      if (rootRef.current && !rootRef.current.contains(event.target)) closeMenus();
    }
    function onKeyDown(event) {
      if (event.key !== 'Escape') return;
      if (systemOpen) systemTriggerRef.current?.focus();
      else if (userOpen) userTriggerRef.current?.focus();
      closeMenus();
    }
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => { document.removeEventListener('mousedown', onPointerDown); document.removeEventListener('keydown', onKeyDown); };
  }, [systemOpen, userOpen]);

  function moveMenuFocus(event) {
    if (!['ArrowDown', 'ArrowUp'].includes(event.key)) return;
    const panel = event.currentTarget.getAttribute('role') === 'menu'
      ? event.currentTarget
      : event.currentTarget.nextElementSibling;
    const items = [...panel?.querySelectorAll('[role="menuitem"]') || []];
    if (!items.length) return;
    event.preventDefault();
    const activeIndex = items.indexOf(document.activeElement);
    const next = event.key === 'ArrowDown'
      ? (activeIndex + 1 + items.length) % items.length
      : (activeIndex - 1 + items.length) % items.length;
    items[next].focus();
  }

  async function signOut() {
    closeMenus();
    await logout();
    onLogout?.();
    navigate('/login', { replace: true });
  }

  const navItems = primaryItems.filter((item) => item.exact || admin);
  return (
    <header className="app-header" ref={rootRef}>
      <div className="app-header__inner">
        <Link to="/" className="app-brand" aria-label="Attendance Dashboard home">
          <img src={logoUrl} alt="Technobrain" className="app-brand__logo" />
        </Link>

        <button className="app-header__toggle" type="button" aria-label="Toggle navigation" aria-expanded={mobileOpen}
          onClick={() => setMobileOpen((open) => !open)}>☰</button>

        <nav className={`app-primary-nav ${mobileOpen ? 'app-primary-nav--open' : ''}`} aria-label="Primary">
          {navItems.map((item) => <Link key={item.to} to={item.to} className="app-nav-link"
            aria-current={isActive(pathname, item) ? 'page' : undefined}>{item.label}</Link>)}
          {admin && <div className="app-menu">
            <button ref={systemTriggerRef} type="button" className="app-nav-link app-menu__trigger"
              aria-current={systemActive ? 'page' : undefined} aria-haspopup="menu" aria-expanded={systemOpen}
              onClick={() => { setSystemOpen((open) => !open); setUserOpen(false); }} onKeyDown={moveMenuFocus}>
              System <span className="app-chevron" aria-hidden="true">▾</span>
            </button>
            {systemOpen && <div className="app-menu__panel" role="menu" onKeyDown={moveMenuFocus}>
              <MenuLink to="/audit-log" onNavigate={closeMenus}>Audit log</MenuLink>
              <MenuLink to="/auth-events" onNavigate={closeMenus}>Auth events</MenuLink>
            </div>}
          </div>}
        </nav>

        <div className="app-menu app-user-menu">
          <button ref={userTriggerRef} type="button" className="app-user-menu__trigger" aria-haspopup="menu" aria-expanded={userOpen}
            onClick={() => { setUserOpen((open) => !open); setSystemOpen(false); }} onKeyDown={moveMenuFocus}>
            <span className="app-avatar" aria-hidden="true">{initials(user)}</span>
            <span className="app-user-menu__name">{displayName}</span>
            <span className={`app-role-pill app-role-pill--${admin ? 'admin' : 'viewer'}`}>{user?.role}</span>
            <span className="app-chevron" aria-hidden="true">▾</span>
          </button>
          {userOpen && <div className="app-menu__panel app-menu__panel--right" role="menu" onKeyDown={moveMenuFocus}>
            <div className="app-user-menu__identity">
              <strong>{displayName}</strong>
              <span>{user?.email}</span>
              <span className={`app-role-pill app-role-pill--${admin ? 'admin' : 'viewer'}`}>{user?.role}</span>
            </div>
            <div className="app-menu__divider" />
            <button type="button" role="menuitem" className="app-menu__item" onClick={signOut}>Sign out</button>
          </div>}
        </div>
      </div>
    </header>
  );
}
