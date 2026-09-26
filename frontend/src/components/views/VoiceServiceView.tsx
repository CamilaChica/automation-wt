import React, { useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  ArrowUpRight,
  Clock3,
  Headphones,
  Mic,
  MicOff,
  PackageCheck,
  Phone,
  PhoneOff,
  RefreshCw,
} from 'lucide-react';
import { voiceService, VoiceConcern, VoiceDashboard, VoiceRequest } from '../../services/voice';

type CallStatus = 'Idle' | 'Connected' | 'Checking Inventory' | 'Escalated';
type TranscriptEntry = { id: string; speaker: 'Customer' | 'Representative'; text: string; time: string };

const statusStyles: Record<CallStatus, string> = {
  Idle: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
  Connected: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/70 dark:text-emerald-300',
  'Checking Inventory': 'bg-sky-100 text-sky-800 dark:bg-sky-950/70 dark:text-sky-300',
  Escalated: 'bg-amber-100 text-amber-900 dark:bg-amber-950/70 dark:text-amber-300',
};

function formatUsd(value: number): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(value);
}

function statusTone(status: string): string {
  if (status.toLowerCase().includes('escalat')) return 'text-amber-700 dark:text-amber-300';
  if (status.toLowerCase().includes('reserved')) return 'text-emerald-700 dark:text-emerald-300';
  return 'text-sky-700 dark:text-sky-300';
}

