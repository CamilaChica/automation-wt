import React from 'react';

export const money = (value: number) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value || 0);

export const Card: React.FC<{ label: string; value: React.ReactNode; hint?: string }> = ({ label, value, hint }) => (
  <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-card-dark">
    <div className="text-sm text-slate-500 dark:text-slate-400">{label}</div>
    <div className="mt-2 text-2xl font-bold text-slate-900 dark:text-white">{value}</div>
    {hint && <div className="mt-1 text-xs text-slate-400">{hint}</div>}
  </div>
);

export const Panel: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-card-dark">
    <h2 className="mb-3 text-sm font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">{title}</h2>
    {children}
  </section>
);

export const BarList: React.FC<{ rows: { label: string; value: number; display?: string }[]; empty: string; color?: string }> = ({ rows, empty, color = 'bg-aero-blue' }) => {
  if (!rows.length) return <p className="text-sm text-slate-500 dark:text-slate-400">{empty}</p>;
  const max = Math.max(...rows.map(r => r.value), 1);
  return (
    <ul className="space-y-2">
      {rows.map(row => (
        <li key={row.label}>
          <div className="flex justify-between gap-2 text-sm text-slate-700 dark:text-slate-200">
            <span className="truncate">{row.label}</span>
            <span className="font-semibold">{row.display ?? row.value}</span>
          </div>
          <div className="mt-1 h-2.5 rounded-full bg-slate-100 dark:bg-slate-800">
            <div className={`h-2.5 rounded-full ${color}`} style={{ width: `${Math.max((row.value / max) * 100, row.value > 0 ? 3 : 0)}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
};

export const ColumnChart: React.FC<{ rows: { label: string; value: number }[]; empty: string }> = ({ rows, empty }) => {
  if (!rows.length) return <p className="text-sm text-slate-500 dark:text-slate-400">{empty}</p>;
  const max = Math.max(...rows.map(r => r.value), 1);
  return (
    <div className="flex h-40 items-end gap-1 overflow-x-auto">
      {rows.map(row => (
        <div key={row.label} className="flex min-w-[18px] flex-1 flex-col items-center justify-end" title={`${row.label}: ${row.value}`}>
          <div className="w-full rounded-t bg-cyan-500" style={{ height: `${(row.value / max) * 100}%`, minHeight: row.value > 0 ? 4 : 0 }} />
          <span className="mt-1 text-[10px] text-slate-400">{row.label.slice(5)}</span>
        </div>
      ))}
    </div>
  );
};

export const PageHeader: React.FC<{ title: string; subtitle: string; onRefresh?: () => void }> = ({ title, subtitle, onRefresh }) => (
  <header className="flex flex-wrap items-end justify-between gap-3">
    <div>
      <h1 className="text-2xl font-bold text-slate-900 dark:text-white">{title}</h1>
      <p className="text-sm text-slate-500 dark:text-slate-400">{subtitle}</p>
    </div>
    {onRefresh && (
      <button type="button" onClick={onRefresh} className="min-h-11 rounded-xl border border-slate-300 px-4 text-sm font-semibold text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800">
        Refresh
      </button>
    )}
  </header>
);

export function useLoad<T>(loader: () => Promise<T>) {
  const [data, setData] = React.useState<T | null>(null);
  const [error, setError] = React.useState('');
  const load = React.useCallback(() => {
    setError('');
    loader().then(setData).catch(() => setError('Could not load data. Try Refresh.'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  React.useEffect(() => { load(); }, [load]);
  return { data, error, load };
}
