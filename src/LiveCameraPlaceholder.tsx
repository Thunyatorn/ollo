import { Cctv, WifiOff } from "lucide-react";

export default function LiveCameraPlaceholder() {
  return <div className="live-camera-placeholder">
    <div className="live-camera-empty"><Cctv size={36} strokeWidth={1.2} /><strong>Live camera</strong><span><WifiOff size={13} />Not connected</span></div>
  </div>;
}
