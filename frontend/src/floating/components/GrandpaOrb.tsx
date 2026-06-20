import type { CSSProperties } from 'react';
import '../styles/grandpa-orb.css';

interface GrandpaOrbProps {
  size?: number;
  className?: string;
  interactive?: boolean;
}

export function GrandpaOrb({
  size = 48,
  className = '',
  interactive = false,
}: GrandpaOrbProps) {
  const style = {
    '--grandpa-orb-size': `${size}px`,
  } as CSSProperties;
  const classes = [
    'grandpa-orb',
    interactive ? 'grandpa-orb--interactive' : '',
    className,
  ].filter(Boolean).join(' ');

  return (
    <span
      className={classes}
      style={style}
      aria-hidden="true"
    >
      <span className="grandpa-orb__core">
        <span className="grandpa-orb__wave grandpa-orb__wave--one" />
        <span className="grandpa-orb__wave grandpa-orb__wave--two" />
        <span className="grandpa-orb__glow" />
        <span className="grandpa-orb__shine" />
      </span>
    </span>
  );
}

export default GrandpaOrb;
