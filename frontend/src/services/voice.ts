import axios from 'axios';
import { API_BASE } from './api';

export const voiceLanguages = [
  { code: 'en', label: 'English' },
  { code: 'es', label: 'Spanish' },
  { code: 'fr', label: 'French' },
  { code: 'de', label: 'German' },
  { code: 'pt', label: 'Portuguese' },
  { code: 'it', label: 'Italian' },
  { code: 'ja', label: 'Japanese' },
  { code: 'zh', label: 'Chinese' },
  { code: 'ko', label: 'Korean' },
  { code: 'nl', label: 'Dutch' },
  { code: 'ar', label: 'Arabic' },
  { code: 'hi', label: 'Hindi' },
] as const;

export type VoiceLanguage = typeof voiceLanguages[number]['code'];

export function getPreferredVoiceLanguage(): VoiceLanguage {
  try {
    const preference = localStorage.getItem('wt_voice_language');
    return voiceLanguages.find(language => language.code === preference)?.code ?? 'en';
  } catch {
    return 'en';
  }
}

export function setPreferredVoiceLanguage(language: VoiceLanguage): void {
  try {
    localStorage.setItem('wt_voice_language', language);
  } catch {
    // Keep the selection for this visit if browser storage is unavailable.
  }
}

export interface VoiceInventoryItem {
  part_number: string;
  description: string;
  quantity: number;
  condition_code: string;
  condition_description: string;
  unit_price: number;
  lead_time: string;
}

export interface VoiceRequest {
  id: string;
  customer_name: string;
  part_number: string;
  status: string;
  tracking_details?: string | null;
  review_notice?: string | null;
}

export interface VoiceConcern {
  id: string;
  issue_type: string;
  details: string;
  part_number: string;
  status: string;
  created_at: string;
}

export interface VoiceDashboard {
  inventory: VoiceInventoryItem[];
  requests: VoiceRequest[];
  human_queue: VoiceConcern[];
}

export const voiceService = {
  async createSession(language: VoiceLanguage = 'en'): Promise<{ client_secret: string; model: string }> {
    const response = await axios.post(`${API_BASE}/session`, { language });
    return response.data;
  },

  async getDashboard(): Promise<VoiceDashboard> {
    const response = await axios.get(`${API_BASE}/voice/dashboard`);
    return response.data;
  },

  async executeTool(name: string, arguments_: Record<string, unknown>): Promise<unknown> {
    const response = await axios.post(`${API_BASE}/voice/tools/${encodeURIComponent(name)}`, arguments_);
    return response.data;
  },
};