import React from 'react';
import { ViewMode } from '../../types';
import { apiService } from '../../services/api';
import { 
  LayoutDashboard, 
  FileText, 
  Search, 
  ShieldCheck, 
  Package, 
  TrendingUp, 
  LogOut,
  BarChart3,
  Wallet,
} from 'lucide-react';

interface SidebarProps {
  currentView: ViewMode;
  onSelectView: (view: ViewMode) => void;
  isMobileOpen?: boolean;
  onCloseMobile?: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ currentView, onSelectView, isMobileOpen = false, onCloseMobile }) => {
  const isOwner = apiService.hasAnyRole(['ROLE_ADMIN']);
  const navItems = [
    ...(isOwner ? [{ id: 'owner-analytics' as ViewMode, label: 'Business Overview', icon: BarChart3, badge: null }] : []),
    { id: 'customer' as ViewMode, label: 'Today', icon: LayoutDashboard, badge: null },
    { id: 'my-sales' as ViewMode, label: 'My Work', icon: Wallet, badge: null },
    { id: 'sales' as ViewMode, label: 'RFQs & Quotes', icon: TrendingUp, badge: null },
    { id: 'sourcing' as ViewMode, label: 'Supplier Offers', icon: Search, badge: null },
    { id: 'aero-procurement' as ViewMode, label: 'Inventory & Email', icon: FileText, badge: null },
    { id: 'fulfillment' as ViewMode, label: 'Shipments', icon: Package, badge: null },
    { id: 'trace-vault' as ViewMode, label: 'Reviews & AI Health', icon: ShieldCheck, badge: null },
  ];
  return (
    <>
      {isMobileOpen && <button type="button" aria-label="Close navigation menu" className="fixed inset-0 z-40 bg-black/40 lg:hidden" onClick={onCloseMobile} />}
      <aside className={`${isMobileOpen ? 'translate-x-0' : '-translate-x-full'} fixed inset-y-0 left-0 z-50 w-64 bg-white dark:bg-card-dark border-r border-slate-200 dark:border-slate-800 flex flex-col justify-between select-none transition-transform lg:static lg:z-auto lg:w-56 lg:translate-x-0`}>
      <div className="py-4 px-3">
          <div className="hidden px-2 mb-3 text-[10px] font-mono font-bold tracking-widest text-slate-400 dark:text-slate-500 uppercase md:block">
          Operations
        </div>

        <nav className="space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = currentView === item.id
              || (item.id === 'my-sales' && currentView === 'sales-race')
              || (item.id === 'fulfillment' && currentView === 'shipments-map');

            return (
              <button
                key={item.id}
                onClick={() => { onSelectView(item.id); onCloseMobile?.(); }}
                aria-label={item.label}
                aria-current={isActive ? 'page' : undefined}
                className={`w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-xs font-semibold transition-all group ${
                  isActive
                    ? 'bg-aero-blue text-white shadow-md shadow-aero-blue/20 font-bold'
                    : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800/60 hover:text-slate-900 dark:hover:text-slate-200'
                }`}
              >
                <div className="flex items-center space-x-3">
                  <Icon className={`w-4 h-4 transition-transform group-hover:scale-110 ${
                    isActive ? 'text-white' : 'text-slate-500 dark:text-slate-400'
                  }`} />
                  <span className="truncate">{item.label}</span>
                </div>

                {item.badge && (
                  <span className={`hidden px-2 py-0.5 text-[10px] font-mono font-bold rounded-full md:inline ${
                    isActive
                      ? 'bg-white/20 text-white'
                      : 'bg-blue-50 text-aero-blue dark:bg-aero-blue/20 dark:text-aero-blue'
                  }`}>
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        <div className="mt-6 space-y-1 border-t border-slate-200 pt-4 dark:border-slate-800">
          <button
            onClick={() => {
              void apiService.signOut().finally(() => { window.location.href = window.location.hostname.startsWith('team.') ? '/' : '/team-portal'; });
            }}
            className="w-full flex items-center space-x-3 px-3 py-2.5 text-xs font-semibold text-slate-600 dark:text-slate-400 hover:text-aog-red hover:bg-slate-100 dark:hover:bg-slate-800/50 rounded-xl transition-colors"
          >
            <LogOut className="w-4 h-4" />
            <span>Sign out</span>
          </button>
        </div>
      </div>      </aside>
    </>
  );
};
