import React from 'react';
import { apiService } from '../../services/api';
import { Card, ColumnChart, PageHeader, Panel, money, useLoad } from './analyticsUi';

export const MySalesView: React.FC = () => {
  const { data, error, load } = useLoad(() => apiService.getMySales());
  const daily = Object.entries(data?.daily_seconds || {})
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([day, secs]) => ({ label: day, value: Math.round((secs / 3600) * 10) / 10 }));
  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 md:p-8">
      <PageHeader title="My sales" subtitle={`Your own revenue, orders and hours${data ? ` · ${data.month}` : ''}`} onRefresh={load} />
      {error && <p role="alert" className="text-sm text-red-500">{error}</p>}
      <section className="grid grid-cols-3 gap-3">
        <Card label="My revenue" value={data ? money(data.revenue) : '…'} />
        <Card label="My orders" value={data ? data.orders : '…'} />
        <Card label="My hours" value={data ? `${data.hours}h` : '…'} />
      </section>
      <Panel title="My hours per day">
        <ColumnChart rows={daily} empty="No hours logged this month yet." />
      </Panel>
      <Panel title="RFQs I handled">
        {!data?.handled_rfqs.length ? (
          <p className="text-sm text-slate-500 dark:text-slate-400">No RFQs assigned to you yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-slate-500"><tr><th className="py-2">RFQ</th><th>Part</th><th>Customer</th><th>Status</th></tr></thead>
              <tbody className="text-slate-800 dark:text-slate-200">
                {data.handled_rfqs.map(r => (
                  <tr key={r.rfq_id} className="border-t border-slate-200 dark:border-slate-800">
                    <td className="py-2 font-mono">{r.rfq_id}</td>
                    <td>{r.part_number || '—'}</td>
                    <td className="truncate">{r.customer_email || '—'}</td>
                    <td>{r.status.replace(/_/g, ' ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
};
