import { Navigate, Route, Routes } from 'react-router-dom';
import { useSpacetimeDB } from 'spacetimedb/react';
import { useMe } from './lib';
import SignIn from './pages/SignIn';
import DashboardLayout from './pages/DashboardLayout';
import RoomView from './pages/RoomView';
import Setup from './pages/Setup';
import Rules from './pages/Rules';
import Reports from './pages/Reports';
import Caregivers from './pages/Caregivers';
import Settings from './pages/Settings';
import PhoneLayout from './pages/PhoneLayout';
import PhoneAlert from './pages/PhoneAlert';
import PhoneRule from './pages/PhoneRule';
import PhoneReports from './pages/PhoneReports';

export default function App() {
  const conn = useSpacetimeDB();
  const { me, ready } = useMe();

  if (!conn.isActive) {
    return (
      <div className="phone" style={{ paddingTop: '18vh' }}>
        <div className="card">
          <h2>{conn.connectionError ? 'Cannot reach Ollo' : 'Connecting…'}</h2>
          <p className="muted">
            {conn.connectionError
              ? 'Check that the Spacetime server is running and this device is on the same network.'
              : 'Waiting for the server.'}
          </p>
        </div>
      </div>
    );
  }
  if (!ready) return null;
  if (!me) return <SignIn />;

  return (
    <Routes>
      <Route element={<DashboardLayout />}>
        <Route index element={<RoomView />} />
        <Route path="settings" element={<Settings />}>
          <Route index element={<Setup />} />
          <Route path="caregivers" element={<Caregivers />} />
        </Route>
        <Route path="setup" element={<Navigate to="/settings" replace />} />
        <Route path="rules" element={<Rules />} />
        <Route path="reports" element={<Reports />} />
        <Route path="reports/:id" element={<Reports />} />
        <Route path="caregivers" element={<Navigate to="/settings/caregivers" replace />} />
      </Route>
      <Route path="m" element={<PhoneLayout />}>
        <Route index element={<Navigate to="alert" replace />} />
        <Route path="alert" element={<PhoneAlert />} />
        <Route path="rules/new" element={<PhoneRule />} />
        <Route path="reports" element={<PhoneReports />} />
        <Route path="reports/:id" element={<PhoneReports />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
