import { FormEvent, useEffect, useMemo, useState } from 'react';

import {
  ApiRequestError,
  askQuestion,
  createGame,
  endGame,
  getGame,
  patchLanguage,
  readyToGuess,
  submitGuess,
} from './api';
import { t } from './i18n';
import type { GameStateResponse, GuessResponse, LanguageMode } from './types';

type Screen = 'title' | 'game' | 'result';

interface GuessForm {
  killer: string;
  motive: string;
  method: string;
  trick: string;
  reasoning: string;
}

function memoKey(gameId: string) {
  return `mystery:memo:${gameId}`;
}

const emptyGuess: GuessForm = {
  killer: '',
  motive: '',
  method: '',
  trick: '',
  reasoning: '',
};

export default function App() {
  const [screen, setScreen] = useState<Screen>('title');
  const [languageMode, setLanguageMode] = useState<LanguageMode>('ja');
  const [gameId, setGameId] = useState<string | null>(null);
  const [gameState, setGameState] = useState<GameStateResponse | null>(null);
  const [result, setResult] = useState<GuessResponse | null>(null);
  const [question, setQuestion] = useState('');
  const [target, setTarget] = useState('');
  const [guessForm, setGuessForm] = useState<GuessForm>(emptyGuess);
  const [memo, setMemo] = useState('');
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  const text = useMemo(() => t(languageMode), [languageMode]);

  useEffect(() => {
    if (!gameId) {
      setMemo('');
      return;
    }
    const saved = localStorage.getItem(memoKey(gameId)) ?? '';
    setMemo(saved);
  }, [gameId]);

  useEffect(() => {
    if (!gameId) {
      return;
    }
    localStorage.setItem(memoKey(gameId), memo);
  }, [gameId, memo]);

  const handleStartGame = async () => {
    setLoading(true);
    setErrorMessage('');
    try {
      const created = await createGame(languageMode);
      const state = await getGame(created.game_id);
      setGameId(created.game_id);
      setGameState(state);
      setLanguageMode(state.language_mode);
      setResult(null);
      setQuestion('');
      setTarget('');
      setGuessForm({ ...emptyGuess, killer: state.characters[0]?.name ?? '' });
      setScreen('game');
    } catch (error) {
      setErrorMessage(resolveError(error));
    } finally {
      setLoading(false);
    }
  };

  const handleLanguageChange = async (mode: LanguageMode) => {
    setLanguageMode(mode);
    if (!gameId) {
      return;
    }
    try {
      await patchLanguage(gameId, mode);
      const refreshed = await getGame(gameId);
      setGameState(refreshed);
    } catch (error) {
      setErrorMessage(resolveError(error));
    }
  };

  const handleAsk = async (event: FormEvent) => {
    event.preventDefault();
    if (!gameId || !question.trim()) {
      return;
    }

    setLoading(true);
    setErrorMessage('');
    try {
      await askQuestion(gameId, question.trim(), target.trim() || undefined);
      const refreshed = await getGame(gameId);
      setGameState(refreshed);
      setQuestion('');
    } catch (error) {
      setErrorMessage(resolveError(error));
    } finally {
      setLoading(false);
    }
  };

  const handleMoveToGuess = async () => {
    if (!gameId) {
      return;
    }
    setLoading(true);
    setErrorMessage('');
    try {
      await readyToGuess(gameId);
      const refreshed = await getGame(gameId);
      setGameState(refreshed);
    } catch (error) {
      setErrorMessage(resolveError(error));
    } finally {
      setLoading(false);
    }
  };

  const handleSubmitGuess = async (event: FormEvent) => {
    event.preventDefault();
    if (!gameId) {
      return;
    }
    setLoading(true);
    setErrorMessage('');
    try {
      const response = await submitGuess(gameId, guessForm);
      setResult(response);
      const refreshed = await getGame(gameId);
      setGameState(refreshed);
      setScreen('result');
    } catch (error) {
      setErrorMessage(resolveError(error));
    } finally {
      setLoading(false);
    }
  };

  const handlePlayAgain = async () => {
    if (gameId) {
      try {
        await endGame(gameId);
      } catch {
        // Continue to restart even if end API fails.
      }
    }
    setGameId(null);
    setGameState(null);
    setResult(null);
    setGuessForm({ ...emptyGuess });
    setScreen('title');
    await handleStartGame();
  };

  const navigateTo = (next: Screen) => {
    if (next === 'game' && !gameState) {
      return;
    }
    if (next === 'result' && !result) {
      return;
    }
    setScreen(next);
  };

  const isGuessing = gameState?.status === 'GUESSING';

  const currentTask = useMemo(() => {
    if (screen === 'title') {
      return {
        main: text.taskStart,
        sub: text.taskStartDetail,
      };
    }
    if (screen === 'game' && gameState?.status === 'PLAYING') {
      return {
        main: text.taskAsk,
        sub: '',
      };
    }
    if (screen === 'game' && gameState?.status === 'GUESSING') {
      return {
        main: text.taskGuess,
        sub: '',
      };
    }
    return {
      main: text.taskResult,
      sub: '',
    };
  }, [screen, gameState?.status, text]);

  return (
    <div className="app-shell">
      <header className="hero">
        <div>
          <p className="eyebrow">Mystery Visual Novel</p>
          <h1>{text.appTitle}</h1>
          <p className="subtitle">{text.subtitle}</p>
        </div>
        <select
          className="language-toggle"
          value={languageMode}
          onChange={(event) => handleLanguageChange(event.target.value as LanguageMode)}
        >
          <option value="ja">🇯🇵 日本語</option>
          <option value="en">🇺🇸 English</option>
        </select>
      </header>

      <nav className="progress-nav" aria-label={text.navLabel}>
        <button
          className={`nav-btn ${screen === 'title' ? 'active' : ''}`}
          type="button"
          onClick={() => navigateTo('title')}
        >
          {text.navStart}
        </button>
        <button
          className={`nav-btn ${screen === 'game' ? 'active' : ''}`}
          type="button"
          onClick={() => navigateTo('game')}
          disabled={!gameState}
        >
          {text.navGame}
        </button>
        <button
          className={`nav-btn ${screen === 'result' ? 'active' : ''}`}
          type="button"
          onClick={() => navigateTo('result')}
          disabled={!result}
        >
          {text.navResult}
        </button>
      </nav>

      <section className="guide-card">
        <h2>{text.currentTaskTitle}</h2>
        <p>{currentTask.main}</p>
        {currentTask.sub && <p className="guide-sub">{currentTask.sub}</p>}
      </section>

      {errorMessage && <div className="error-box">{errorMessage}</div>}
      {loading && <div className="loading">{text.loading}</div>}

      {screen === 'title' && (
        <main className="panel title-panel">
          <h2>{text.rulesTitle}</h2>
          <p>{text.rulesBody}</p>

          <h3>{text.quickStartTitle}</h3>
          <ol className="quick-steps">
            <li>{text.quickStep1}</li>
            <li>{text.quickStep2}</li>
            <li>{text.quickStep3}</li>
          </ol>

          <button className="primary-btn" onClick={handleStartGame}>
            {text.startGame}
          </button>
        </main>
      )}

      {screen === 'game' && gameState && (
        <main className="game-layout">
          <section className="panel chat-panel" id="investigation">
            <div className="row-between">
              <h2>{text.chatTitle}</h2>
              <span className="badge">
                {text.remainingQuestions}: {gameState.remaining_questions}
              </span>
            </div>

            <div className="in-page-nav">
              <span>{text.gameNavTitle}</span>
              <a href="#investigation">{text.goInvestigation}</a>
              <a href="#casefile">{text.goCase}</a>
              <a href="#deduction">{text.goGuess}</a>
            </div>

            <div className="chat-log">
              {gameState.messages.length === 0 && <p className="empty-log">{text.noMessages}</p>}
              {gameState.messages.map((message) => (
                <article key={message.id} className="chat-item">
                  <p className="chat-q">Q: {message.question}</p>
                  <p className="chat-a">A: {message.answer_text}</p>
                </article>
              ))}
            </div>

            <form className="ask-form" onSubmit={handleAsk}>
              <input
                type="text"
                placeholder={text.askPlaceholder}
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                disabled={gameState.status !== 'PLAYING'}
              />
              <input
                type="text"
                placeholder={text.askTarget}
                value={target}
                onChange={(event) => setTarget(event.target.value)}
                disabled={gameState.status !== 'PLAYING'}
              />
              <button className="primary-btn" type="submit" disabled={gameState.status !== 'PLAYING'}>
                {text.askButton}
              </button>
            </form>

            {gameState.status === 'PLAYING' && (
              <button className="secondary-btn" onClick={handleMoveToGuess}>
                {text.toGuess}
              </button>
            )}

            {isGuessing && <p className="notice">{text.stateGuessing}</p>}

            {isGuessing && (
              <form className="guess-form" id="deduction" onSubmit={handleSubmitGuess}>
                <h3>{text.guessTitle}</h3>
                <select
                  value={guessForm.killer}
                  onChange={(event) => setGuessForm({ ...guessForm, killer: event.target.value })}
                  required
                >
                  {gameState.characters.map((character) => (
                    <option value={character.name} key={character.id}>
                      {character.name}
                    </option>
                  ))}
                </select>
                <textarea
                  placeholder={text.motive}
                  value={guessForm.motive}
                  onChange={(event) => setGuessForm({ ...guessForm, motive: event.target.value })}
                  required
                />
                <textarea
                  placeholder={text.method}
                  value={guessForm.method}
                  onChange={(event) => setGuessForm({ ...guessForm, method: event.target.value })}
                  required
                />
                <textarea
                  placeholder={text.trick}
                  value={guessForm.trick}
                  onChange={(event) => setGuessForm({ ...guessForm, trick: event.target.value })}
                  required
                />
                <textarea
                  placeholder={text.reasoning}
                  value={guessForm.reasoning}
                  onChange={(event) => setGuessForm({ ...guessForm, reasoning: event.target.value })}
                  required
                />
                <button className="primary-btn" type="submit">
                  {text.submitGuess}
                </button>
              </form>
            )}
          </section>

          <aside className="panel side-panel" id="casefile">
            <h2>{text.caseTitle}</h2>
            <p>{gameState.case_summary.summary}</p>
            <p>
              {gameState.case_summary.location} / {gameState.case_summary.time_window}
            </p>
            <p>
              {gameState.case_summary.victim_name} - {gameState.case_summary.found_state}
            </p>

            <h3>{text.charactersTitle}</h3>
            <ul className="character-list">
              {gameState.characters.map((character) => (
                <li key={character.id} className="character-item">
                  <strong>{character.name}</strong>
                  <span className="character-role">（{character.role}）</span>
                </li>
              ))}
            </ul>

            <h3>{text.evidenceTitle}</h3>
            {gameState.unlocked_evidence.length === 0 && <p className="empty-evidence">{text.noEvidence}</p>}
            <ul className="evidence-list">
              {gameState.unlocked_evidence.map((evidence) => (
                <li key={evidence.id} className="evidence-item">
                  <strong>{evidence.name}</strong>
                  <p>{evidence.detail}</p>
                </li>
              ))}
            </ul>

            <h3>{text.memoTitle}</h3>
            <textarea
              className="memo"
              placeholder={text.memoPlaceholder}
              value={memo}
              onChange={(event) => setMemo(event.target.value)}
            />
          </aside>
        </main>
      )}

      {screen === 'result' && result && (
        <main className="panel result-panel">
          <h2>{text.resultTitle}</h2>
          <p>
            {text.score}: <strong>{result.score}</strong>
          </p>
          <p>
            {text.grade}: <strong className="grade-display">{result.grade}</strong>
          </p>

          <h3>{text.matchTitle}</h3>
          <ul className="match-list">
            <li>
              {text.killer}: {result.matches.killer ? '✅' : '❌'}
            </li>
            <li>
              {text.motive}: {result.matches.motive ? '✅' : '❌'}
            </li>
            <li>
              {text.method}: {result.matches.method ? '✅' : '❌'}
            </li>
            <li>
              {text.trick}: {result.matches.trick ? '✅' : '❌'}
            </li>
          </ul>

          <h3>{text.feedback}</h3>
          <p>{result.feedback}</p>

          <h3>{text.contradictions}</h3>
          <ul>
            {result.contradictions.length === 0 && <li>なし</li>}
            {result.contradictions.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>

          <h3>{text.weaknesses}</h3>
          <ol className="weakness-list">
            {result.weaknesses_top3.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ol>

          <h3>{text.solution}</h3>
          <p className="solution-text">{result.solution_summary}</p>

          <button className="primary-btn" onClick={handlePlayAgain}>
            {text.playAgain}
          </button>
        </main>
      )}
    </div>
  );
}

function resolveError(error: unknown): string {
  if (error instanceof ApiRequestError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return 'Unexpected error';
}
