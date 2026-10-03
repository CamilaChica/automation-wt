import React from 'react';
import { EmployeeProfilePanel } from '../common/EmployeeProfilePanel';
import { MySalesView } from './MySalesView';
import { SalesRaceView } from './SalesRaceView';

export type MyWorkSection = 'sales' | 'profile' | 'leaderboard';

export const MyWorkWorkspace: React.FC<{
  section: MyWorkSection;
  onSelectSection: (section: MyWorkSection) => void;
}> = ({ section, onSelectSection }) => (
  <div>
    <header className="mx-auto max-w-6xl space-y-3 px-4 pt-6 md:px-8">
      <h1 className="text-xl font-bold">My Work</h1>
      <p className="text-sm text-slate-500 dark:text-slate-400">Your sales, work hours and profile, with the team leaderboard in one place.</p>
      <nav aria-label="My work sections" className="flex flex-wrap gap-2">
        {([
          { label: 'My Sales', id: 'sales' },
          { label: 'Hours & Profile', id: 'profile' },
          { label: 'Team Leaderboard', id: 'leaderboard' },
        ] as const).map(item => (
          <button key={item.id} type="button" aria-pressed={section === item.id} onClick={() => onSelectSection(item.id)}
            className={`min-h-11 rounded-lg px-4 text-sm font-semibold focus-visible:ring-2 focus-visible:ring-aero-blue ${section === item.id ? 'bg-aero-blue text-white' : 'bg-slate-200 text-slate-800 hover:bg-slate-300 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700'}`}>
            {item.label}
          </button>
        ))}
      </nav>
    </header>
    {section === 'sales' && <MySalesView />}
    {section === 'leaderboard' && <SalesRaceView />}
    {section === 'profile' && <div className="mx-auto max-w-6xl p-4 md:p-8"><EmployeeProfilePanel embedded onClose={() => onSelectSection('sales')} /></div>}
  </div>
);
