import React, { useState } from 'react';
import axios from 'axios';
import { LockKeyhole, ShieldCheck } from 'lucide-react';
import { apiService } from '../../services/api';
import { BrandMark } from './BrandMark';
import { PrivacyPolicyModal } from './PrivacyPolicyModal';

interface AuthScreenProps {
  role: 'customer' | 'internal';
  onAuthenticated: () => void;
  onSwitchRole?: () => void;
}

export const AuthScreen: React.FC<AuthScreenProps> = ({ role, onAuthenticated, onSwitchRole }) => {
  const [email, setEmail] = useState('');
  const [challengeId, setChallengeId] = useState<string | null>(null);
  const [otp, setOtp] = useState('');
  const [developmentOtp, setDevelopmentOtp] = useState<string | undefined>();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [deliveryFailed, setDeliveryFailed] = useState(false);
  const [pendingPrivacyPolicy, setPendingPrivacyPolicy] = useState(false);
  const [viewPrivacyModal, setViewPrivacyModal] = useState(false);
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
    setDevelopmentOtp(undefined);
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
        if (role === 'customer' && !session.privacy_policy_accepted) {
          setPendingPrivacyPolicy(true);
        } else {
          onAuthenticated();
        }
    } catch (loginError) {
      setError(friendlyAuthError(loginError));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={`min-h-screen ${isCustomer ? 'bg-slate-50 text-slate-900' : 'bg-slate-950 text-slate-100'} flex items-center justify-center p-6`}>
      <form onSubmit={submit} className={`w-full max-w-md rounded-3xl border p-8 shadow-xl ${isCustomer ? 'border-slate-200 bg-white' : 'border-slate-700 bg-slate-900 text-slate-100'}`}>
        <div className="mb-8 flex items-center gap-3">
          <BrandMark />
          <div><p className="font-display text-lg font-bold">WINGED TYCOONS</p><p className="text-xs uppercase tracking-wider text-slate-400">{isCustomer ? 'Customer portal' : 'Internal command center'}</p></div>
        </div>
        <div className="mb-6 flex items-start gap-3"><LockKeyhole className="mt-1 h-5 w-5 text-aero-blue" /><div><h1 className="font-display text-2xl font-bold">Secure sign in</h1><p className="mt-1 text-sm text-slate-500">Your access is restricted to the {isCustomer ? 'customer portal' : 'internal operations workspace'}.</p></div></div>
        <label htmlFor="auth-email" className="block text-sm font-semibold">Work email</label><input id="auth-email" name={isCustomer ? 'email' : 'wt-crew-login'} autoComplete={isCustomer ? 'email' : 'off'} data-lpignore="true" data-1p-ignore="true" autoCorrect="off" autoCapitalize="none" spellCheck={false} required type={isCustomer ? 'email' : 'text'} inputMode="email" placeholder="name@company.com" value={email} onChange={event => setEmail(event.target.value)} className={`auth-input mb-4 mt-2 w-full select-text rounded-xl border px-4 py-3 outline-none focus:ring-2 focus:ring-aero-blue focus:outline-none selection:bg-aero-blue selection:text-white ${isCustomer ? 'border-slate-300 bg-white text-slate-900 caret-slate-900' : 'border-slate-600 bg-slate-950 text-slate-100 caret-white'}`} />
        {challengeId && <label htmlFor="auth-otp" className="mb-5 block text-sm font-semibold">One-time code<input id="auth-otp" name="one-time-code" autoComplete="one-time-code" required inputMode="numeric" pattern="[0-9]{6}" value={otp} onChange={event => setOtp(event.target.value)} placeholder="6-digit code" className={`mt-2 w-full rounded-xl border px-4 py-3 outline-none focus:ring-2 focus:ring-aero-blue focus:outline-none ${isCustomer ? 'border-slate-300 bg-white text-slate-900' : 'border-slate-600 bg-slate-950 text-slate-100'}`} /></label>}
        <button type="submit" disabled={loading} aria-busy={loading} className="min-h-[44px] w-full rounded-xl bg-aero-blue px-4 py-3 font-bold text-white hover:bg-blue-600 disabled:opacity-60">{loading ? 'Working...' : challengeId ? 'Verify code' : 'Send one-time code'}</button>
        {isDevelopmentAuth && developmentOtp && (
          <p className="mt-4 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
            <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-amber-700">DEVELOPMENT MODE OTP ONLY</span>
            One-time code: <strong className="font-mono">{developmentOtp}</strong>
          </p>
        )}
        {error && <p role="alert" aria-live="assertive" className="mt-4 rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</p>}
        {challengeId && <div className="mt-4 flex items-center justify-between gap-3 text-xs text-slate-500"><button type="button" onClick={() => { setChallengeId(null); setOtp(''); setError(null); setDeliveryFailed(false); }} className="font-semibold underline focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue">Change email</button><button type="button" disabled={loading} onClick={() => { setChallengeId(null); setOtp(''); void requestCode(); }} className="font-semibold text-aero-blue underline disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue">Resend code</button></div>}
        {deliveryFailed && !challengeId && <p className="mt-3 text-xs text-slate-500">Check the verification mailbox configuration or contact support if the problem continues.</p>}
        {onSwitchRole && !challengeId && <button type="button" onClick={onSwitchRole} className="mt-5 min-h-[44px] w-full rounded-xl border border-slate-300 px-4 py-2.5 text-sm font-semibold text-slate-600 hover:border-aero-blue hover:text-aero-blue focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue">{isCustomer ? 'Team sign in' : 'Customer portal sign in'}</button>}
        
        <div className="mt-6 flex flex-col gap-2 text-xs text-slate-500">
          <p className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 shrink-0" /> Secure sign-in. For your protection, sessions expire after 8 hours.</p>
          <div className="flex items-center justify-between pt-2 border-t border-slate-200 dark:border-slate-800">
            <span>Commercial aviation data protection</span>
            <button
              type="button"
              onClick={() => setViewPrivacyModal(true)}
              className="text-xs text-aero-blue font-semibold underline hover:text-blue-700 focus:outline-none"
            >
              Privacy Policy
            </button>
          </div>
        </div>
      </form>

      {/* First-time sign in mandatory modal */}
      <PrivacyPolicyModal
        isOpen={pendingPrivacyPolicy}
        companyOrEmail={email}
        onAccept={async () => {
          await apiService.acceptPrivacyPolicy();
          setPendingPrivacyPolicy(false);
          onAuthenticated();
        }}
        onDecline={() => {
          apiService.logout();
          setPendingPrivacyPolicy(false);
          setChallengeId(null);
          setOtp('');
        }}
      />

      {/* Read-only policy viewer modal */}
      <PrivacyPolicyModal
        isOpen={viewPrivacyModal}
        isReadOnly={true}
        onClose={() => setViewPrivacyModal(false)}
      />
    </div>
  );
};
