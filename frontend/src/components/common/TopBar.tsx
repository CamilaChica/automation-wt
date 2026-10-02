import React, { useState, useEffect } from 'react';
import { ViewMode, ThemeMode } from '../../types';
import { Search, Sun, Moon, ShieldCheck, UserCheck, AlertTriangle, Bell, Menu } from 'lucide-react';
import { BrandMark } from './BrandMark';
import { FloatingQa } from './FloatingQa';
import { useMailboxHealth, useRFQs, useSystemHealth } from '../../hooks/useApiResources';
import { apiService } from '../../services/api';

interface TopBarProps {
  currentView: ViewMode;
  theme: ThemeMode;
  onToggleTheme: () => void;
  onSelectView: (view: ViewMode) => void;
  onSearch?: (query: string) => void;
  onOpenAuditLog?: () => void;
  onOpenSidebar?: () => void;
  onOpenProfile?: () => void;
}

export const TopBar: React.FC<TopBarProps> = ({
  currentView,
  theme,
  onToggleTheme,
  onSelectView,
  onSearch,
  onOpenAuditLog,
  onOpenSidebar,
  onOpenProfile,
}) => {
  const [timeString, setTimeString] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState('');
  const [employeeName, setEmployeeName] = useState('');
  const [employeeTitle, setEmployeeTitle] = useState('');
  const [isOnline, setIsOnline] = useState(false);
  const systemHealth = useSystemHealth();
  const rfqQuery = useRFQs();
  const activeAogCount = (rfqQuery.data || []).filter(rfq => rfq.urgency?.toUpperCase() === 'AOG' && !['INTAKE_FAILED', 'REJECTED'].includes(rfq.status.toUpperCase())).length;
  const role = localStorage.getItem('wt_role');
  const isBoss = localStorage.getItem('wt_email')?.toLowerCase() === 'camila@wingedtycoons.com';
  const mailboxHealthEnabled = ['ROLE_ADMIN', 'ROLE_MANAGER', 'ROLE_SALES', 'ROLE_PURCHASING', 'ROLE_INTERNAL'].includes(role || '');
  const mailboxHealth = useMailboxHealth(mailboxHealthEnabled);
  const mailboxStates = Object.values(mailboxHealth.data || {});
  const mailboxStatus = mailboxHealth.error
    ? 'unavailable'
    : mailboxHealth.isLoading
      ? 'checking'
      : mailboxStates.length === 0
        ? 'unknown'
        : mailboxStates.every(mailbox => mailbox.status === 'ok') ? 'healthy' : 'attention required';

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setTimeString(now.toLocaleTimeString('en-US', { hour12: true, timeZoneName: 'short' }));
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    let active = true;
    const refreshProfile = () => {
      void apiService.getEmployeeProfile().then(profile => {
        if (!active) return;
        setEmployeeName(profile.display_name);
        setEmployeeTitle(profile.job_title);
        setIsOnline(profile.is_online);
      }).catch(() => undefined);
    };
    refreshProfile();
    window.addEventListener('wt-employee-profile-changed', refreshProfile);
    return () => {
      active = false;
      window.removeEventListener('wt-employee-profile-changed', refreshProfile);
    };
  }, []);

  return (
    <>
    <header className="min-h-14 border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-card-dark px-2 md:px-4 py-2 flex items-center justify-between gap-2 text-xs font-sans select-none transition-colors">
      {/* Brand & Page Title */}
      <div className="flex-none items-center space-x-2 md:space-x-3">
        <button type="button" aria-label="Open navigation menu" onClick={onOpenSidebar} className="min-h-11 min-w-11 rounded-xl border border-slate-200 bg-slate-100 p-2 dark:border-slate-700 dark:bg-slate-800 lg:hidden">
          <Menu className="mx-auto h-5 w-5" aria-hidden="true" />
        </button>
        <a
          href="/"
          aria-label="Winged Tycoons Executive Dashboard"
          className="flex shrink-0 items-center space-x-2 bg-slate-100 dark:bg-slate-900 px-2.5 py-1 rounded-lg border border-slate-200 dark:border-slate-700/80 hover:border-aero-blue transition-colors"
        >
          <BrandMark compact />
          <span className="hidden font-display font-bold text-sm tracking-wider text-slate-900 dark:text-slate-100 sm:inline">
            WINGED TYCOONS
          </span>
        </a>
        <div className="h-4 w-px shrink-0 bg-slate-300 dark:bg-slate-700" />
      </div>

      {/* Center Search & AOG Badge */}
      <div className="hidden xl:flex shrink-0 items-center space-x-4">
        {/* AOG Priority Badge */}
        <div className={`flex shrink-0 items-center space-x-2 whitespace-nowrap border px-3 py-1 rounded-full font-mono text-[11px] font-semibold ${activeAogCount > 0 ? 'bg-red-50 dark:bg-aog-red/10 border-red-200 dark:border-aog-red/40 text-aog-red aog-pulse-badge' : 'border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300'}`}>
          <AlertTriangle className="w-3.5 h-3.5 animate-bounce" />
          <span className="whitespace-nowrap">{rfqQuery.isLoading ? 'AOG ALERTS: …' : rfqQuery.error ? 'AOG ALERTS: UNAVAILABLE' : `AOG ALERTS: ${activeAogCount} ACTIVE`}</span>
        </div>

        {/* Global Omnibar */}
        <div className="relative w-52 2xl:w-72">
          <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-slate-400" />
          <input
            type="text"
            aria-label="Global Search"
            name="search"
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              onSearch?.(e.target.value);
            }}
            placeholder="Search P/N, NSN, S/N, CAGE... [Cmd + K]"
            className="w-full bg-slate-100 dark:bg-slate-900/80 border border-slate-200 dark:border-slate-700 rounded-xl pl-9 pr-3 py-1.5 text-slate-900 dark:text-slate-200 placeholder-slate-400 focus:ring-2 focus:ring-aero-blue focus:outline-none transition-colors font-mono text-[11px]"
          />
        </div>
      </div>

      {/* Right Controls: Telemetry, Theme, Notifications & User */}
      <div className="ml-auto flex shrink-0 items-center space-x-1.5 md:space-x-4">
        {/* Sub-header status tags */}
        <div className="hidden xl:flex items-center space-x-2 text-[10px] font-mono text-slate-600 dark:text-slate-400">
          <span className="flex items-center gap-1" title={systemHealth.error?.message || `Readiness status: ${systemHealth.data?.status || 'checking'}`} aria-label={`API readiness ${systemHealth.error ? 'unavailable' : systemHealth.data?.status || 'checking'}`}>
            <span aria-hidden="true" className={`h-2 w-2 rounded-full ${systemHealth.error ? 'bg-red-500' : systemHealth.data?.status === 'ready' ? 'bg-emerald-500' : 'bg-amber-500'}`} />
            <span>API {systemHealth.isLoading ? '…' : systemHealth.error ? 'DEGRADED' : systemHealth.data?.status === 'ready' ? 'READY' : 'UNKNOWN'}</span>
            {systemHealth.error && <button type="button" aria-label="Retry API readiness" onClick={() => void systemHealth.refetch()} className="ml-1 underline">Retry</button>}
          </span>
          {mailboxHealthEnabled && <span className="flex items-center gap-1" title={mailboxHealth.error?.message || `Mailbox health: ${mailboxStatus}`} aria-label={`Mailbox health ${mailboxStatus}`}>
            <span aria-hidden="true" className={`h-2 w-2 rounded-full ${mailboxStatus === 'healthy' ? 'bg-emerald-500' : mailboxStatus === 'checking' ? 'bg-amber-500' : 'bg-red-500'}`} />
            <span>MAIL {mailboxStatus === 'healthy' ? 'OK' : mailboxStatus === 'checking' ? '…' : mailboxStatus === 'attention required' ? 'ATTENTION' : 'N/A'}</span>
            {mailboxHealth.error && <button type="button" aria-label="Retry mailbox health" onClick={() => void mailboxHealth.refetch()} className="ml-1 underline">Retry</button>}
          </span>}
        </div>
        <div className="hidden min-[1700px]:flex items-center space-x-3 text-[11px] font-mono text-slate-600 dark:text-slate-400">
          <span className="flex items-center space-x-1 text-emerald-600 dark:text-emerald-400 font-semibold">
            <ShieldCheck className="w-3.5 h-3.5" />
            <span>SPEED. TRACEABILITY. RELIABILITY.</span>
          </span>
          <span className="text-slate-300 dark:text-slate-600">|</span>
          <span className="font-semibold text-slate-800 dark:text-slate-200">{timeString}</span>
        </div>

        {/* Shared notifications/activity drawer trigger */}
        <button
          onClick={onOpenAuditLog}
          aria-label="Open notifications and agent activity"
          title="Notifications and agent activity"
          className="flex min-h-11 min-w-11 shrink-0 items-center justify-center space-x-1.5 rounded-xl border border-blue-200 bg-blue-50 p-2 font-mono text-[10px] font-bold text-aero-blue shadow-sm transition-all hover:bg-aero-blue hover:text-white dark:border-aero-blue/40 dark:bg-aero-blue/10 md:px-3 md:py-1.5"
        >
          <Bell className="w-3.5 h-3.5" aria-hidden="true" />
          <span className="hidden md:inline">ACTIVITY LOG</span>
        </button>

        {/* Theme Toggle Switch */}
        <button
          onClick={onToggleTheme}
          aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
          title={`Switch to ${theme === 'dark' ? 'Light' : 'Dark'} Mode`}
          className="flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-xl border border-slate-200 bg-slate-100 p-2 text-slate-700 transition-all hover:border-aero-blue hover:text-slate-900 dark:border-slate-700 dark:bg-slate-800/80 dark:text-slate-300 dark:hover:text-white"
        >
          {theme === 'dark' ? (
            <Sun className="w-4 h-4 text-amber-400" />
          ) : (
            <Moon className="w-4 h-4 text-indigo-600" />
          )}
        </button>

        {/* Operator Profile Context */}
        <button type="button" onClick={onOpenProfile} aria-label="Open employee profile and work hours" title="Profile and work hours" className="hidden sm:flex items-center space-x-2 bg-slate-100 dark:bg-slate-800/90 border border-slate-200 dark:border-slate-700 px-2.5 py-1 rounded-xl text-left hover:border-aero-blue focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue">
          <div className="w-6 h-6 rounded-full bg-blue-100 dark:bg-slate-700 flex items-center justify-center text-aero-blue font-bold font-mono">
            <UserCheck className="w-3.5 h-3.5" />
          </div>
          <div className="flex flex-col text-[11px] leading-tight">
            <span className="font-semibold text-slate-900 dark:text-slate-100">{isBoss ? 'BOSS' : (employeeName || localStorage.getItem('wt_email')?.split('@')[0] || 'EMPLOYEE').toUpperCase()}{employeeTitle ? ` (${employeeTitle.toUpperCase()})` : ''}</span>
            <span className={`flex items-center space-x-1 text-[9px] font-mono font-bold ${isOnline ? 'text-emerald-600 dark:text-emerald-400' : 'text-slate-500 dark:text-slate-400'}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${isOnline ? 'bg-emerald-500 animate-pulse' : 'bg-slate-400'}`}></span>
              <span>{isOnline ? 'ONLINE' : 'OFFLINE'}</span>
            </span>
          </div>
        </button>
      </div>
    </header>
    <FloatingQa audience="internal" />
    </>
  );
};
