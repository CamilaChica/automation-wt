import React, { useEffect, useState } from 'react';
import { AlertCircle, Headphones, Mic, MicOff, Phone, PhoneOff, X } from 'lucide-react';
import { useRealtimeVoice } from '../../hooks/useRealtimeVoice';
import { getPreferredVoiceLanguage, setPreferredVoiceLanguage, voiceLanguages, VoiceLanguage } from '../../services/voice';
import { CustomerLanguage, customerLanguages, translateCustomerPortal } from '../../i18n/customerPortal';

interface CustomerVoiceContactProps {
  uiLanguage: CustomerLanguage;
  isOpen: boolean;
  onClose: () => void;
}

const statusTone: Record<string, string> = {
  Idle: 'bg-slate-100 text-slate-700',
  Connecting: 'bg-sky-100 text-sky-800',
  Connected: 'bg-emerald-100 text-emerald-800',
  'Checking Inventory': 'bg-sky-100 text-sky-800',
  Escalated: 'bg-amber-100 text-amber-900',
};

export const CustomerVoiceContact: React.FC<CustomerVoiceContactProps> = ({ uiLanguage, isOpen, onClose }) => {
  const t = (phrase: Parameters<typeof translateCustomerPortal>[1]) => translateCustomerPortal(uiLanguage, phrase);
  const [language, setLanguage] = useState<VoiceLanguage>(getPreferredVoiceLanguage);
  const [reviewNotice, setReviewNotice] = useState('');
  const call = useRealtimeVoice({ onEscalated: () => setReviewNotice(translateCustomerPortal(uiLanguage, 'escalationNotice')) });

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        call.endCall();
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const close = () => {
    call.endCall();
    onClose();
  };

  const start = () => {
    setPreferredVoiceLanguage(language);
    setReviewNotice('');
    void call.startCall(language);
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/60 p-3 sm:p-6" onMouseDown={event => { if (event.target === event.currentTarget) close(); }}>
      <section role="dialog" aria-modal="true" aria-labelledby="customer-voice-title" className="flex max-h-[92vh] w-full max-w-xl flex-col overflow-hidden border border-slate-200 bg-white shadow-2xl">
        <header className="flex items-start justify-between border-b border-slate-200 px-5 py-4">
          <div>
            <p className="flex items-center gap-2 text-xs font-semibold uppercase text-cyan-800"><Headphones className="h-4 w-4" /> {t('voiceSupport')}</p>
            <h2 id="customer-voice-title" className="mt-1 text-lg font-bold text-slate-900">{t('voiceTitle')}</h2>
          </div>
          <button type="button" onClick={close} aria-label={t('closeVoice')} className="inline-flex h-10 w-10 items-center justify-center text-slate-500 hover:bg-slate-100 hover:text-slate-900"><X className="h-5 w-5" /></button>
        </header>

        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
          <div className="border-b border-slate-200 px-5 py-4">
            <label htmlFor="voice-contact-language" className="mb-1.5 block text-xs font-semibold text-slate-700">{t('conversationLanguage')}</label>
            <select id="voice-contact-language" value={language} disabled={call.isConnecting || call.callStatus !== 'Idle'} onChange={event => setLanguage(event.target.value as VoiceLanguage)} className="min-h-11 w-full border border-slate-300 bg-white px-3 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-cyan-600 disabled:bg-slate-100">
              {voiceLanguages.map(option => <option key={option.code} value={option.code}>{customerLanguages.find(languageOption => languageOption.code === option.code)?.label ?? option.label}</option>)}
            </select>
            <p className="mt-2 text-xs leading-5 text-slate-500">{t('voiceLanguageHint')}</p>
          </div>

          <div className="flex flex-col items-center border-b border-slate-200 px-5 py-5">
            <span className={`rounded px-2.5 py-1 text-xs font-semibold ${statusTone[call.callStatus]}`} aria-live="polite">{t(({ Idle: 'idle', Connecting: 'connecting', Connected: 'connected', 'Checking Inventory': 'checkingInventory', Escalated: 'escalated' } as const)[call.callStatus])}</span>
            <div className="relative my-4 flex h-20 w-20 items-center justify-center rounded-full border border-cyan-200 bg-cyan-50">
              <div className="absolute inset-2 rounded-full border border-cyan-300" style={{ transform: `scale(${1 + call.micLevel * 0.18})`, opacity: 0.35 + call.micLevel * 0.65 }} />
              {call.micLevel > 0.025 ? <Mic className="h-7 w-7 text-cyan-800" /> : <MicOff className="h-7 w-7 text-slate-500" />}
            </div>
            <div className="mb-4 flex h-6 items-center gap-1" role="meter" aria-label="Microphone input level" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(call.micLevel * 100)}>
              {Array.from({ length: 21 }, (_, index) => <span key={index} className={`w-1 rounded-full ${index < Math.round(call.micLevel * 21) ? 'bg-cyan-600' : 'bg-slate-200'}`} style={{ height: 6 + ((index * 7) % 16) }} />)}
            </div>
            <div className="flex gap-2">
              <button type="button" onClick={start} disabled={call.callStatus !== 'Idle' || call.isConnecting} className="inline-flex min-h-11 items-center gap-2 bg-cyan-800 px-4 text-sm font-semibold text-white hover:bg-cyan-900 disabled:cursor-not-allowed disabled:opacity-50">
                <Phone className="h-4 w-4" /> {call.isConnecting ? t('connectingCall') : t('startCall')}
              </button>
              <button type="button" onClick={call.endCall} disabled={call.callStatus === 'Idle' && !call.isConnecting} className="inline-flex min-h-11 items-center gap-2 border border-slate-300 px-4 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40">
                <PhoneOff className="h-4 w-4" /> {t('endCall')}
              </button>
            </div>
            <p className="mt-3 max-w-sm text-center text-xs leading-5 text-slate-500">{t('voiceDisclosure')}</p>
          </div>

          {(call.errorMessage || reviewNotice) && <div role="status" className="flex items-start gap-2 border-b border-slate-200 bg-amber-50 px-5 py-3 text-sm text-amber-900"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0" /><span>{call.errorMessage || reviewNotice}</span></div>}

          <div className="flex min-h-44 flex-1 flex-col">
            <div className="flex items-center justify-between px-5 py-3"><h3 className="text-xs font-bold uppercase text-slate-600">{t('transcript')}</h3><span className="text-[11px] text-slate-500">{t('transcriptLive')}</span></div>
            <div className="max-h-56 min-h-32 flex-1 space-y-3 overflow-y-auto px-5 pb-4" aria-live="polite" aria-relevant="additions text">
              {call.transcript.length ? call.transcript.map(entry => <article key={entry.id} className={`border-l-2 px-3 py-2 ${entry.speaker === 'Customer' ? 'border-slate-300' : 'border-cyan-600'}`}>
                <div className="mb-1 flex items-center justify-between gap-2"><span className="text-xs font-bold text-slate-800">{entry.speaker === 'Customer' ? t('you') : t('voiceAssistant')}</span><time className="text-[10px] text-slate-500">{entry.time}</time></div>
                <p className="text-sm leading-5 text-slate-700">{entry.text}</p>
              </article>) : <p className="py-10 text-center text-sm text-slate-500">{t('transcriptPlaceholder')}</p>}
            </div>
          </div>
        </div>
        <audio ref={call.remoteAudioRef} autoPlay className="sr-only" aria-label="AI voice assistant audio" />
      </section>
    </div>
  );
};