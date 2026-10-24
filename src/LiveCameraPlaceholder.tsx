import { Cctv, WifiOff } from "lucide-react";

export function LiveBadge() {
  return <span className="live-feed-badge">LIVE</span>;
}

export default function LiveCameraPlaceholder() {
  return <div className="live-camera-placeholder">
    <div className="live-camera-clock"><LiveBadge /><time>--:--:--</time></div>
    <div className="live-camera-empty"><Cctv size={36} strokeWidth={1.2} /><strong>Live camera</strong><span><WifiOff size={13} />Not connected</span></div>
  </div>;
}
