import { useEffect, useRef, useState } from 'react';
import { voiceLanguages, voiceService, VoiceLanguage } from '../services/voice';

export type VoiceCallStatus = 'Idle' | 'Connecting' | 'Connected' | 'Checking Inventory' | 'Escalated';
export type VoiceTranscriptEntry = { id: string; speaker: 'Customer' | 'Representative'; text: string; time: string };

interface UseRealtimeVoiceOptions {
  onEscalated?: () => void;
}

export function useRealtimeVoice({ onEscalated }: UseRealtimeVoiceOptions = {}) {
  const [callStatus, setCallStatus] = useState<VoiceCallStatus>('Idle');
  const [isConnecting, setIsConnecting] = useState(false);
  const [micLevel, setMicLevel] = useState(0);
  const [transcript, setTranscript] = useState<VoiceTranscriptEntry[]>([]);
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
  const onEscalatedRef = useRef(onEscalated);

  useEffect(() => { onEscalatedRef.current = onEscalated; }, [onEscalated]);

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
    lastMicLevelRef.current = 0;
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

  const appendTranscript = (speaker: VoiceTranscriptEntry['speaker'], text: string) => {
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
    } else if (['response.audio_transcript.done', 'response.output_audio_transcript.done'].includes(event.type)) {
      appendTranscript('Representative', event.transcript || '');
    } else if (event.type === 'response.output_text.done') {
      appendTranscript('Representative', event.text || '');
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
          onEscalatedRef.current?.();
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
        setErrorMessage('The operations lookup failed. Your request was not confirmed.');
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
    } else if (event.type === 'error' || event.type === 'invalid_request_error') {
      setErrorMessage(event.error?.message || event.message || 'The voice connection reported an error.');
    }
  };

  const startCall = async (language: VoiceLanguage) => {
    if (!navigator.mediaDevices?.getUserMedia) {
      setErrorMessage('Microphone access is unavailable. Use a secure connection and try again.');
      return;
    }
    const generation = ++generationRef.current;
    setErrorMessage('');
    setTranscript([]);
    escalatedRef.current = false;
    setCallStatus('Connecting');
    setIsConnecting(true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (generation !== generationRef.current) {
        stream.getTracks().forEach(track => track.stop());
        return;
      }
      localStreamRef.current = stream;
      const session = await voiceService.createSession(language);
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
          setErrorMessage('The call connection failed. Check your network and start another call.');
          releaseCallResources();
          setCallStatus('Idle');
          setIsConnecting(false);
        }
      };

      const channel = peer.createDataChannel('oai-events');
      channelRef.current = channel;
      channel.onopen = () => {
        if (generation !== generationRef.current) return;
        setCallStatus('Connected');
        setIsConnecting(false);
        const languageLabel = voiceLanguages.find(item => item.code === language)?.label || 'English';
        const greetingInstructions = language === 'es'
          ? 'Say exactly: "Hola, soy Camila, la asistente de voz con IA de Winged Tycoons. ¿En qué puedo ayudarte hoy?"'
          : `Greet the customer briefly in ${languageLabel}. Introduce yourself as Camila, Winged Tycoons' AI voice assistant, and ask how you can help.`;
        channel.send(JSON.stringify({
          type: 'response.create',
          response: { instructions: greetingInstructions },
        }));
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
      if (!answerResponse.ok) throw new Error('The voice service could not accept the call.');
      if (generation !== generationRef.current) return;
      await peer.setRemoteDescription({ type: 'answer', sdp: await answerResponse.text() });
    } catch (error) {
      releaseCallResources();
      setCallStatus('Idle');
      const message = error instanceof Error ? error.message : 'Unable to start the call.';
      setErrorMessage(message.toLowerCase().includes('permission') || message.toLowerCase().includes('denied')
        ? 'Microphone permission was denied. Allow microphone access in your browser to call us.'
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

  return { callStatus, isConnecting, micLevel, transcript, errorMessage, setErrorMessage, remoteAudioRef, startCall, endCall };
}