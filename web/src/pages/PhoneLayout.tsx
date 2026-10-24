import { Eye } from 'lucide-react';
import { Fragment } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { useUnhandledCount } from '../lib';

export default function PhoneLayout() {
  const unhandled = useUnhandledCount();
  const cls = ({ isActive }: { isActive: boolean }) => (isActive ? 'active' : '');
  const items = [
    { to: '/m/alert', label: 'Alert' },
    { to: '/m/rules/new', label: 'Rule' },
    { to: '/m/reports', label: 'Reports' },
    { to: '/', label: 'Desk' },
  ];
  return (
    <div className="phone">
      <h1 className="phone-title"><Eye size={22} strokeWidth={1.6} />Ollo</h1>
      <nav className="phone-nav" aria-label="Phone">
        {items.map((it, i) => (
          <Fragment key={it.to}>
            {i > 0 && <span aria-hidden="true">|</span>}
            <NavLink to={it.to} className={cls}>
              {it.label}
              {it.to === '/m/alert' && unhandled > 0 && <strong className="unhandled" aria-label={`${unhandled} need attention`}> ({unhandled})</strong>}
            </NavLink>
          </Fragment>
        ))}
      </nav>
      <Outlet />
    </div>
  );
}
