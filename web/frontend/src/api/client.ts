import axios from 'axios';
import type {
  StatusResponse,
  Position,
  Opportunity,
  ActivityLogEntry,
  BotSettings,
} from '../types';

const API_BASE = 'http://localhost:8000/api';

const api = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Bot Status
export async function getBotStatus(): Promise<StatusResponse> {
  const { data } = await api.get('/bot/status');
  return data;
}

export async function startBot(preset: string = 'balanced'): Promise<{ message: string }> {
  const { data } = await api.post('/bot/start', { preset });
  return data;
}

export async function stopBot(): Promise<{ message: string }> {
  const { data } = await api.post('/bot/stop');
  return data;
}

// Portfolio
export async function getPositions(): Promise<Position[]> {
  const { data } = await api.get('/portfolio/positions');
  return data;
}

// Strategies
export async function getOpportunities(
  strategy: string,
  params: {
    limit?: number;
    min_edge?: number;
    min_liquidity?: number;
    max_days?: number;
  } = {}
): Promise<Opportunity[]> {
  const { data } = await api.get(`/strategies/opportunities/${strategy}`, { params });
  return data;
}

// Activity
export async function getActivityLog(limit: number = 50): Promise<ActivityLogEntry[]> {
  const { data } = await api.get('/bot/activity', { params: { limit } });
  return data;
}

// Settings
export async function getSettings(): Promise<BotSettings> {
  const { data } = await api.get('/settings');
  return data;
}

export async function updateSettings(settings: Partial<BotSettings>): Promise<BotSettings> {
  const { data } = await api.post('/settings', settings);
  return data;
}
