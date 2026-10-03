import React, { useEffect, useState } from 'react';
import { Clock3, Loader2, Save, UserRound, X } from 'lucide-react';
import { apiService, getApiErrorMessage } from '../../services/api';
import type { EmployeeProfile, EmployeeWorkHours, EmployeeWorkHoursReport } from '../../types/api';

interface EmployeeProfilePanelProps {
  onClose: () => void;
  embedded?: boolean;
}

const currentMonth = () => new Date().toISOString().slice(0, 7);
const formatHours = (seconds: number) => `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;

export const EmployeeProfilePanel: React.FC<EmployeeProfilePanelProps> = ({ onClose, embedded = false }) => {
  const [month, setMonth] = useState(currentMonth);
  const [profile, setProfile] = useState<EmployeeProfile | null>(null);
  const [report, setReport] = useState<EmployeeWorkHours | null>(null);
  const [hrReport, setHrReport] = useState<EmployeeWorkHoursReport | null>(null);
  const [displayName, setDisplayName] = useState('');
  const [jobTitle, setJobTitle] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const isHr = ['ROLE_ADMIN', 'ROLE_MANAGER'].includes(localStorage.getItem('wt_role') || '');

  useEffect(() => {
    if (embedded) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [onClose, embedded]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');
    void Promise.all([
      apiService.getEmployeeProfile(),
      apiService.getEmployeeWorkHours(month),
      isHr ? apiService.getHrWorkHoursReport(month) : Promise.resolve(null),
    ]).then(([nextProfile, nextReport, nextHrReport]) => {
      if (!active) return;
      setProfile(nextProfile);
      setDisplayName(nextProfile.display_name);
      setJobTitle(nextProfile.job_title);
      setReport(nextReport);
      setHrReport(nextHrReport);
    }).catch(loadError => {
      if (active) setError(getApiErrorMessage(loadError, 'Unable to load your profile and time report.'));
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [month, isHr]);

  const runAction = async (action: () => Promise<EmployeeProfile>, successMessage: string) => {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const updatedProfile = await action();
      setProfile(updatedProfile);
      setDisplayName(updatedProfile.display_name);
      setJobTitle(updatedProfile.job_title);
      setNotice(successMessage);
      const [nextReport, nextHrReport] = await Promise.all([
        apiService.getEmployeeWorkHours(month),
        isHr ? apiService.getHrWorkHoursReport(month) : Promise.resolve(null),
      ]);
      setReport(nextReport);
      setHrReport(nextHrReport);
    } catch (actionError) {
      setError(getApiErrorMessage(actionError, 'The update could not be saved.'));
    } finally {
      setBusy(false);
    }
  };

  const isBoss = profile?.email.toLowerCase() === 'camila@wingedtycoons.com';
  const dailyEntries = Object.entries(report?.daily_seconds || {}).sort(([left], [right]) => right.localeCompare(left));

  return (
    <div className={embedded ? '' : 'fixed inset-0 z-[70] flex justify-end bg-slate-950/55'} onMouseDown={event => { if (!embedded && event.target === event.currentTarget) onClose(); }}>
      <section role={embedded ? 'region' : 'dialog'} aria-modal={embedded ? undefined : true} aria-labelledby="employee-profile-title" className={`flex w-full flex-col bg-white text-slate-900 dark:bg-slate-950 dark:text-slate-100 ${embedded ? 'rounded-xl' : 'h-full max-w-xl border-l border-slate-700 shadow-2xl'}`}>
        <header className="flex items-center justify-between border-b border-slate-200 px-5 py-4 dark:border-slate-800">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 text-aero-blue dark:bg-blue-950/60"><UserRound className="h-5 w-5" /></span>
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Employee profile</p>
              <h2 id="employee-profile-title" className="text-base font-bold">{isBoss ? 'Hey Boss!' : 'Your profile & hours'}</h2>
            </div>
          </div>
          {!embedded && <button type="button" onClick={onClose} aria-label="Close profile" title="Close profile" className="flex h-11 w-11 items-center justify-center rounded-xl border border-slate-200 bg-slate-50 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:hover:bg-slate-800"><X className="h-4 w-4" /></button>}
        </header>

        <div className="flex-1 space-y-6 overflow-y-auto p-5">
          {error && <p role="alert" className="rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-800 dark:bg-red-950/40 dark:text-red-200">{error}</p>}
          {notice && <p role="status" aria-live="polite" className="rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200">{notice}</p>}
          {loading && <div role="status" className="flex items-center gap-2 py-4 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" />Loading profile...</div>}

          {!loading && profile && <>
            <form className="space-y-4" onSubmit={event => { event.preventDefault(); void runAction(() => apiService.updateEmployeeProfile(displayName.trim(), jobTitle.trim()), 'Profile saved.'); }}>
              <label className="block text-xs font-semibold text-slate-600 dark:text-slate-300">Display name
                <input required maxLength={120} value={displayName} onChange={event => setDisplayName(event.target.value)} className="mt-1.5 min-h-11 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:ring-2 focus:ring-aero-blue dark:border-slate-700 dark:bg-slate-900 dark:text-white" />
              </label>
              <label className="block text-xs font-semibold text-slate-600 dark:text-slate-300">Job title
                <input required maxLength={120} value={jobTitle} onChange={event => setJobTitle(event.target.value)} className="mt-1.5 min-h-11 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:ring-2 focus:ring-aero-blue dark:border-slate-700 dark:bg-slate-900 dark:text-white" />
              </label>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="text-xs text-slate-500">{profile.email}</div>
                <button type="submit" disabled={busy || !displayName.trim() || !jobTitle.trim()} className="flex min-h-11 items-center gap-2 rounded-lg bg-aero-blue px-4 text-xs font-bold text-white hover:bg-blue-700 disabled:opacity-50"><Save className="h-4 w-4" />Save profile</button>
              </div>
            </form>

            <section className="border-y border-slate-200 py-4 dark:border-slate-800">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 className="text-sm font-bold">Availability</h3>
                  <p className="mt-1 text-xs text-slate-500">Set your status manually. This is separate from recorded work hours.</p>
                </div>
                <button type="button" disabled={busy} onClick={() => void runAction(() => apiService.setEmployeePresence(!profile.is_online), `Status set to ${profile.is_online ? 'offline' : 'online'}.`)} className={`flex min-h-11 items-center gap-2 rounded-lg border px-3 text-xs font-bold ${profile.is_online ? 'border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300' : 'border-slate-300 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300'}`}>
                  <span className={`h-2 w-2 rounded-full ${profile.is_online ? 'bg-emerald-500' : 'bg-slate-400'}`} />{profile.is_online ? 'Online' : 'Offline'}
                </button>
              </div>
            </section>

            <section>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2"><Clock3 className="h-4 w-4 text-aero-blue" /><h3 className="text-sm font-bold">Work hours</h3></div>
                <button type="button" disabled={busy} onClick={() => void runAction(() => apiService.recordEmployeeClockAction(profile.is_clocked_in ? 'clock_out' : 'clock_in'), profile.is_clocked_in ? 'Clocked out.' : 'Clocked in.')} className={`min-h-11 rounded-lg px-4 text-xs font-bold text-white disabled:opacity-50 ${profile.is_clocked_in ? 'bg-red-700 hover:bg-red-800' : 'bg-emerald-700 hover:bg-emerald-800'}`}>
                  {profile.is_clocked_in ? 'Clock out' : 'Clock in'}
                </button>
              </div>
              <div className="mt-4 flex items-end justify-between gap-3 border-b border-slate-200 pb-4 dark:border-slate-800">
                <div><p className="text-3xl font-bold tabular-nums">{formatHours(report?.total_seconds || 0)}</p><p className="mt-1 text-[10px] font-bold uppercase tracking-wider text-slate-500">Recorded this month</p></div>
                <label className="text-[10px] font-bold uppercase text-slate-500">Report month<input type="month" value={month} onChange={event => setMonth(event.target.value)} className="mt-1 block min-h-11 rounded-lg border border-slate-300 bg-white px-2 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-900 dark:text-white" /></label>
              </div>
              <div className="mt-2 divide-y divide-slate-100 dark:divide-slate-900">
                {dailyEntries.length === 0 && <p className="py-4 text-xs text-slate-500">No clocked hours recorded for this month.</p>}
                {dailyEntries.map(([day, seconds]) => <div key={day} className="flex items-center justify-between py-2.5 text-xs"><span>{new Date(`${day}T12:00:00`).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })}</span><span className="font-mono font-semibold tabular-nums">{formatHours(seconds)}</span></div>)}
              </div>
            </section>

            {isHr && <section className="border-t border-slate-200 pt-5 dark:border-slate-800">
              <div className="flex items-center justify-between gap-3"><h3 className="text-sm font-bold">HR work-hours report</h3><span className="text-[10px] uppercase text-slate-500">{hrReport?.month || month}</span></div>
              <div className="mt-3 overflow-x-auto">
                <table className="w-full min-w-[360px] text-left text-xs">
                  <thead className="border-b border-slate-200 text-[10px] uppercase text-slate-500 dark:border-slate-800"><tr><th className="py-2 pr-3">Employee</th><th className="py-2 pr-3">Job title</th><th className="py-2 text-right">Hours</th></tr></thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-slate-900">{hrReport?.employees.map(employee => <tr key={employee.email}><td className="py-2.5 pr-3"><span className="block font-semibold">{employee.display_name}</span><span className="text-[10px] text-slate-500">{employee.email}</span></td><td className="py-2.5 pr-3 text-slate-600 dark:text-slate-300">{employee.job_title}</td><td className="py-2.5 text-right font-mono tabular-nums">{formatHours(employee.total_seconds)}</td></tr>)}</tbody>
                </table>
                {!hrReport?.employees.length && <p className="py-4 text-xs text-slate-500">No employee hours recorded for this month.</p>}
              </div>
            </section>}
          </>}
        </div>
      </section>
    </div>
  );
};