export const VoiceServiceView: React.FC = () => {
  const [dashboard, setDashboard] = useState<VoiceDashboard>({ inventory: [], requests: [], human_queue: [] });
  const [callStatus, setCallStatus] = useState<CallStatus>('Idle');
  const [isConnecting, setIsConnecting] = useState(false);
  const [micLevel, setMicLevel] = useState(0);
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [errorMessage, setErrorMessage] = useState('');
  const peerRef = useRef<RTCPeerConnection | null>(null);
  const channelRef = useRef<RTCDataChannel | null>(null);
  const localStreamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const remoteAudioRef = useRef<HTMLAudioElement | null>(null);
  const generationRef = useRef(0);
  const escalatedRef = useRef(false);
  const lastMicLevelRef = useRef(0);

  useEffect(() => {
    let active = true;
    void voiceService.getDashboard().then(data => {
      if (active) setDashboard(data);
    }).catch(() => {
      if (active) setErrorMessage('Operations data is unavailable. Check your connection and refresh.');
    });
    return () => { active = false; };
  }, []);

  const releaseCallResources = () => {
    generationRef.current += 1;
    if (animationFrameRef.current !== null) cancelAnimationFrame(animationFrameRef.current);
    animationFrameRef.current = null;
    channelRef.current?.close();
    channelRef.current = null;
    peerRef.current?.close();
    peerRef.current = null;
    localStreamRef.current?.getTracks().forEach(track => track.stop());
    localStreamRef.current = null;
    if (remoteAudioRef.current) remoteAudioRef.current.srcObject = null;
    void audioContextRef.current?.close();
    audioContextRef.current = null;
    setMicLevel(0);
  };

  useEffect(() => () => {
    if (animationFrameRef.current !== null) cancelAnimationFrame(animationFrameRef.current);
    channelRef.current?.close();
    peerRef.current?.close();
    localStreamRef.current?.getTracks().forEach(track => track.stop());
    if (remoteAudioRef.current) remoteAudioRef.current.srcObject = null;
    void audioContextRef.current?.close();
  }, []);

  const appendTranscript = (speaker: TranscriptEntry['speaker'], text: string) => {
    const cleanText = text.trim();
    if (!cleanText) return;
    setTranscript(current => [...current, {
      id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
      speaker,
      text: cleanText,
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    }].slice(-80));
  };

  const handleRealtimeEvent = async (eventData: string, generation: number) => {
    let event: Record<string, any>;
    try {
      event = JSON.parse(eventData) as Record<string, any>;
    } catch {
      return;
    }

    if (event.type === 'conversation.item.input_audio_transcription.completed') {
      appendTranscript('Customer', event.transcript || '');
    } else if (['response.audio_transcript.done', 'response.output_audio_transcript.done', 'response.output_text.done'].includes(event.type)) {
      appendTranscript('Representative', event.transcript || event.text || '');
    } else if (event.type === 'response.output_item.done' && event.item?.type === 'function_call') {
      const toolName = String(event.item.name || '');
      const callId = String(event.item.call_id || '');
      if (!['check_inventory_availability', 'get_order_status', 'log_customer_concern'].includes(toolName) || !callId) return;
      setCallStatus(toolName === 'log_customer_concern' ? 'Escalated' : 'Checking Inventory');
      try {
        const args = JSON.parse(event.item.arguments || '{}') as Record<string, unknown>;
        const result = await voiceService.executeTool(toolName, args);
        if (generation !== generationRef.current) return;
        const requiresReview = Boolean((result as { requires_review?: boolean })?.requires_review);
        if (requiresReview) {
          escalatedRef.current = true;
          setCallStatus('Escalated');
          const latest = await voiceService.getDashboard();
          if (generation === generationRef.current) setDashboard(latest);
        } else {
          setCallStatus('Connected');
        }
        const channel = channelRef.current;
        if (channel?.readyState === 'open') {
          channel.send(JSON.stringify({
            type: 'conversation.item.create',
            item: { type: 'function_call_output', call_id: callId, output: JSON.stringify(result) },
          }));
          channel.send(JSON.stringify({ type: 'response.create' }));
        }
      } catch {
        escalatedRef.current = true;
        setCallStatus('Escalated');
        setErrorMessage('The operations lookup failed. The request has not been confirmed.');
        const channel = channelRef.current;
        if (channel?.readyState === 'open') {
          channel.send(JSON.stringify({
            type: 'conversation.item.create',
            item: { type: 'function_call_output', call_id: callId, output: JSON.stringify({ error: 'Lookup unavailable. Tell the customer an operator will follow up.' }) },
          }));
          channel.send(JSON.stringify({ type: 'response.create' }));
        }
      }
    } else if (event.type === 'response.done' && !escalatedRef.current) {
      setCallStatus('Connected');
    } else if (event.type === 'error') {
      setErrorMessage(event.error?.message || 'The voice connection reported an error.');
    }
  };

  const startCall = async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      setErrorMessage('Microphone access is not available in this browser. Use a secure connection and try again.');
      return;
    }
    const generation = ++generationRef.current;
    setErrorMessage('');
    setTranscript([]);
    escalatedRef.current = false;
    setCallStatus('Idle');
    setIsConnecting(true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (generation !== generationRef.current) {
        stream.getTracks().forEach(track => track.stop());
        return;
      }
      localStreamRef.current = stream;
      const session = await voiceService.createSession();
      if (generation !== generationRef.current) return;

      const peer = new RTCPeerConnection();
      peerRef.current = peer;
      stream.getTracks().forEach(track => peer.addTrack(track, stream));
      peer.ontrack = event => {
        if (remoteAudioRef.current) {
          remoteAudioRef.current.srcObject = event.streams[0];
          void remoteAudioRef.current.play().catch(() => undefined);
        }
      };
      peer.onconnectionstatechange = () => {
        if (peer.connectionState === 'failed') {
          setErrorMessage('The call connection failed. Check your network and start a new call.');
          releaseCallResources();
          setCallStatus('Idle');
          setIsConnecting(false);
        }
      };

      const channel = peer.createDataChannel('oai-events');
      channelRef.current = channel;
      channel.onopen = () => {
        if (generation === generationRef.current) {
          setCallStatus('Connected');
          setIsConnecting(false);
        }
      };
      channel.onmessage = message => { void handleRealtimeEvent(message.data, generation); };

      const audioContext = new AudioContext();
      audioContextRef.current = audioContext;
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      audioContext.createMediaStreamSource(stream).connect(analyser);
      const samples = new Uint8Array(analyser.fftSize);
      const updateLevel = () => {
        analyser.getByteTimeDomainData(samples);
        const rms = Math.sqrt(samples.reduce((sum, sample) => sum + ((sample - 128) / 128) ** 2, 0) / samples.length);
        const level = Math.min(1, rms * 2.5);
        if (Math.abs(level - lastMicLevelRef.current) >= 0.025) {
          lastMicLevelRef.current = level;
          setMicLevel(level);
        }
        animationFrameRef.current = requestAnimationFrame(updateLevel);
      };
      updateLevel();

      const offer = await peer.createOffer();
      await peer.setLocalDescription(offer);
      const answerResponse = await fetch('https://api.openai.com/v1/realtime/calls', {
        method: 'POST',
        headers: { Authorization: `Bearer ${session.client_secret}`, 'Content-Type': 'application/sdp' },
        body: peer.localDescription?.sdp,
      });
      if (!answerResponse.ok) throw new Error('OpenAI could not accept the audio connection.');
      if (generation !== generationRef.current) return;
      await peer.setRemoteDescription({ type: 'answer', sdp: await answerResponse.text() });
    } catch (error) {
      releaseCallResources();
      setCallStatus('Idle');
      const message = error instanceof Error ? error.message : 'Unable to start the call.';
      setErrorMessage(message.toLowerCase().includes('permission') || message.toLowerCase().includes('denied')
        ? 'Microphone permission was denied. Allow microphone access in your browser to start a call.'
        : message);
    } finally {
      setIsConnecting(false);
    }
  };

  const endCall = () => {
    releaseCallResources();
    escalatedRef.current = false;
    setCallStatus('Idle');
    setIsConnecting(false);
  };

  const refreshDashboard = async () => {
    try {
      setDashboard(await voiceService.getDashboard());
      setErrorMessage('');
    } catch {
      setErrorMessage('Operations data could not be refreshed.');
    }
  };

  return (
    <div className="mx-auto w-full max-w-[1600px] px-4 py-5 sm:px-6 lg:px-8">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3 border-b border-slate-200 pb-4 dark:border-slate-800">
        <div>
          <div className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase text-cyan-700 dark:text-cyan-400">
            <Headphones className="h-4 w-4" /> Aerospace Global Industry Supplies
          </div>
          <h1 className="text-xl font-bold text-slate-900 dark:text-white">Customer service desk</h1>
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
          <span className={`h-2 w-2 rounded-full ${callStatus === 'Connected' || callStatus === 'Checking Inventory' ? 'bg-emerald-500' : callStatus === 'Escalated' ? 'bg-amber-500' : 'bg-slate-400'}`} />
          Voice channel {callStatus === 'Idle' ? 'ready' : 'active'}
        </div>
      </div>

      {errorMessage && (
        <div role="alert" className="mb-4 flex items-start gap-2 border-l-4 border-amber-500 bg-amber-50 px-3 py-2.5 text-sm text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> <span>{errorMessage}</span>
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,0.88fr)_minmax(0,1.12fr)]">
        <section aria-label="Live call center" className="flex min-h-[650px] flex-col border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800">
            <div>
              <h2 className="text-sm font-bold text-slate-900 dark:text-white">Live call center</h2>
              <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">Realtime customer channel</p>
            </div>
            <span className={`rounded px-2.5 py-1 text-xs font-semibold ${statusStyles[callStatus]}`} aria-live="polite">{callStatus}</span>
          </div>

          <div className="flex min-h-[218px] flex-col items-center justify-center border-b border-slate-200 px-5 py-6 dark:border-slate-800">
            <div className="relative mb-4 flex h-24 w-24 items-center justify-center rounded-full border border-cyan-200 bg-cyan-50 dark:border-cyan-900 dark:bg-cyan-950/50">
              <div className="absolute inset-2 rounded-full border border-cyan-300/70 dark:border-cyan-700" style={{ transform: `scale(${1 + micLevel * 0.18})`, opacity: 0.4 + micLevel * 0.6 }} />
              {micLevel > 0.025 ? <Mic className="h-8 w-8 text-cyan-700 dark:text-cyan-300" /> : <MicOff className="h-8 w-8 text-slate-500 dark:text-slate-400" />}
            </div>
            <div className="mb-5 flex h-7 items-center gap-1" role="meter" aria-label="Microphone input level" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(micLevel * 100)}>
              {Array.from({ length: 23 }, (_, index) => {
                const lit = index < Math.round(micLevel * 23);
                const height = 6 + ((index * 7) % 17);
                return <span key={index} className={`w-1 rounded-full transition-colors ${lit ? 'bg-cyan-500' : 'bg-slate-200 dark:bg-slate-700'}`} style={{ height }} />;
              })}
            </div>
            <div className="flex flex-wrap justify-center gap-2">
              <button type="button" onClick={() => void startCall()} disabled={callStatus !== 'Idle' || isConnecting} className="inline-flex min-h-11 items-center gap-2 bg-cyan-700 px-4 text-sm font-semibold text-white hover:bg-cyan-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-cyan-600 dark:hover:bg-cyan-500">
                {isConnecting ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Phone className="h-4 w-4" />}
                {isConnecting ? 'Connecting' : 'Start call'}
              </button>
              <button type="button" onClick={endCall} disabled={callStatus === 'Idle' && !isConnecting} className="inline-flex min-h-11 items-center gap-2 border border-slate-300 px-4 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800">
                <PhoneOff className="h-4 w-4" /> End call
              </button>
            </div>
            <p className="mt-3 text-center text-[11px] text-slate-500 dark:text-slate-400">Your browser will ask for microphone access when you start.</p>
          </div>

          <div className="flex flex-1 flex-col">
            <div className="flex items-center justify-between px-4 py-3">
              <h3 className="text-xs font-bold uppercase text-slate-600 dark:text-slate-300">Call transcript</h3>
              <span className="text-[11px] text-slate-400">Live</span>
            </div>
            <div className="max-h-[380px] min-h-[290px] flex-1 space-y-3 overflow-y-auto px-4 pb-4" aria-live="polite" aria-relevant="additions text">
              {transcript.length ? transcript.map(entry => (
                <article key={entry.id} className={`border-l-2 px-3 py-2 ${entry.speaker === 'Customer' ? 'border-slate-300 dark:border-slate-600' : 'border-cyan-500'}`}>
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <span className="text-xs font-bold text-slate-800 dark:text-slate-200">{entry.speaker}</span>
                    <time className="text-[10px] text-slate-400">{entry.time}</time>
                  </div>
                  <p className="text-sm leading-5 text-slate-700 dark:text-slate-300">{entry.text}</p>
                </article>
              )) : (
                <div className="flex min-h-[250px] flex-col items-center justify-center text-center text-slate-400">
                  <Mic className="mb-2 h-5 w-5" />
                  <p className="text-sm">Transcript will appear here</p>
                </div>
              )}
            </div>
          </div>
          <audio ref={remoteAudioRef} autoPlay className="sr-only" aria-label="Representative audio" />
        </section>

        <section aria-label="Operations panel" className="space-y-5">
          <div className="border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
            <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800">
              <div className="flex items-center gap-2">
                <PackageCheck className="h-4 w-4 text-cyan-700 dark:text-cyan-400" />
                <h2 className="text-sm font-bold text-slate-900 dark:text-white">Live inventory</h2>
              </div>
              <span className="text-[11px] text-slate-500">{dashboard.inventory.length} demo records</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[620px] text-left text-xs">
                <thead className="bg-slate-50 text-[10px] uppercase text-slate-500 dark:bg-slate-950/50 dark:text-slate-400">
                  <tr><th className="px-4 py-2.5 font-semibold">Part number / description</th><th className="px-3 py-2.5 font-semibold">On hand</th><th className="px-3 py-2.5 font-semibold">Condition</th><th className="px-3 py-2.5 text-right font-semibold">Unit price</th><th className="px-4 py-2.5 text-right font-semibold">Lead</th></tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {dashboard.inventory.map(item => (
                    <tr key={item.part_number} className="text-slate-700 dark:text-slate-300">
                      <td className="px-4 py-3"><div className="font-mono font-semibold text-slate-900 dark:text-slate-100">{item.part_number}</div><div className="mt-1 text-[11px] text-slate-500">{item.description}</div></td>
                      <td className="px-3 py-3 font-mono">{item.quantity}</td>
                      <td className="px-3 py-3"><span className="font-semibold">{item.condition_code}</span><span className="ml-1 text-[10px] text-slate-500">{item.condition_description}</span></td>
                      <td className="px-3 py-3 text-right font-mono">{formatUsd(item.unit_price)}</td>
                      <td className="px-4 py-3 text-right text-slate-500">{item.lead_time}</td>
                    </tr>
                  ))}
                  {!dashboard.inventory.length && <tr><td colSpan={5} className="px-4 py-8 text-center text-slate-500">Loading inventory...</td></tr>}
                </tbody>
              </table>
            </div>
          </div>

          <div className="border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
            <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800">
              <div className="flex items-center gap-2"><Clock3 className="h-4 w-4 text-cyan-700 dark:text-cyan-400" /><h2 className="text-sm font-bold text-slate-900 dark:text-white">Active RFQs &amp; orders</h2></div>
              <button type="button" onClick={() => void refreshDashboard()} title="Refresh operations data" aria-label="Refresh operations data" className="inline-flex h-9 w-9 items-center justify-center text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:hover:bg-slate-800 dark:hover:text-white"><RefreshCw className="h-4 w-4" /></button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-left text-xs">
                <thead className="bg-slate-50 text-[10px] uppercase text-slate-500 dark:bg-slate-950/50 dark:text-slate-400">
                  <tr><th className="px-4 py-2.5 font-semibold">RFQ ID</th><th className="px-3 py-2.5 font-semibold">Customer</th><th className="px-3 py-2.5 font-semibold">Part number</th><th className="px-4 py-2.5 font-semibold">Status</th></tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {dashboard.requests.map((request: VoiceRequest) => <RequestRow key={request.id} request={request} />)}
                  {!dashboard.requests.length && <tr><td colSpan={4} className="px-4 py-8 text-center text-slate-500">No active requests</td></tr>}
                </tbody>
              </table>
            </div>
          </div>

          <div className="border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
            <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800">
              <div className="flex items-center gap-2"><AlertTriangle className="h-4 w-4 text-amber-600 dark:text-amber-400" /><h2 className="text-sm font-bold text-slate-900 dark:text-white">Operator review queue</h2></div>
              <span className="min-w-6 rounded bg-amber-100 px-2 py-0.5 text-center text-xs font-bold text-amber-900 dark:bg-amber-950 dark:text-amber-200">{dashboard.human_queue.length}</span>
            </div>
            {dashboard.human_queue.length ? <div className="divide-y divide-slate-100 dark:divide-slate-800">
              {dashboard.human_queue.slice(0, 3).map((concern: VoiceConcern) => <div key={concern.id} className="flex items-start justify-between gap-3 px-4 py-3">
                <div><div className="text-xs font-semibold text-slate-800 dark:text-slate-200">{concern.issue_type.replace(/_/g, ' ')} · {concern.part_number || 'No part specified'}</div><p className="mt-1 text-xs text-slate-500">{concern.details}</p></div>
                <span className="shrink-0 text-[10px] font-semibold text-amber-700 dark:text-amber-300">{concern.status}</span>
              </div>)}
            </div> : <p className="px-4 py-4 text-xs text-slate-500">No operator reviews pending.</p>}
          </div>
        </section>
      </div>
    </div>
  );
};

const RequestRow: React.FC<{ request: VoiceRequest }> = ({ request }) => (
  <tr className="text-slate-700 dark:text-slate-300">
    <td className="whitespace-nowrap px-4 py-3 font-mono font-semibold text-slate-900 dark:text-slate-100">{request.id}</td>
    <td className="px-3 py-3">{request.customer_name}</td>
    <td className="whitespace-nowrap px-3 py-3 font-mono">{request.part_number || '-'}</td>
    <td className={`px-4 py-3 font-semibold ${statusTone(request.status)}`}>
      <span className="inline-flex items-center gap-1">{request.status}{request.review_notice && <ArrowUpRight className="h-3 w-3" aria-label={request.review_notice} />}</span>
    </td>
  </tr>
);