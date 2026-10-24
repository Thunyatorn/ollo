import { useEffect, useState } from 'react';
import { VISION_URL } from '../config';

// The camera's live picture, from the vision service on the daycare network: faces blurred, pose skeleton drawn on.
// It is a motion-JPEG stream in an <img>; the video never goes through the cloud.
export default function LiveCamera({ cameraId, name }: { cameraId: string; name: string }) {
  const [attempt, setAttempt] = useState(0);
  const [failed, setFailed] = useState(false);

  // if the stream could not start (computer off, wrong network), try again every few seconds
  useEffect(() => {
    if (!failed) return;
    const timer = setTimeout(() => { setFailed(false); setAttempt(n => n + 1); }, 5000);
    return () => clearTimeout(timer);
  }, [failed]);

  return (
    <figure style={{ margin: 0 }}>
      {failed ? (
        <div className="live-off" role="status">
          No live picture from {name}. It only works on the daycare network, and the camera computer must be running.
          <div className="small muted">Trying again…</div>
        </div>
      ) : (
        <img key={attempt} className="live" src={`${VISION_URL}/live/${encodeURIComponent(cameraId)}?n=${attempt}`}
             alt={`Live picture from ${name}, faces blurred`} onError={() => setFailed(true)} />
      )}
      <figcaption className="small muted">
        Figure 1. Live picture from {name}. Faces are blurred and the pose skeleton is drawn on. It stays on the daycare network.
      </figcaption>
    </figure>
  );
}
