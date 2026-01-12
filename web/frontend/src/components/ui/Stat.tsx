interface StatProps {
  label: string;
  value: string | number;
  positive?: boolean;
  negative?: boolean;
  mono?: boolean;
  size?: 'sm' | 'md' | 'lg';
}

export function Stat({
  label,
  value,
  positive,
  negative,
  mono = false,
  size = 'md',
}: StatProps) {
  const valueColor = positive
    ? 'text-profit'
    : negative
    ? 'text-loss'
    : 'text-text-primary';

  const sizes = {
    sm: 'text-lg',
    md: 'text-xl',
    lg: 'text-2xl',
  };

  return (
    <div>
      <div className="text-text-secondary text-sm">{label}</div>
      <div
        className={`
          font-semibold ${sizes[size]} ${valueColor}
          ${mono ? 'font-mono' : ''}
        `}
      >
        {value}
      </div>
    </div>
  );
}
