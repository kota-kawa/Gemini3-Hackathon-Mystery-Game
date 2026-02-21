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
type ReasoningStyle = 'evidence' | 'timeline' | 'elimination';
type UiMode = 'dialogue' | 'input' | 'log' | 'notebook' | 'case' | 'guessing';

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

function questionTemplatesFor(mode: LanguageMode): string[] {
  if (mode === 'ja') {
    return [
      '最後に被害者を見たのは誰？',
      '事件当時、あなたはどこにいた？',
      '被害者と揉めていた人物はいる？',
      'この証拠について心当たりはある？',
      '犯行時刻に不自然な行動をした人は？',
      'アリバイを証明できる人はいる？',
      '部屋の鍵を扱える人物は誰？',
      '被害者が残した手がかりを知っている？',
    ];
  }

  return [
    'Who saw the victim last?',
    'Where were you at the time of the incident?',
    'Was anyone in conflict with the victim?',
    'Do you recognize this piece of evidence?',
    'Who behaved suspiciously around the crime time?',
    'Can anyone confirm your alibi?',
    'Who could access the room key?',
    'Do you know any clue the victim left behind?',
  ];
}

function guessChoiceOptionsFor(mode: LanguageMode): { motive: string[]; method: string[]; trick: string[] } {
  if (mode === 'ja') {
    return {
      motive: ['金銭トラブル', '復讐', '秘密の隠蔽', '嫉妬・人間関係', '事故の口封じ', '脅迫への対処', '不明'],
      method: ['毒物を使った殺害', '鈍器での殺害', '刃物での殺害', '絞殺', '転落を装った殺害', '設備トラブルを利用', '不明'],
      trick: ['密室トリック', 'アリバイ工作', '証拠改ざん', '犯行時刻の偽装', '共犯者との連携', '事故に見せかけた工作', '不明'],
    };
  }

  return {
    motive: ['Money dispute', 'Revenge', 'Covering up a secret', 'Jealousy / personal conflict', 'Silencing an accident', 'Responding to blackmail', 'Unknown'],
    method: ['Poisoning', 'Blunt-force attack', 'Stabbing', 'Strangulation', 'Staged as a fall', 'Using facility malfunction', 'Unknown'],
    trick: ['Locked-room trick', 'Alibi fabrication', 'Evidence tampering', 'Faked timeline', 'Accomplice coordination', 'Staged as an accident', 'Unknown'],
  };
}

function buildReasoningDraft(mode: LanguageMode, style: ReasoningStyle, guess: GuessForm): string {
  const killer = guess.killer || (mode === 'ja' ? '犯人候補' : 'the culprit candidate');
  const motive = guess.motive || (mode === 'ja' ? '不明な動機' : 'an unclear motive');
  const method = guess.method || (mode === 'ja' ? '不明な手口' : 'an unclear method');
  const trick = guess.trick || (mode === 'ja' ? '不明なトリック' : 'an unclear trick');

  if (mode === 'ja') {
    if (style === 'timeline') {
      return `時系列で整理すると、${killer}が${motive}を背景に${method}を実行し、${trick}で発覚を遅らせたと考えられる。`;
    }
    if (style === 'elimination') {
      return `他の人物のアリバイや証言との矛盾を消去すると、${killer}が最も有力で、動機は${motive}、犯行手口は${method}、そして${trick}が使われた可能性が高い。`;
    }
    return `証拠の整合性から、${killer}が${motive}のために${method}を行い、${trick}によって痕跡を隠したと判断した。`;
  }

  if (style === 'timeline') {
    return `Following the timeline, ${killer} likely acted from ${motive}, used ${method}, and delayed discovery through ${trick}.`;
  }
  if (style === 'elimination') {
    return `By eliminating suspects with stronger alibis and fewer contradictions, ${killer} remains most plausible, with ${motive} as motive, ${method} as method, and ${trick} as the key trick.`;
  }
  return `Based on evidence consistency, ${killer} likely acted from ${motive}, carried out ${method}, and concealed the crime through ${trick}.`;
}

