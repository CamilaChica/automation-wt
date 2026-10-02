import React, { useState, useEffect } from 'react';
import { ViewMode, ThemeMode, AgentAuditLog, AutomationEvent } from './types';
import { TopBar } from './components/common/TopBar';
import { Sidebar } from './components/common/Sidebar';
import { AuditLogDrawer } from './components/common/AuditLogDrawer';
import { CustomerDashboard } from './components/views/CustomerDashboard';
import { SupplierSourcingView } from './components/views/SupplierSourcingView';
import { AeroProcurementView } from './components/views/AeroProcurementView';
import { TraceVaultView } from './components/views/TraceVaultView';
import { FulfillmentHubView } from './components/views/FulfillmentHubView';
import { SalesCommandView } from './components/views/SalesCommandView';
import { CustomerPortal } from './components/views/CustomerPortal';
import { LandingPage } from './components/views/LandingPage';
import { InternalTeamPortal } from './components/views/InternalTeamPortal';
import { VoiceServiceView } from './components/views/VoiceServiceView';
import { AuthScreen } from './components/common/AuthScreen';
import { EmployeeProfilePanel } from './components/common/EmployeeProfilePanel';
import { apiService } from './services/api';
import { getThemePreference, getViewPreference, setThemePreference, setViewPreference } from './services/preferences';

const InternalApp: React.FC = () => {
  const [authenticated, setAuthenticated] = useState(apiService.getRole() === 'internal');
  const [currentView, setCurrentViewState] = useState<ViewMode>(getViewPreference());
  const [theme, setThemeState] = useState<ThemeMode>(getThemePreference('dark'));
  const [isAuditLogOpen, setIsAuditLogOpen] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isEmployeeProfileOpen, setIsEmployeeProfileOpen] = useState(false);
  const [auditLogs, setAuditLogs] = useState<AgentAuditLog[]>([]);
  const [auditRfqId, setAuditRfqId] = useState('');
  const [isLiveAuditUnavailable, setIsLiveAuditUnavailable] = useState(false);

  useEffect(() => {
    const handleAuthChange = () => setAuthenticated(apiService.getRole() === 'internal');
    window.addEventListener('wt-auth-changed', handleAuthChange);
    return () => window.removeEventListener('wt-auth-changed', handleAuthChange);
  }, []);

  useEffect(() => {
    let active = true;
    const loadAuditFeed = async () => {
      const rfqs = await apiService.getRFQs();
      if (!active) return;
      if (rfqs.length === 0) {
        setIsLiveAuditUnavailable(true);
        setAuditLogs([]);
        setAuditRfqId('No RFQs');
        return;
      }
      let events: AutomationEvent[] = [];
      let eventsUnavailable = false;
      try {
        events = await apiService.getAutomationEvents();
      } catch {
        eventsUnavailable = true;
      }
      const detail = await apiService.getRFQDetail(rfqs[0].id);
      if (active) {
        setAuditRfqId(rfqs[0].id);
        const eventLogs: AgentAuditLog[] = (events as AutomationEvent[]).map(event => ({
          rfq_id: event.entity_type === 'rfq' ? event.entity_id : rfqs[0].id,
          agent_name: `${event.event_type} automation`,
          action_type: event.status,
          message: event.error || event.result || `Automation event ${event.status.toLowerCase()}. Attempts: ${event.attempts}/${event.max_attempts}.`,
          status: event.status === 'FAILED' ? 'FAILURE' : event.status === 'SUCCEEDED' ? 'SUCCESS' : 'WARNING',
          timestamp: event.execution_time || event.created_at,
        }));
        const liveLogs = [...eventLogs, ...(detail.logs || [])];
        setAuditLogs(liveLogs);
        setIsLiveAuditUnavailable(eventsUnavailable || liveLogs.length === 0);
      }
    };

    void loadAuditFeed().catch(() => {
      if (active) {
        setIsLiveAuditUnavailable(true);
        setAuditLogs([]);
        setAuditRfqId('Live activity unavailable');
      }
    });
    const refresh = window.setInterval(() => {
      void loadAuditFeed().catch(() => undefined);
    }, 10000);
    return () => {
      active = false;
      window.clearInterval(refresh);
    };
  }, []);

  // Sync theme with HTML class
  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'dark') {
      root.classList.add('dark');
      root.classList.remove('light');
    } else {
      root.classList.add('light');
      root.classList.remove('dark');
    }
  }, [theme]);

  const toggleTheme = () => {
    setThemeState(prev => {
      const next = prev === 'dark' ? 'light' : 'dark';
      setThemePreference(next);
      return next;
    });
  };
  const setCurrentView = (view: ViewMode) => {
    setViewPreference(view);
    setCurrentViewState(view);
  };

  const renderActiveView = () => {
    switch (currentView) {
      case 'customer':
        return <CustomerDashboard />;
      case 'sourcing':
        return <SupplierSourcingView />;
      case 'aero-procurement':
        return <AeroProcurementView />;
      case 'trace-vault':
        return <TraceVaultView />;
      case 'fulfillment':
        return <FulfillmentHubView />;
      case 'sales':
        return <SalesCommandView />;
      case 'voice-service':
        return <VoiceServiceView />;
      default:
        return <CustomerDashboard />;
    }
  };

  if (!authenticated) {
    return <AuthScreen role="internal" onAuthenticated={() => setAuthenticated(true)} onSwitchRole={() => { window.location.href = '/customer-portal'; }} />;
  }

  return (
    <div className={`min-h-screen flex flex-col font-sans transition-colors duration-200 ${
      theme === 'dark' ? 'bg-canvas-dark text-slate-100' : 'bg-canvas-light text-slate-900'
    }`}>
      {/* Global Top App Bar */}
      <TopBar
        currentView={currentView}
        theme={theme}
        onToggleTheme={toggleTheme}
        onSelectView={setCurrentView}
        onSearch={(query) => {
          const normalized = query.trim().toLowerCase();
          if (normalized.includes('supplier') || normalized.includes('part')) setCurrentView('sourcing');
          else if (normalized.includes('quote') || normalized.includes('sales')) setCurrentView('sales');
          else if (normalized.includes('trace') || normalized.includes('compliance')) setCurrentView('trace-vault');
          else if (normalized.includes('shipment') || normalized.includes('fulfillment')) setCurrentView('fulfillment');
        }}
        onOpenAuditLog={() => setIsAuditLogOpen(true)}
        onOpenSidebar={() => setIsSidebarOpen(true)}
        onOpenProfile={() => setIsEmployeeProfileOpen(true)}
      />

      {/* Main Content Layout (Sidebar + Active View) */}
      <div className="flex-1 flex overflow-hidden">
        <Sidebar
          currentView={currentView}
          onSelectView={setCurrentView}
          isMobileOpen={isSidebarOpen}
          onCloseMobile={() => setIsSidebarOpen(false)}
          onOpenProfile={() => setIsEmployeeProfileOpen(true)}
        />

        <main className="min-w-0 flex-1 overflow-y-auto bg-slate-50 dark:bg-slate-950/60">
          {renderActiveView()}
        </main>
      </div>

      {/* Slide-over Agent Audit Log Drawer */}
      <AuditLogDrawer
        isOpen={isAuditLogOpen}
        onClose={() => setIsAuditLogOpen(false)}
        logs={auditLogs}
        rfqId={auditRfqId || 'Live operations'}
        isLiveAuditUnavailable={isLiveAuditUnavailable}
      />
      {isEmployeeProfileOpen && <EmployeeProfilePanel onClose={() => setIsEmployeeProfileOpen(false)} />}
    </div>
  );
};

