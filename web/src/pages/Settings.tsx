import { NavLink, Outlet } from 'react-router-dom';

// The reference build's "Workspace settings" page with tabs: the room and its camera, and the caregivers.
export default function Settings() {
  return (
    <section className="secondary-page settings-page">
      <span className="eyebrow">MAKE NESTWATCH YOURS</span>
      <h1>Workspace settings</h1>
      <p className="page-lead">The room, its camera and restricted areas, and the people who respond.</p>
      <nav className="page-tabs" aria-label="Settings sections">
        <NavLink to="/settings" end className={({ isActive }) => (isActive ? 'active' : '')}>Room and camera</NavLink>
        <NavLink to="/settings/caregivers" className={({ isActive }) => (isActive ? 'active' : '')}>Caregivers</NavLink>
        <NavLink to="/settings/watch" className={({ isActive }) => (isActive ? 'active' : '')}>Garmin watch</NavLink>
      </nav>
      <Outlet />
    </section>
  );
}
