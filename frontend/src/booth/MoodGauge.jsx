// Analog needle gauge for the room's rolling sentiment (0 = flagging, 1 = hyped).
export default function MoodGauge({ mood }) {
  const score = mood?.rollingScore ?? 0.5;
  const angle = -90 + score * 180;
  const word = score >= 0.62 ? 'Hyped' : score <= 0.4 ? 'Flagging' : 'Cruising';
  return (
    <figure className="gauge" title={`${mood?.sampleSize ?? 0} messages in the last ${mood?.windowSeconds ?? 30}s`}>
      <svg viewBox="0 0 120 70" aria-hidden="true">
        <path d="M10 60 A50 50 0 0 1 43 13" stroke="#2f6f73" strokeWidth="8" fill="none" />
        <path d="M45 12 A50 50 0 0 1 75 12" stroke="#e8a93b" strokeWidth="8" fill="none" />
        <path d="M77 13 A50 50 0 0 1 110 60" stroke="#e2553f" strokeWidth="8" fill="none" />
        <line x1="60" y1="60" x2="60" y2="18" stroke="#1b1a17" strokeWidth="3" strokeLinecap="round"
          style={{ transform: `rotate(${angle}deg)`, transformOrigin: '60px 60px', transition: 'transform .8s cubic-bezier(.3,1.6,.5,1)' }} />
        <circle cx="60" cy="60" r="5" fill="#1b1a17" />
      </svg>
      <figcaption><b>{word}</b> <span>{Math.round(score * 100)}</span></figcaption>
    </figure>
  );
}
