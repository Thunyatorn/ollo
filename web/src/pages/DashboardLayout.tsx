import { NavLink, Outlet } from 'react-router-dom';
import { Eye, FileText, LogOut, Settings2, Shield, Smartphone, Video } from 'lucide-react';
import AlertBar from '../components/AlertBar';
import AlertSound from '../components/AlertSound';
import { clearToken, useMe, useUnhandledCount } from '../lib';

// The reference build's top bar (brand, page buttons, connection state), around our pages.
const links = [
  { to: '/', label: 'Monitor', icon: Video, end: true },
  { to: '/rules', label: 'Rules', icon: Shield },
  { to: '/reports', label: 'Reports', icon: FileText },
  { to: '/settings', label: 'Settings', icon: Settings2 },
  { to: '/m/alert', label: 'Phone view', icon: Smartphone },
];

export default function DashboardLayout() {
  const { me } = useMe();
  const unhandled = useUnhandledCount();
  return (
    <div className="app-shell">
      <main className="main">
        <header className="topbar">
          <NavLink className="brand compact-brand" to="/" aria-label="Ollo monitor">
            <Eye size={23} strokeWidth={1.6} />
            Ollo
          </NavLink>
          <nav className="topbar-nav" aria-label="Main">
            {links.map(l => (
              <NavLink key={l.to} to={l.to} end={l.end} className={({ isActive }) => `button ${isActive ? 'active' : ''}`}>
                <l.icon size={14} />
                {l.label}
                {l.to === '/' && unhandled > 0 && <span className="unhandled" aria-label={`${unhandled} alerts need attention`}>{unhandled}</span>}
              </NavLink>
            ))}
          </nav>
          <div className="topbar-right">
            <AlertSound />
            <span className="connection"><span className="status-dot" />System connected</span>
            <span className="who">{me?.name} ({me?.role})</span>
            <button className="linkbtn" onClick={() => { clearToken(); window.location.reload(); }}><LogOut size={13} />Sign out</button>
          </div>
        </header>
        <AlertBar />
        <Outlet />
      </main>
    </div>
  );
}
