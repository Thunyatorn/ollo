import { Fragment } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { clearToken, useMe, useUnhandledCount } from '../lib';

const links = [
  { to: '/', label: 'Room', end: true },
  { to: '/rules', label: 'Rules' },
  { to: '/reports', label: 'Reports' },
  { to: '/caregivers', label: 'Caregivers' },
  { to: '/setup', label: 'Setup' },
  { to: '/m/alert', label: 'Phone view' },
];

export default function DashboardLayout() {
  const { me } = useMe();
  const unhandled = useUnhandledCount();
  return (
    <div className="doc">
      <header className="masthead">
        <h1>NestWatch</h1>
        <p className="byline">Room monitoring for small daycares</p>
        <p className="byline2">Signed in as {me?.name} ({me?.role})</p>
      </header>
      <nav className="topnav" aria-label="Main">
        {links.map((l, i) => (
          <Fragment key={l.to}>
            {i > 0 && <span aria-hidden="true"> | </span>}
            <NavLink to={l.to} end={l.end} className={({ isActive }) => (isActive ? 'active' : '')}>
              {l.label}
              {l.to === '/' && unhandled > 0 && <strong className="unhandled" aria-label={`${unhandled} alerts need attention`}> ({unhandled})</strong>}
            </NavLink>
          </Fragment>
        ))}
        <span aria-hidden="true"> | </span>
        <button className="linkbtn" onClick={() => { clearToken(); window.location.reload(); }}>Sign out</button>
      </nav>
      <main className="main"><Outlet /></main>
      <footer className="foot">NestWatch. Video stays in the daycare; only positions and events are shared.</footer>
    </div>
  );
}
