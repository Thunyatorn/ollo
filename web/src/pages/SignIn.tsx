import { useState } from 'react';
import { Eye } from 'lucide-react';
import { useTable, useReducer } from 'spacetimedb/react';
import { reducers, tables } from '../module_bindings';

export default function SignIn() {
  const [caregivers] = useTable(tables.caregiver);
  const claim = useReducer(reducers.claimCaregiver);
  const [id, setId] = useState('');
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      await claim({ caregiverId: id, joinCode: code });
    } catch {
      setError('That name and code do not match. Ask your director for your code.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="phone" style={{ paddingTop: '14vh' }}>
      <form className="card stack" onSubmit={submit}>
        <h1 className="phone-title"><Eye size={22} strokeWidth={1.6} />Ollo</h1>
        <p className="muted">Sign in to see alerts and the room.</p>
        <div>
          <label htmlFor="who">Who are you?</label>
          <select id="who" value={id} onChange={e => setId(e.target.value)} required>
            <option value="" disabled>Choose your name</option>
            {caregivers.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="code">Your code</label>
          <input id="code" value={code} onChange={e => setCode(e.target.value)} autoComplete="one-time-code" required />
        </div>
        {error && <div className="banner" role="alert">{error}</div>}
        <button className="btn" disabled={busy || !id || !code}>{busy ? 'Signing in…' : 'Sign in'}</button>
        {caregivers.length === 0 && <p className="small muted">No caregivers exist yet. An admin has to add them first.</p>}
      </form>
    </div>
  );
}