const CustomerPortalRoute: React.FC = () => {
  const [authenticated, setAuthenticated] = useState(apiService.getRole() === 'customer');
  useEffect(() => {
    const handleAuthChange = () => setAuthenticated(apiService.getRole() === 'customer');
    window.addEventListener('wt-auth-changed', handleAuthChange);
    return () => window.removeEventListener('wt-auth-changed', handleAuthChange);
  }, []);
  return authenticated ? <CustomerPortal /> : <AuthScreen role="customer" onAuthenticated={() => setAuthenticated(true)} onSwitchRole={() => { window.location.href = '/internal'; }} />;
};

export const App: React.FC = () => {
  const isTeamHost = window.location.hostname.startsWith('team.');
  const isLandingPath = window.location.pathname === '/' && !isTeamHost;
  const isTeamPortalPath = window.location.pathname === '/team-portal' || (isTeamHost && window.location.pathname === '/');
  const isCustomerPath =
    window.location.pathname.startsWith('/customer-portal') ||
    window.location.pathname.startsWith('/portal');
  const isInternalPath = window.location.pathname.startsWith('/internal');
  const isCustomerSession = apiService.getRole() === 'customer';
  const isInternalSession = apiService.getRole() === 'internal';
  if (isTeamPortalPath) return <InternalTeamPortal />;
  if (isInternalPath) return <InternalApp />;
  if (isCustomerPath) return <CustomerPortalRoute />;
  if (isLandingPath) return <LandingPage />;
  if (isInternalSession) return <InternalApp />;
  if (isCustomerSession) return <CustomerPortalRoute />;
  return <CustomerPortalRoute />;
};

export default App;
