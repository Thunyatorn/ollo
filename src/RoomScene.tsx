export default function RoomScene({ variant = 0 }: { variant?: number }) {
  return (
    <svg
      className="room-scene"
      viewBox="0 0 1200 760"
      preserveAspectRatio="xMidYMid slice"
      role="img"
      aria-label="Illustrated daycare room, demonstration scene only"
    >
      <defs>
        <linearGradient id="wall" x2="0" y2="1">
          <stop stopColor="#b8b7ad" />
          <stop offset="1" stopColor="#858b84" />
        </linearGradient>
        <linearGradient id="floor" x2=".3" y2="1">
          <stop stopColor="#aaa18c" />
          <stop offset="1" stopColor="#776f60" />
        </linearGradient>
        <linearGradient id="light">
          <stop stopColor="#d7dfce" stopOpacity=".5" />
          <stop offset="1" stopColor="#d7dfce" stopOpacity="0" />
        </linearGradient>
        <filter id="shadow">
          <feDropShadow dx="0" dy="12" stdDeviation="13" floodOpacity=".2" />
        </filter>
        <pattern
          id="boards"
          width="130"
          height="65"
          patternUnits="userSpaceOnUse"
          patternTransform="skewX(-30)"
        >
          <path
            d="M0 0H130V65H0Z"
            fill="none"
            stroke="#4b463c"
            strokeOpacity=".13"
          />
        </pattern>
        <pattern id="grain" width="4" height="4" patternUnits="userSpaceOnUse">
          <circle cx="1" cy="2" r=".5" fill="#fff" opacity=".09" />
        </pattern>
      </defs>
      <rect width="1200" height="760" fill="url(#wall)" />
      <path d="M0 0H290V425L0 670Z" fill="#8c938a" />
      <path d="M290 425H1200V760H0V670Z" fill="url(#floor)" />
      <path d="M290 425H1200V760H0V670Z" fill="url(#boards)" />
      <path d="M290 0V425H1200" fill="none" stroke="#d8d3c4" strokeWidth="9" />
      <path d="M290 425L0 670" stroke="#666c61" strokeWidth="10" />
      <g transform="translate(440 60)">
        <rect width="245" height="245" rx="3" fill="#d4d1bd" />
        <rect x="11" y="11" width="223" height="224" fill="#728a83" />
        <path d="M11 160Q70 110 120 153T234 155V235H11Z" fill="#8b9b89" />
        <path d="M120 11V235M11 118H234" stroke="#d4d1bd" strokeWidth="10" />
        <path d="M-10 245H255" stroke="#e0dcc9" strokeWidth="15" />
      </g>
      <path d="M452 310L714 310 1140 760H600Z" fill="url(#light)" />
      <g transform="translate(990 113)">
        <rect width="158" height="316" fill="#535c51" />
        <rect x="11" y="12" width="136" height="302" fill="#303b33" />
        <path d="M11 12L95 37V314H11Z" fill="#87917f" />
        <circle cx="78" cy="167" r="4" fill="#c5c5b2" />
      </g>
      <g filter="url(#shadow)" transform="translate(720 325)">
        <path d="M0 0H228V116H0Z" fill="#b9aa88" />
        <path d="M8 9H220V103H8Z" fill="#716e58" />
        <path
          d="M79 4V110M153 4V110M4 56H224"
          stroke="#b9aa88"
          strokeWidth="10"
        />
        <rect x="16" y="20" width="50" height="29" rx="4" fill="#87927d" />
        <rect x="92" y="66" width="48" height="30" rx="4" fill="#9a826c" />
        <rect x="165" y="13" width="41" height="38" rx="4" fill="#9b9d85" />
        <path
          d="M15 65V96M23 65V96M31 62V96M38 69V96"
          stroke="#b1a18a"
          strokeWidth="6"
        />
      </g>
      <g transform="translate(330 375)" filter="url(#shadow)">
        <path d="M0 0H170L202 66H30Z" fill="#c6bda4" />
        <path d="M30 66H202V87H30Z" fill="#9d947c" />
        <path
          d="M39 85V140M187 85V140M8 22V91M160 22V91"
          stroke="#8c856e"
          strokeWidth="12"
        />
        <ellipse cx="91" cy="33" rx="22" ry="11" fill="#7d8c7c" />
        <rect x="130" y="15" width="15" height="23" rx="2" fill="#c0a174" />
      </g>
      <g transform="translate(65 355)">
        <path d="M0 0L146 -86V99L0 192Z" fill="#ad9f82" />
        <path d="M0 16L130 -63V87L0 167Z" fill="#626c5e" />
        <path
          d="M8 61L130 -12M8 110L130 37M65 -22V132"
          stroke="#ad9f82"
          strokeWidth="8"
        />
        <path d="M16 112L54 89V125L16 148Z" fill="#9b8b73" />
        <path d="M76 31L117 8V39L76 65Z" fill="#a0a283" />
      </g>
      <path
        d="M285 506L691 486 924 696 459 740Z"
        fill={variant === 1 ? "#737d70" : "#777d72"}
        opacity=".94"
      />
      <path
        d="M315 529L682 512 873 684 470 715Z"
        fill="none"
        stroke="#a8ac94"
        strokeWidth="3"
        opacity=".45"
      />
      <g opacity=".5" stroke="#aeb29c" strokeWidth="2">
        <path d="M430 524L629 707M559 519L757 695M390 607L776 590" />
      </g>
      <g filter="url(#shadow)">
        <path d="M569 583l26-16 29 15-25 19Z" fill="#b4a17c" />
        <path d="M569 583V608L599 625V601Z" fill="#857859" />
        <path d="M599 601L624 582V608L599 625Z" fill="#9d8c69" />
        <path d="M652 629l17-11 20 12-18 13Z" fill="#9b735f" />
        <path d="M652 629V648L671 659V643Z" fill="#765347" />
        <path d="M671 643L689 630V648L671 659Z" fill="#8f6553" />
        <circle cx="728" cy="584" r="20" fill="#a7ad8e" />
      </g>
      <g transform="translate(840 170)">
        <rect x="-46" y="-35" width="88" height="101" rx="2" fill="#c3bca6" />
        <path d="M-29 45L-8-4 8 21 20-9 30 45Z" fill="#7a8a73" />
        <circle cx="-20" cy="-13" r="9" fill="#b9a376" />
      </g>
      <rect width="1200" height="760" fill="url(#grain)" />
      <rect width="1200" height="760" fill="#152019" opacity=".12" />
    </svg>
  );
}
