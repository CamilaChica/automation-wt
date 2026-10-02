import React from 'react';
import { apiService } from '../../services/api';
import { BarList, PageHeader, Panel, money, useLoad } from './analyticsUi';

export const SalesRaceView: React.FC = () => {
  const { data, error, load } = useLoad(() => apiService.getSalesLeaderboard());
  const board = data?.board || [];
  const medal = (i: number) => (['🥇', '🥈', '🥉'][i] ?? `${i + 1}.`);
  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 md:p-8">
      <PageHeader title="Sales race" subtitle={`Everyone's income and hours this month${data ? ` · ${data.month}` : ''}`} onRefresh={load} />
      {error && <p role="alert" className="text-sm text-red-500">{error}</p>}
      <div className="grid gap-4 md:grid-cols-2">
        <Panel title="Income">
          <BarList color="bg-amber-400" rows={[...board].sort((a, b) => b.revenue - a.revenue).map((r, i) => ({ label: `${medal(i)} ${r.name}`, value: r.revenue, display: `${money(r.revenue)} · ${r.orders} orders` }))} empty="No sales yet this month." />
        </Panel>
        <Panel title="Work hours">
          <BarList color="bg-cyan-500" rows={[...board].sort((a, b) => b.hours - a.hours).map((r, i) => ({ label: `${medal(i)} ${r.name}${r.is_online ? ' ●' : ''}`, value: r.hours, display: `${r.hours}h` }))} empty="No hours logged this month." />
        </Panel>
      </div>
    </div>
  );
};
