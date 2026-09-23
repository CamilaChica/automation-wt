import { ThemeMode, ViewMode } from '../types';

const COOKIE_MAX_AGE = 60 * 60 * 24 * 365;

function getCookie(name: string): string | null {
  const prefix = `${encodeURIComponent(name)}=`;
  const entry = document.cookie.split('; ').find(value => value.startsWith(prefix));
  return entry ? decodeURIComponent(entry.slice(prefix.length)) : null;
}

function setCookie(name: string, value: string): void {
  document.cookie = `${encodeURIComponent(name)}=${encodeURIComponent(value)}; Max-Age=${COOKIE_MAX_AGE}; Path=/; SameSite=Lax`;
}

export function getThemePreference(): ThemeMode {
  return getCookie('wt_theme') === 'dark' ? 'dark' : 'light';
}

export function setThemePreference(theme: ThemeMode): void {
  setCookie('wt_theme', theme);
}

export function getViewPreference(): ViewMode {
  const value = getCookie('wt_internal_view');
  const views: ViewMode[] = ['customer', 'sourcing', 'aero-procurement', 'trace-vault', 'fulfillment', 'sales', 'swarm-simulation'];
  return views.includes(value as ViewMode) ? value as ViewMode : 'customer';
}

export function setViewPreference(view: ViewMode): void {
  setCookie('wt_internal_view', view);
}
