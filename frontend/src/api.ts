import type {
  AskResponse,
  GameStateResponse,
  GuessResponse,
  LanguageMode,
  NewGameResponse,
} from './types';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

class ApiRequestError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(options?.headers ?? {}),
    },
    ...options,
  });

  if (!response.ok) {
    const fallback = `Request failed with status ${response.status}`;
    let message = fallback;
    try {
      const data = (await response.json()) as { message?: string };
      message = data.message ?? fallback;
    } catch {
      // Keep fallback message when body is not JSON.
    }
    throw new ApiRequestError(message, response.status);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export { ApiRequestError };

export function createGame(language_mode: LanguageMode): Promise<NewGameResponse> {
  return apiFetch('/api/game/new', {
    method: 'POST',
    body: JSON.stringify({ language_mode }),
  });
}

export function getGame(gameId: string): Promise<GameStateResponse> {
  return apiFetch(`/api/game/${gameId}`, { method: 'GET' });
}

export function askQuestion(gameId: string, question: string, target?: string): Promise<AskResponse> {
  return apiFetch(`/api/game/${gameId}/ask`, {
    method: 'POST',
    body: JSON.stringify({ question, target: target || null }),
  });
}

export function patchLanguage(gameId: string, language_mode: LanguageMode) {
  return apiFetch(`/api/game/${gameId}/language`, {
    method: 'PATCH',
    body: JSON.stringify({ language_mode }),
  });
}

export function readyToGuess(gameId: string) {
  return apiFetch(`/api/game/${gameId}/ready-to-guess`, {
    method: 'POST',
  });
}

export function submitGuess(
  gameId: string,
  payload: {
    killer: string;
    motive: string;
    method: string;
    trick: string;
    reasoning: string;
  },
): Promise<GuessResponse> {
  return apiFetch(`/api/game/${gameId}/guess`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function endGame(gameId: string) {
  return apiFetch(`/api/game/${gameId}/end`, {
    method: 'POST',
  });
}
