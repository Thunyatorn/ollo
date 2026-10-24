import { useEffect, useState } from 'react';
import { VISION_URL } from '../config';

// The camera's live picture inside the reference build's camera stage: a motion-JPEG stream from the vision service on
// the daycare network, faces blurred and the pose skeleton drawn on. The video never goes through the cloud.
export default function LiveCamera({ cameraId, name }: { cameraId: string; name: string }) {
  const [attempt, setAttempt] = useState(0);
  const [failed, setFailed] = useState(false);

  // if the stream could not start (computer off, wrong network), try again every few seconds
  useEffect(() => {
    if (!failed) return;
    const timer = setTimeout(() => { setFailed(false); setAttempt(n => n + 1); }, 5000);
    return () => clearTimeout(timer);
  }, [failed]);

  if (failed) {
    return <div className="server-frame waiting" role="status">No live picture from {name}. It only works on the daycare network, with the camera computer running. Trying again…</div>;
  }
  return <img key={attempt} className="server-frame" src={`${VISION_URL}/live/${encodeURIComponent(cameraId)}?n=${attempt}`}
              alt={`Live picture from ${name}, faces blurred`} onError={() => setFailed(true)} />;
}
