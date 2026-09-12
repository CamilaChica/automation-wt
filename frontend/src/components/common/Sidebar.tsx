import React from 'react';
import { ViewMode, UserRole, ROLE_ALLOWED_VIEWS } from '../../types';
import { 
  LayoutDashboard, 
  FileText, 
  Search, 
  ShieldCheck, 
  Package, 
  Truck, 
  TrendingUp, 
  Settings, 
  LogOut,
  UserCog
} from 'lucide-react';

interface SidebarProps {
  currentView: ViewMode;
  onSelectView: (view: ViewMode) => void;
  userRole: UserRole;
}

export const Sidebar: React.FC<SidebarProps> = ({ currentView, onSelectView, userRole }) => {
  const allNavItems = [
    {
      id: 'customer' as ViewMode,
      label: 'Dashboard',
      icon: LayoutDashboard,
      badge: null
    },
    {
      id: 'sourcing' as ViewMode,
      label: 'Sourcing Matrix',
      icon: Search,
      badge: '18'
    },
    {
      id: 'aero-procurement' as ViewMode,
      label: 'Proc Command',
      icon: FileText,
      badge: '14'
    },
    {
      id: 'trace-vault' as ViewMode,
      label: 'Trace Vault',
      icon: ShieldCheck,
      badge: '42'
    },
    {
      id: 'fulfillment' as ViewMode,
      label: 'Fulfillment (FCH)',
      icon: Package,
      badge: null
    },
    {
      id: 'sales' as ViewMode,
      label: 'Sales Command',
      icon: TrendingUp,
      badge: '9'
    },
    {
      id: 'admin' as ViewMode,
      label: 'Admin Console',
      icon: UserCog,
      badge: null
    }
  ];

  // Only show sidebar entries the signed-in role is actually allowed to open,
  // so Customer/Sales/Purchasing/Admin interfaces stay properly delimited.
  const navItems = allNavItems.filter(item => ROLE_ALLOWED_VIEWS[userRole].includes(item.id));

  return (
    <aside className="w-full md:w-56 shrink-0 bg-white/90 dark:bg-card-dark/95 border-b md:border-b-0 md:border-r border-slate-200 dark:border-slate-800 flex flex-col justify-between select-none transition-colors">
      <div className="py-3 md:py-4 px-3">
        <div className="hidden md:block px-2 mb-3 text-[10px] font-mono font-bold tracking-widest text-slate-400 dark:text-slate-500 uppercase">
          Command Hub
        </div>

        <nav className="flex md:block gap-1 overflow-x-auto pb-1 md:pb-0">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = currentView === item.id;

            return (
              <button
                key={item.id}
                onClick={() => onSelectView(item.id)}
                className={`shrink-0 md:w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-xs font-semibold transition-all group ${
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
                  <span className={`px-2 py-0.5 text-[10px] font-mono font-bold rounded-full ${
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

        {/* Secondary section */}
        <div className="hidden md:block mt-8 px-2 mb-2 text-[10px] font-mono font-bold tracking-widest text-slate-400 dark:text-slate-500 uppercase">
          System Utility
        </div>
        <div className="hidden md:block space-y-1">
          <button
            onClick={() => onSelectView('fulfillment')}
            disabled={!ROLE_ALLOWED_VIEWS[userRole].includes('fulfillment')}
            className="w-full flex items-center space-x-3 px-3 py-2 text-xs text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800/50 rounded-xl transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent"
          >
            <Truck className="w-4 h-4 text-slate-400" />
            <span>Logistics API</span>
          </button>
          <button
            onClick={() => onSelectView('admin')}
            disabled={!ROLE_ALLOWED_VIEWS[userRole].includes('admin')}
            className="w-full flex items-center space-x-3 px-3 py-2 text-xs text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800/50 rounded-xl transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent"
          >
            <Settings className="w-4 h-4 text-slate-400" />
            <span>Account Settings</span>
          </button>
        </div>
      </div>

      {/* Footer System Integrity Status */}
      <div className="hidden md:block p-3 border-t border-slate-200 dark:border-slate-800">
        <div className="bg-slate-50 dark:bg-slate-900/90 rounded-xl p-2.5 border border-slate-200 dark:border-slate-800">
          <div className="flex items-center justify-between text-[11px] font-mono font-semibold mb-1">
            <span className="text-slate-600 dark:text-slate-400">SYSTEM HEALTH</span>
            <span className="text-emerald-600 dark:text-emerald-400">99.9%</span>
          </div>
          <div className="w-full bg-slate-200 dark:bg-slate-800 h-1.5 rounded-full overflow-hidden">
            <div className="bg-emerald-500 h-full w-[99.9%]" />
          </div>
          <div className="mt-2 flex items-center justify-between text-[9px] font-mono text-slate-500">
            <span>FASTAPI MVP</span>
            <span>v1.0.0</span>
          </div>
        </div>

        <button className="mt-2 w-full flex items-center justify-center space-x-2 py-1.5 rounded text-xs text-slate-400 hover:text-aog-red transition-colors">
          <LogOut className="w-3.5 h-3.5" />
          <span>Exit Command Center</span>
        </button>
      </div>
    </aside>
  );
};
