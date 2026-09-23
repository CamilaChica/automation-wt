import React, { useState } from 'react';
import axios from 'axios';
import { LockKeyhole, ShieldCheck } from 'lucide-react';
import { apiService } from '../../services/api';
import { BrandMark } from './BrandMark';

interface AuthScreenProps {
  role: 'customer' | 'internal';
  onAuthenticated: () => void;
  onSwitchRole?: () => void;
}

export const AuthScreen: React.FC<AuthScreenProps> = ({ role, onAuthenticated, onSwitchRole }) => {
  const [email, setEmail] = useState(role === 'customer' ? '' : 'camila@wingedtycoons.com');
  const [challengeId, setChallengeId] = useState<string | null>(null);
  const [otp, setOtp] = useState('');
  const [developmentOtp, setDevelopmentOtp] = useState<string | undefined>();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [deliveryFailed, setDeliveryFailed] = useState(false);
  const isCustomer = role === 'customer';
  const isDevelopmentAuth = import.meta.env.VITE_AUTH_ENV === 'development';

  const friendlyAuthError = (error: unknown): string => {
    if (axios.isAxiosError(error)) {
      const status = error.response?.status;
      const detail = typeof error.response?.data?.detail === 'string'
        ? error.response.data.detail
        : undefined;

      if (status === 400) {
        if (detail?.includes('Winged Tycoons staff')) {
          return 'Use the internal sign-in screen for @wingedtycoons.com accounts.';
        }
        if (detail?.includes('Internal users must use')) {
          return 'Internal sign-in requires a @wingedtycoons.com email address.';
        }
        return detail ?? 'Sign-in request is invalid. Please check your email and role.';
      }
      if (status === 401) {
        return 'Your one-time code is invalid or expired. Request a new code.';
      }
      if (status === 403) {
        return detail ?? 'Your account is not authorized for this application.';
      }
      if (status === 429) {
        return detail ?? 'Too many attempts. Please wait and try again.';
      }
      if (status === 503) {
        return detail ?? 'The verification email service is temporarily unavailable. Please try again.';
      }
    }

    if (error instanceof Error && error.message.trim().length > 0) {
      return error.message;
    }
    return 'Sign-in failed. Check your credentials.';
  };

  const requestCode = async () => {
    setLoading(true);
    setError(null);
    setDeliveryFailed(false);
    try {
      const response = await apiService.requestOtp(email, role === 'customer' ? 'ROLE_CUSTOMER' : 'ROLE_INTERNAL');
      setChallengeId(response.challenge_id);
      setDevelopmentOtp(response.development_otp);
    } catch (loginError) {
      setDeliveryFailed(true);
      setError(friendlyAuthError(loginError));
    } finally {
      setLoading(false);
    }
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!challengeId) {
      await requestCode();
      return;
    }
    setLoading(true);
    setError(null);
    try {
        const session = await apiService.verifyOtp(challengeId, otp);
        const isCorrectRole = role === 'customer'
          ? session.role === 'ROLE_CUSTOMER'
          : session.role !== 'ROLE_CUSTOMER';
        if (!isCorrectRole) {
          apiService.logout();
          throw new Error(`Use the ${role} login for this application.`);
        }
        onAuthenticated();
    } catch (loginError) {
      setError(friendlyAuthError(loginError));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={`min-h-screen ${isCustomer ? 'bg-slate-950 text-white' : 'bg-slate-100 text-slate-900'} flex items-center justify-center p-6`}>
      <form onSubmit={submit} className={`w-full max-w-md rounded-3xl border p-8 shadow-xl ${isCustomer ? 'border-slate-800 bg-slate-900' : 'border-slate-200 bg-white'}`}>
        <div className="mb-8 flex items-center gap-3">
          <BrandMark />
          <div><p className="font-display text-lg font-bold">WINGED TYCOONS</p><p className="text-xs uppercase tracking-wider text-slate-400">{isCustomer ? 'Customer portal' : 'Internal command center'}</p></div>
        </div>
        <div className="mb-6 flex items-start gap-3"><LockKeyhole className="mt-1 h-5 w-5 text-aero-blue" /><div><h1 className="font-display text-2xl font-bold">Secure sign in</h1><p className="mt-1 text-sm text-slate-500">Your access is restricted to the {isCustomer ? 'customer portal' : 'internal operations workspace'}.</p></div></div>
        <label htmlFor="auth-email" className="mb-4 block text-sm font-semibold">Work email<input id="auth-email" name="email" autoComplete="email" required type="email" value={email} onChange={event => setEmail(event.target.value)} className="mt-2 w-full rounded-xl border border-slate-300 bg-transparent px-4 py-3 outline-none focus:border-aero-blue" /></label>
        {challengeId && <label htmlFor="auth-otp" className="mb-5 block text-sm font-semibold">One-time code<input id="auth-otp" name="one-time-code" autoComplete="one-time-code" required inputMode="numeric" pattern="[0-9]{6}" value={otp} onChange={event => setOtp(event.target.value)} placeholder="6-digit code" className="mt-2 w-full rounded-xl border border-slate-300 bg-transparent px-4 py-3 outline-none focus:border-aero-blue" /></label>}
        <button disabled={loading} className="w-full rounded-xl bg-aero-blue px-4 py-3 font-bold text-white hover:bg-blue-600 disabled:opacity-60">{loading ? 'Working...' : challengeId ? 'Verify code' : 'Send one-time code'}</button>
        {isDevelopmentAuth && developmentOtp && (
          <p className="mt-4 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
            <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-amber-700">DEVELOPMENT MODE OTP ONLY</span>
            One-time code: <strong className="font-mono">{developmentOtp}</strong>
          </p>
        )}
        {error && <p role="alert" aria-live="assertive" className="mt-4 rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</p>}
        {challengeId && <div className="mt-4 flex items-center justify-between gap-3 text-xs text-slate-500"><button type="button" onClick={() => { setChallengeId(null); setOtp(''); setError(null); setDeliveryFailed(false); }} className="font-semibold underline focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue">Change email</button><button type="button" disabled={loading} onClick={() => { setChallengeId(null); setOtp(''); void requestCode(); }} className="font-semibold text-aero-blue underline disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue">Resend code</button></div>}
        {deliveryFailed && !challengeId && <p className="mt-3 text-xs text-slate-500">Check the verification mailbox configuration or contact support if the problem continues.</p>}
        {onSwitchRole && !challengeId && <button type="button" onClick={onSwitchRole} className="mt-5 w-full rounded-xl border border-slate-300 px-4 py-2.5 text-sm font-semibold text-slate-600 hover:border-aero-blue hover:text-aero-blue focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue">{isCustomer ? 'Team sign in' : 'Customer portal sign in'}</button>}
        <p className="mt-6 flex gap-2 text-xs text-slate-500"><ShieldCheck className="h-4 w-4 shrink-0" /> Sessions expire after 8 hours. Production deployments should replace demo users with an identity provider.</p>
      </form>
    </div>
  );
};