export default function App() {
  const [screen, setScreen] = useState<Screen>('title');
  const [languageMode, setLanguageMode] = useState<LanguageMode>('ja');
  const [gameId, setGameId] = useState<string | null>(null);
  const [gameState, setGameState] = useState<GameStateResponse | null>(null);
  const [result, setResult] = useState<GuessResponse | null>(null);
  const [question, setQuestion] = useState('');
  const [selectedQuestionTemplate, setSelectedQuestionTemplate] = useState('');
  const [target, setTarget] = useState('');
  const [guessForm, setGuessForm] = useState<GuessForm>(emptyGuess);
  const [reasoningStyle, setReasoningStyle] = useState<ReasoningStyle>('evidence');
  const [memo, setMemo] = useState('');
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [uiMode, setUiMode] = useState<UiMode>('dialogue');
  const [showBriefing, setShowBriefing] = useState(false);
  const [isGuessFinalized, setIsGuessFinalized] = useState(false);

  const text = useMemo(() => t(languageMode), [languageMode]);
  const questionTemplates = useMemo(() => questionTemplatesFor(languageMode), [languageMode]);
  const guessChoiceOptions = useMemo(() => guessChoiceOptionsFor(languageMode), [languageMode]);

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

  useEffect(() => {
    if (gameState?.status === 'GUESSING') {
      setUiMode('guessing');
    } else if (screen === 'game') {
      setUiMode('dialogue');
    }
  }, [gameState?.status, screen]);

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
      setSelectedQuestionTemplate('');
      setTarget('');
      setReasoningStyle('evidence');
      setGuessForm({ ...emptyGuess, killer: state.characters[0]?.name ?? '' });
      setIsGuessFinalized(false);
      setUiMode('dialogue');
      setShowBriefing(true);
      setScreen('game');
    } catch (error) {
      setErrorMessage(resolveError(error));
    } finally {
      setLoading(false);
    }
  };

  const handleLanguageChange = async (mode: LanguageMode) => {
    setLanguageMode(mode);
    setSelectedQuestionTemplate('');
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
    if (!gameId || !question.trim() || showBriefing || isGuessFinalized || gameState?.status !== 'PLAYING') {
      return;
    }

    setLoading(true);
    setErrorMessage('');
    try {
      await askQuestion(gameId, question.trim(), target.trim() || undefined);
      const refreshed = await getGame(gameId);
      setGameState(refreshed);
      setQuestion('');
      setSelectedQuestionTemplate('');
      setUiMode('dialogue');
    } catch (error) {
      setErrorMessage(resolveError(error));
    } finally {
      setLoading(false);
    }
  };

  const handleOpenGuess = () => {
    if (showBriefing) {
      return;
    }
    setUiMode('guessing');
  };

  const handleFinalizeGuess = async () => {
    if (!gameId || isGuessFinalized) {
      return;
    }
    setLoading(true);
    setErrorMessage('');
    try {
      if (gameState?.status === 'PLAYING') {
        await readyToGuess(gameId);
      }
      setIsGuessFinalized(true);
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
    if (!gameId || !isGuessFinalized) {
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

  const handleAutofillReasoning = () => {
    setGuessForm((current) => ({
      ...current,
      reasoning: buildReasoningDraft(languageMode, reasoningStyle, current),
    }));
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
    setQuestion('');
    setSelectedQuestionTemplate('');
    setTarget('');
    setReasoningStyle('evidence');
    setGuessForm({ ...emptyGuess });
    setIsGuessFinalized(false);
    setShowBriefing(false);
    setUiMode('dialogue');
    setScreen('title');
    await handleStartGame();
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

  const isImmersive = screen !== 'title';
  const flowStep = useMemo(() => {
    if (screen === 'title') {
      return 0;
    }
    if (screen === 'game' && gameState?.status === 'PLAYING') {
      return 1;
    }
    if (screen === 'game' && gameState?.status === 'GUESSING') {
      return 2;
    }
    return 3;
  }, [screen, gameState?.status]);

  const storyFlow = [text.navStart, text.navGame, text.navGuess, text.navResult];

  // Helper to get latest message content
  const latestMessage = useMemo(() => {
    if (!gameState || gameState.messages.length === 0) {
      return null;
    }
    return gameState.messages[gameState.messages.length - 1];
  }, [gameState]);

  const briefingCaseText = useMemo(() => {
    if (!gameState) {
      return '';
    }
    const summary = gameState.case_summary;
    if (languageMode === 'ja') {
      return `舞台は${summary.location}、時間帯は${summary.time_window}です。被害者は${summary.victim_name}。${summary.summary} 発見時の状況は「${summary.found_state}」。`;
    }
    return `The case takes place at ${summary.location} during ${summary.time_window}. The victim is ${summary.victim_name}. ${summary.summary} The victim was found ${summary.found_state}.`;
  }, [gameState, languageMode]);

  const briefingHowToText = useMemo(() => {
    if (!gameState) {
      return '';
    }
    if (languageMode === 'ja') {
      return `質問は合計${gameState.remaining_questions}回まで可能です。「質問」で聞き込み、「ログ」と「ノート」で情報を整理し、準備ができたら「推理」で結論を提出してください。`;
    }
    return `You can ask up to ${gameState.remaining_questions} questions. Use "Ask" to interrogate, review "Log" and "Notebook", then submit your theory from "Guess".`;
  }, [gameState, languageMode]);

  return (
    <div className={`app-shell ${isImmersive ? 'app-shell-immersive' : ''}`}>
      {screen === 'title' && (
        <>
          <header className="hero hero-title">
            <div className="hero-main">
              <p className="eyebrow">Mystery Visual Novel</p>
              <h1>{text.appTitle}</h1>
              <p className="subtitle">{text.subtitle}</p>
            </div>
            <div className="hero-tools">
              <select
                className="language-toggle"
                value={languageMode}
                onChange={(event) => handleLanguageChange(event.target.value as LanguageMode)}
              >
                <option value="ja">🇯🇵 日本語</option>
                <option value="en">🇺🇸 English</option>
              </select>
            </div>
          </header>

          <section className="guide-card title-guide-card">
            <h2>{text.currentTaskTitle}</h2>
            <p>{currentTask.main}</p>
            {currentTask.sub && <p className="guide-sub">{currentTask.sub}</p>}
          </section>

          {errorMessage && <div className="error-box">{errorMessage}</div>}
          {loading && <div className="loading">{text.loading}</div>}

          <section className="story-flow story-flow-title" aria-label={text.navLabel}>
            {storyFlow.map((label, index) => (
              <div
                key={label}
                className={`flow-node ${index < flowStep ? 'done' : ''} ${index === flowStep ? 'active' : ''}`}
              >
                <span className="flow-index">{index + 1}</span>
                <span>{label}</span>
              </div>
            ))}
          </section>

          <main className="title-grid">
            <section className="panel title-panel">
              <h2>{text.rulesTitle}</h2>
              <p className="title-rules-body">{text.rulesBody}</p>
              <button className="primary-btn title-start-btn" onClick={handleStartGame}>
                {text.startGame}
              </button>
            </section>

            <aside className="panel title-panel title-side-panel">
              <h3>{text.quickStartTitle}</h3>
              <ol className="quick-steps">
                <li>{text.quickStep1}</li>
                <li>{text.quickStep2}</li>
                <li>{text.quickStep3}</li>
              </ol>
              <span className="badge title-badge">{text.remainingQuestions}: 12</span>
            </aside>
          </main>
        </>
      )}

      {isImmersive && screen !== 'game' && (
        <>
          <header className="novel-topbar">
            <div>
              <p className="eyebrow">Mystery Visual Novel</p>
              <h1>{text.appTitle}</h1>
              <p className="subtitle">{text.subtitle}</p>
            </div>
            <div className="novel-topbar-right">
              <select
                className="language-toggle"
                value={languageMode}
                onChange={(event) => handleLanguageChange(event.target.value as LanguageMode)}
              >
                <option value="ja">🇯🇵 日本語</option>
                <option value="en">🇺🇸 English</option>
              </select>
            </div>
          </header>

          <section className="story-flow" aria-label={text.navLabel}>
            {storyFlow.map((label, index) => (
              <div
                key={label}
                className={`flow-node ${index < flowStep ? 'done' : ''} ${index === flowStep ? 'active' : ''}`}
              >
                <span className="flow-index">{index + 1}</span>
                <span>{label}</span>
              </div>
            ))}
          </section>

          <section className="guide-card guide-card-immersive">
            <h2>{text.currentTaskTitle}</h2>
            <p>{currentTask.main}</p>
            {currentTask.sub && <p className="guide-sub">{currentTask.sub}</p>}
          </section>
        </>
      )}

      {screen === 'game' && errorMessage && <div className="error-box vn-error">{errorMessage}</div>}
      {screen === 'game' && loading && <div className="loading vn-loading">{text.loading}</div>}

      {screen === 'game' && gameState && (
        <div className="vn-container">
          {/* Top Left Badge */}
          <div className="vn-date-badge">
            <span className="vn-date-text">{gameState.case_summary.time_window.split(' ')[0]}</span>
            <span className="vn-location-text">{gameState.case_summary.location}</span>
          </div>

          <div className="vn-top-right">
             <span className="badge">
               {text.remainingQuestions}: {gameState.remaining_questions}
             </span>
             <select
                className="language-toggle"
                value={languageMode}
                onChange={(event) => handleLanguageChange(event.target.value as LanguageMode)}
              >
                <option value="ja">🇯🇵 日本語</option>
                <option value="en">🇺🇸 English</option>
              </select>
          </div>

          {/* Dialogue Box Area */}
          <div className="vn-textbox">
            {uiMode === 'dialogue' && (
               <div className="vn-dialogue-content">
                  <h3 className="vn-speaker-name">{text.gmName}</h3>
                  {showBriefing ? (
                    <div className="vn-briefing">
                      <p className="vn-briefing-title">{text.briefingTitle}</p>
                      <section className="vn-briefing-section">
                        <p className="vn-briefing-label">{text.briefingCaseLabel}</p>
                        <p className="vn-briefing-text">{briefingCaseText}</p>
                      </section>
                      <section className="vn-briefing-section">
                        <p className="vn-briefing-label">{text.briefingHowToLabel}</p>
                        <p className="vn-briefing-text">{briefingHowToText}</p>
                      </section>
                      <button className="primary-btn vn-briefing-btn" onClick={() => setShowBriefing(false)}>
                        {text.briefingAction}
                      </button>
                    </div>
                  ) : (
                    <p className="vn-dialogue-text">
                      {latestMessage ? latestMessage.answer_text : gameState.case_summary.summary}
                    </p>
                  )}
               </div>
            )}

            {uiMode === 'input' && (
              <form className="vn-input-form" onSubmit={handleAsk}>
                <div className="vn-input-row">
                    <input
                        type="text"
                        className="vn-input-field"
                        placeholder={text.askPlaceholder}
                        value={question}
                        onChange={(event) => setQuestion(event.target.value)}
                        autoFocus
                    />
                    <select
                        className="vn-target-select"
                        value={target}
                        onChange={(event) => setTarget(event.target.value)}
                    >
                        <option value="">{text.askTargetAnyone}</option>
                        {gameState.characters.map((character) => (
                          <option value={character.name} key={character.id}>
                            {character.name}
                          </option>
                        ))}
                    </select>
                    <button className="primary-btn vn-ask-btn" type="submit">
                        {text.askButton}
                    </button>
                </div>
                <div className="quick-option-row">
                    {questionTemplates.slice(0, 3).map((template) => (
                        <button
                        type="button"
                        key={template}
                        className="chip-btn"
                        onClick={() => {
                            setQuestion(template);
                        }}
                        >
                        {template}
                        </button>
                    ))}
                </div>
                <button type="button" className="secondary-btn vn-cancel-btn" onClick={() => setUiMode('dialogue')}>
                    {text.cancel}
                </button>
              </form>
            )}

            {/* Menu Bar */}
            <div className="vn-menu-bar">
                <div className="vn-menu-group">
                  <button
                    className="vn-menu-btn"
                    onClick={() => setUiMode('case')}
                    disabled={showBriefing || uiMode === 'guessing'}
                  >
                    {text.briefingCaseLabel}
                  </button>
                </div>
                <div className="vn-menu-group">
                <button
                  className="vn-menu-btn"
                  onClick={() => setUiMode('input')}
                  disabled={showBriefing || isGuessing || uiMode === 'guessing' || uiMode === 'input'}
                >
                    {text.menuAsk}
                </button>
                <button className="vn-menu-btn" onClick={() => setUiMode('log')} disabled={showBriefing || uiMode === 'guessing'}>
                    {text.menuLog}
                </button>
                <button className="vn-menu-btn" onClick={() => setUiMode('notebook')} disabled={showBriefing || uiMode === 'guessing'}>
                    {text.menuNotebook}
                </button>
                <button
                  className="vn-menu-btn warning"
                  onClick={handleOpenGuess}
                  disabled={showBriefing || uiMode === 'guessing'}
                >
                    {text.menuGuess}
                </button>
                </div>
            </div>
          </div>

          {/* Overlays */}
          {uiMode === 'case' && (
            <div className="vn-overlay">
                <div className="vn-overlay-content vn-case-overlay-content">
                    <div className="row-between">
                        <h2>{text.briefingCaseLabel}</h2>
                        <button className="secondary-btn" onClick={() => setUiMode('dialogue')}>{text.close}</button>
                    </div>
                    <div className="vn-case-summary-panel">
                      <p className="vn-case-summary-text">{briefingCaseText}</p>
                    </div>
                </div>
            </div>
          )}

          {uiMode === 'log' && (
            <div className="vn-overlay">
                <div className="vn-overlay-content">
                    <div className="row-between">
                        <h2>{text.chatTitle}</h2>
                        <button className="secondary-btn" onClick={() => setUiMode('dialogue')}>{text.close}</button>
                    </div>
                    <div className="chat-log full-height">
                        {gameState.messages.map((message) => (
                          <article key={message.id} className="chat-item">
                            <p className="chat-q">{text.chatQuestionPrefix} {message.question}</p>
                            <p className="chat-a">{text.chatAnswerPrefix} {message.answer_text}</p>
                          </article>
                        ))}
                    </div>
                </div>
            </div>
          )}

          {uiMode === 'notebook' && (
            <div className="vn-overlay">
                <div className="vn-overlay-content">
                    <div className="row-between">
                        <h2>{text.caseTitle}</h2>
                        <button className="secondary-btn" onClick={() => setUiMode('dialogue')}>{text.close}</button>
                    </div>
                    <div className="vn-notebook-grid">
                        <div className="vn-col">
                            <h3>{text.charactersTitle}</h3>
                            <ul className="character-list">
                                {gameState.characters.map((character) => (
                                <li key={character.id} className="character-item">
                                    <strong>{character.name}</strong>
                                    <span className="character-role">（{character.role}）</span>
                                </li>
                                ))}
                            </ul>
                        </div>
                        <div className="vn-col">
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
                        </div>
                        <div className="vn-col">
                            <h3>{text.memoTitle}</h3>
                            <textarea
                                className="memo"
                                placeholder={text.memoPlaceholder}
                                value={memo}
                                onChange={(event) => setMemo(event.target.value)}
                            />
                        </div>
                    </div>
                </div>
            </div>
          )}

            {uiMode === 'guessing' && (
                <div className="vn-overlay guessing-overlay">
                    <div className="vn-overlay-content">
                        <div className="row-between">
                          <h2>{text.guessTitle}</h2>
                          {gameState.status === 'PLAYING' && !isGuessFinalized && (
                            <button className="secondary-btn" type="button" onClick={() => setUiMode('dialogue')}>
                              {text.backToInvestigation}
                            </button>
                          )}
                        </div>
                        {gameState.status === 'GUESSING' && <p className="notice">{text.stateGuessing}</p>}
                        {!isGuessFinalized && <p className="form-helper">{text.guessDraftHint}</p>}
                        {isGuessFinalized && <p className="notice guess-lock-warning">{text.guessLockedWarning}</p>}
                        <form className="guess-form" onSubmit={handleSubmitGuess}>
                        <p className="form-helper">{text.guessHelp}</p>
                        <div className="vn-guess-grid">
                            <div>
                                <label className="field-label" htmlFor="killer-select">
                                    {text.killer}
                                </label>
                                <select
                                    id="killer-select"
                                    value={guessForm.killer}
                                    onChange={(event) => setGuessForm({ ...guessForm, killer: event.target.value })}
                                    disabled={isGuessFinalized}
                                    required
                                >
                                    {gameState.characters.map((character) => (
                                    <option value={character.name} key={character.id}>
                                        {character.name}
                                    </option>
                                    ))}
                                </select>
                            </div>
                            <div>
                                <label className="field-label" htmlFor="motive-select">
                                    {text.motive}
                                </label>
                                <select
                                    id="motive-select"
                                    value={guessForm.motive}
                                    onChange={(event) => setGuessForm({ ...guessForm, motive: event.target.value })}
                                    disabled={isGuessFinalized}
                                    required
                                >
                                    <option value="">{text.selectMotive}</option>
                                    {guessChoiceOptions.motive.map((option) => (
                                    <option value={option} key={option}>
                                        {option}
                                    </option>
                                    ))}
                                </select>
                            </div>
                            <div>
                                <label className="field-label" htmlFor="method-select">
                                    {text.method}
                                </label>
                                <select
                                    id="method-select"
                                    value={guessForm.method}
                                    onChange={(event) => setGuessForm({ ...guessForm, method: event.target.value })}
                                    disabled={isGuessFinalized}
                                    required
                                >
                                    <option value="">{text.selectMethod}</option>
                                    {guessChoiceOptions.method.map((option) => (
                                    <option value={option} key={option}>
                                        {option}
                                    </option>
                                    ))}
                                </select>
                            </div>
                            <div>
                                <label className="field-label" htmlFor="trick-select">
                                    {text.trick}
                                </label>
                                <select
                                    id="trick-select"
                                    value={guessForm.trick}
                                    onChange={(event) => setGuessForm({ ...guessForm, trick: event.target.value })}
                                    disabled={isGuessFinalized}
                                    required
                                >
                                    <option value="">{text.selectTrick}</option>
                                    {guessChoiceOptions.trick.map((option) => (
                                    <option value={option} key={option}>
                                        {option}
                                    </option>
                                    ))}
                                </select>
                            </div>
                        </div>

                        <label className="field-label" htmlFor="reasoning-style-select">
                            {text.reasoningStyle}
                        </label>
                        <select
                            id="reasoning-style-select"
                            value={reasoningStyle}
                            onChange={(event) => setReasoningStyle(event.target.value as ReasoningStyle)}
                            disabled={isGuessFinalized}
                        >
                            <option value="evidence">{text.reasoningStyleEvidence}</option>
                            <option value="timeline">{text.reasoningStyleTimeline}</option>
                            <option value="elimination">{text.reasoningStyleElimination}</option>
                        </select>

                        <button
                            className="secondary-btn"
                            type="button"
                            onClick={handleAutofillReasoning}
                            disabled={isGuessFinalized || !guessForm.killer || !guessForm.motive || !guessForm.method || !guessForm.trick}
                        >
                            {text.autoFillReasoning}
                        </button>

                        <label className="field-label" htmlFor="reasoning-input">
                            {text.reasoning}
                        </label>
                        <textarea
                            id="reasoning-input"
                            placeholder={text.reasoningPlaceholder}
                            value={guessForm.reasoning}
                            onChange={(event) => setGuessForm({ ...guessForm, reasoning: event.target.value })}
                            disabled={isGuessFinalized}
                            required
                        />
                        <div className="guess-action-row">
                            <button className="secondary-btn" type="button" onClick={handleFinalizeGuess} disabled={isGuessFinalized}>
                              {isGuessFinalized ? text.finalDecisionDone : text.finalDecision}
                            </button>
                            <button className="primary-btn" type="submit" disabled={!isGuessFinalized}>
                                {text.submitGuess}
                            </button>
                        </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
      )}

      {screen === 'result' && result && (
        <main className="panel result-panel novel-result-panel">
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
            {result.contradictions.length === 0 && <li>{languageMode === 'ja' ? 'なし' : 'None'}</li>}
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
