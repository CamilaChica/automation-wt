import React from 'react';
import { apiService } from '../../services/api';
import { BarList, Card, ColumnChart, PageHeader, Panel, money, useLoad } from './analyticsUi';

export const OwnerAnalyticsView: React.FC = () => {
  const { data, error, load } = useLoad(() => apiService.getOwnerAnalytics());
  const k = data?.kpis;
  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 md:p-8">
      <PageHeader title="Business overview" subtitle={`Company performance${data ? ` · ${data.month}` : ''}`} onRefresh={load} />
      {error && <p role="alert" className="text-sm text-red-500">{error}</p>}
      <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Card label="Revenue (POs)" value={k ? money(k.revenue) : '…'} hint={k ? `${k.purchase_orders} purchase orders` : undefined} />
        <Card label="Quoted value" value={k ? money(k.quoted_value) : '…'} hint={k ? `${k.quotes_sent} quotes sent` : undefined} />
        <Card label="RFQs (30 days)" value={k ? k.rfqs_last_30_days : '…'} hint={k ? `${k.total_rfqs} all time` : undefined} />
        <Card label="Win rate" value={k ? `${Math.round(k.win_rate * 100)}%` : '…'} hint={k ? `Quote rate ${Math.round(k.quote_rate * 100)}%` : undefined} />
      </section>
      <div className="grid gap-4 md:grid-cols-2">
        <Panel title="RFQs per day">
          <ColumnChart rows={(data?.daily_rfqs || []).map(d => ({ label: d.day, value: d.count }))} empty="No RFQs in the last 30 days." />
        </Panel>
        <Panel title="Pipeline by status">
          <BarList rows={(data?.rfq_status || []).map(s => ({ label: s.status.replace(/_/g, ' '), value: s.count }))} empty="No RFQs yet." />
        </Panel>
        <Panel title="Sales team this month">
          <BarList color="bg-amber-400" rows={(data?.team || []).map(t => ({ label: `${t.name}${t.is_online ? ' ●' : ''}`, value: t.revenue, display: `${money(t.revenue)} · ${t.hours}h` }))} empty="No sales activity yet." />
        </Panel>
        <Panel title="Top customers">
          <BarList rows={(data?.top_customers || []).map(c => ({ label: c.customer, value: c.rfqs }))} empty="No customers yet." />
        </Panel>
        <Panel title="Most requested parts">
          <BarList color="bg-cyan-500" rows={(data?.top_parts || []).map(p => ({ label: p.part_number, value: p.rfqs }))} empty="No parts requested yet." />
        </Panel>
      </div>
    </div>
  );
};
