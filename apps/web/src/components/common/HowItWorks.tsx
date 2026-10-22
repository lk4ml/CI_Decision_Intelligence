export default function HowItWorks({ title, cols }: { title: string; cols: [string, string][] }) {
  return (
    <details className="how">
      <summary>{title}</summary>
      <div className="b">
        {cols.map(([h, t]) => (
          <div key={h}>
            <b>{h}</b>
            {t}
          </div>
        ))}
      </div>
    </details>
  );
}
