export type LanguageMode = 'ja' | 'en';
export type GameStatus = 'INIT' | 'PLAYING' | 'GUESSING' | 'RESULT' | 'ENDED';

export interface CaseSummary {
  title: string;
  location: string;
  time_window: string;
  summary: string;
  victim_name: string;
  found_state: string;
}

export interface CharacterPublic {
  id: string;
  name: string;
  role: string;
  traits: string[];
}

export interface UnlockedEvidence {
  id: string;
  name: string;
  detail: string;
  relevance: string;
}

export interface Message {
  id: number;
  question: string;
  answer_text: string;
  language_mode: LanguageMode;
  created_at: string;
}

export interface NewGameResponse {
  game_id: string;
  case_summary: CaseSummary;
  characters: CharacterPublic[];
  initial_state: GameStatus;
  remaining_questions: number;
  language_mode: LanguageMode;
}

export interface AskResponse {
  answer_text: string;
  remaining_questions: number;
  status: GameStatus;
  unlocked_evidence?: UnlockedEvidence | null;
}

export interface MatchResult {
  killer: boolean;
  motive: boolean;
  method: boolean;
  trick: boolean;
}

export interface GuessResponse {
  score: number;
  grade: 'S' | 'A' | 'B' | 'C';
  matches: MatchResult;
  feedback: string;
  contradictions: string[];
  weaknesses_top3: string[];
  solution_summary: string;
}

export interface GameStateResponse {
  game_id: string;
  status: GameStatus;
  remaining_questions: number;
  language_mode: LanguageMode;
  case_summary: CaseSummary;
  characters: CharacterPublic[];
  unlocked_evidence: UnlockedEvidence[];
  messages: Message[];
}

export interface ApiError {
  error_code: string;
  message: string;
  retryable: boolean;
  detail: Record<string, unknown>;
}
