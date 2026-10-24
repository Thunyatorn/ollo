import { useEffect, useRef, useState } from 'react';
import { useTable } from 'spacetimedb/react';
import { tables } from '../module_bindings';
import { eventLabel } from '../lib';

const KEY = 'nestwatch.sound';
const WAITING = ['notified', 'escalated', 'unanswered'];
const read = () => { try { return localStorage.getItem(KEY) === 'on'; } catch { return false; } };
const write = (on: boolean) => { try { localStorage.setItem(KEY, on ? 'on' : 'off'); } catch { /* storage can be blocked */ } };

// A sound (and, when the tab is hidden, a browser notification) for each new alert, and a reminder every 10 s while a HIGH alert
// is still untaken. Browsers only allow sound after a click, so it starts switched off and remembers the choice.
export default function AlertSound() {
  const [on, setOn] = useState(read);
  const [alerts, ready] = useTable(tables.alert);
  const ctx = useRef<AudioContext | null>(null);
  const known = useRef<Set<string> | null>(null);
  const lastBeep = useRef(0);

  function audio(): AudioContext | null {
    if (!ctx.current) {
      const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (AC) ctx.current = new AC();
    }
    void ctx.current?.resume();
    return ctx.current;
  }

  function beeps(freq: number, count: number) {
    const c = audio();
    if (!c) return;
    lastBeep.current = Date.now();
    for (let i = 0; i < count; i++) {
      const t = c.currentTime + i * 0.28;
      const osc = c.createOscillator(), gain = c.createGain();
      osc.type = 'square'; osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.0001, t);
      gain.gain.exponentialRampToValueAtTime(0.25, t + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.2);
      osc.connect(gain).connect(c.destination);
      osc.start(t); osc.stop(t + 0.22);
    }
  }

  // alerts that were already waiting when the page opened do not shout; new ones do
  useEffect(() => {
    if (!ready) return;
    const waiting = alerts.filter(a => WAITING.includes(a.status));
    if (known.current === null) { known.current = new Set(waiting.map(a => a.id)); return; }
    for (const a of waiting) {
      if (known.current.has(a.id)) continue;
      known.current.add(a.id);
      if (!on || a.severity === 'low') continue;
      beeps(a.severity === 'high' ? 880 : 620, a.severity === 'high' ? 3 : 1);
      if ('Notification' in window && Notification.permission === 'granted' && document.hidden) {
        new Notification(`Ollo: ${a.severity} alert`, { body: eventLabel(a.eventType), tag: a.id });
      }
    }
  }, [alerts, ready, on]);

  useEffect(() => {
    if (!on) return;
    const id = setInterval(() => {
      const high = alerts.some(a => a.severity === 'high' && WAITING.includes(a.status));
      if (high && Date.now() - lastBeep.current > 10000) beeps(880, 2);
    }, 2000);
    return () => clearInterval(id);
  }, [on, alerts]);

  // after a page reload the sound is still "on" but the browser wants one click before it will play
  useEffect(() => {
    if (!on) return;
    const unlock = () => void audio();
    window.addEventListener('pointerdown', unlock, { once: true });
    return () => window.removeEventListener('pointerdown', unlock);
  }, [on]);

  function toggle() {
    if (on) { write(false); setOn(false); return; }
    write(true); setOn(true);
    beeps(660, 1);                                                   // proof that it works
    if ('Notification' in window && Notification.permission === 'default') void Notification.requestPermission();
  }

  return <button className="linkbtn" aria-pressed={on} onClick={toggle} title="Play a sound when a new alert arrives">Alert sound: {on ? 'on' : 'off'}</button>;
}
