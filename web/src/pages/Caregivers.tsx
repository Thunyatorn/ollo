import { useState } from 'react';
import { useReducer, useTable } from 'spacetimedb/react';
import { reducers, tables } from '../module_bindings';

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');

export default function Caregivers() {
  const [caregivers] = useTable(tables.caregiver);
  const upsert = useReducer(reducers.upsertCaregiver);
  const [editing, setEditing] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [role, setRole] = useState('staff');
  const [phone, setPhone] = useState('');
  const [joinCode, setJoinCode] = useState('');
  const [buzzer, setBuzzer] = useState('');
  const [onDuty, setOnDuty] = useState(true);
  const [error, setError] = useState('');

  function edit(id: string) {
    const c = caregivers.find(x => x.id === id);
    if (!c) return;
    setEditing(id); setName(c.name); setRole(c.role); setPhone(''); setJoinCode(''); setBuzzer(c.buzzerId ?? ''); setOnDuty(c.onDuty);
  }
  function reset() { setEditing(null); setName(''); setRole('staff'); setPhone(''); setJoinCode(''); setBuzzer(''); setOnDuty(true); }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    try {
      await upsert({ id: editing ?? `c_${slug(name)}`, name, role, phone, joinCode, buzzerId: buzzer || undefined, onDuty });
      reset();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save.');
    }
  }

  return (
    <div className="stack">
      <div className="room-layout">
        <div className="card">
          <table>
            <thead><tr><th>Name</th><th>Role</th><th>Buzzer</th><th>On duty</th><th /></tr></thead>
            <tbody>
              {caregivers.map(c => (
                <tr key={c.id}>
                  <td>{c.name}</td>
                  <td><span className={`pill ${c.role === 'primary' ? 'ok' : 'off'}`}>{c.role}</span></td>
                  <td className="small">{c.buzzerId ?? <span className="muted">not paired</span>}</td>
                  <td>{c.onDuty ? 'Yes' : 'No'}</td>
                  <td style={{ textAlign: 'right' }}><button className="btn secondary" onClick={() => edit(c.id)}>Edit</button></td>
                </tr>
              ))}
            </tbody>
          </table>
          {caregivers.length === 0 && <p className="muted">No caregivers yet.</p>}
        </div>

        <form className="card stack" onSubmit={save}>
          <h2>{editing ? 'Edit caregiver:' : 'Add a caregiver:'}</h2>
          <div><label htmlFor="cn">Name</label><input id="cn" value={name} onChange={e => setName(e.target.value)} required /></div>
          <div>
            <label htmlFor="cr">Role</label>
            <select id="cr" value={role} onChange={e => setRole(e.target.value)}>
              <option value="primary">Primary (first to be alerted)</option>
              <option value="backup">Backup (gets the phone call)</option>
              <option value="staff">Staff</option>
            </select>
          </div>
          <div><label htmlFor="cp">Phone number{editing && ' (blank keeps the saved one)'}</label><input id="cp" type="tel" value={phone} onChange={e => setPhone(e.target.value)} placeholder="+15551234567" required={!editing} /></div>
          <div><label htmlFor="cj">Sign-in code{editing && ' (blank keeps the saved one)'}</label><input id="cj" value={joinCode} onChange={e => setJoinCode(e.target.value)} required={!editing} /></div>
          <div><label htmlFor="cb">Wrist buzzer ID</label><input id="cb" value={buzzer} onChange={e => setBuzzer(e.target.value)} placeholder="buzzer-maria" /></div>
          <label className="row" style={{ fontWeight: 400 }}><input type="checkbox" checked={onDuty} onChange={e => setOnDuty(e.target.checked)} style={{ width: 'auto', minHeight: 0 }} /> On duty today</label>
          {error && <div className="banner" role="alert">{error}</div>}
          <div className="row"><button className="btn">Save</button>{editing && <button type="button" className="btn secondary" onClick={reset}>Cancel</button>}</div>
        </form>
      </div>
    </div>
  );
}
