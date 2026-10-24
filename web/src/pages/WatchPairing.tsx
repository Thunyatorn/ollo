import { useState } from 'react';
import { Watch } from 'lucide-react';
import { WORKER_URL } from '../config';
import { loadToken, useMe } from '../lib';
import { useServices } from '../services';

// Settings › Garmin watch: pair the signed-in caregiver's watch with the ollo Connect IQ app (garmin/ in the repository).
export default function WatchPairing() {
  const { me } = useMe();
  const { worker } = useServices();
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function pair() {
    setBusy(true); setError(''); setCode('');
    try {
      const res = await fetch(`${WORKER_URL}/watch/pair`, { method: 'POST', headers: { authorization: `Bearer ${loadToken() ?? ''}` } });
      if (!res.ok) throw new Error(String(res.status));
      setCode((await res.json()).code);
    } catch {
      setError('The worker is not reachable, so no code was made. Start it and try again.');
    } finally { setBusy(false); }
  }

  const server = worker?.public_url;
  return (
    <div className="stack">
      <div className="card stack">
        <h2><Watch size={14} style={{ display: 'inline', marginRight: 6 }} />Use a Garmin watch as {me?.name ?? 'your'}'s buzzer</h2>
        <p>The ollo watch app vibrates when an alert needs you, shows what and where, and has <strong>I'm on it</strong> and <strong>I can't respond</strong> on its buttons. Keep the app open during a shift: closed, Garmin only lets it check every 5 minutes.</p>
        <div className="row">
          <button className="btn" onClick={pair} disabled={busy}>{busy ? 'Making a code…' : code ? 'Make a new code' : 'Pair my watch'}</button>
          <span className="small muted">A new code replaces the old one, so a lost watch stops working.</span>
        </div>
        {error && <div className="banner" role="alert">{error}</div>}
        {code && (
          <table><tbody>
            <tr><th scope="row">Pairing code</th><td className="mono" style={{ fontSize: 22, letterSpacing: 2, color: 'var(--bright)' }}>{code}</td></tr>
            <tr><th scope="row">Server address</th><td className="mono">{server ?? 'not set: put the worker’s https address in PUBLIC_BASE_URL (worker/.env) and restart it'}</td></tr>
          </tbody></table>
        )}
      </div>
      <div className="card">
        <h2>Steps</h2>
        <ol className="report-lines" style={{ paddingLeft: 18, margin: 0 }}>
          <li>Install the ollo app on the watch (see <span className="mono">garmin/README.md</span>).</li>
          <li>On the phone, open Garmin Connect › your watch › Connect IQ apps › ollo › Settings.</li>
          <li>Type the server address and the pairing code above, and save.</li>
          <li>Open ollo on the watch. It shows "Paired as {me?.name ?? 'you'}" and starts checking every 3 seconds.</li>
        </ol>
      </div>
    </div>
  );
}
