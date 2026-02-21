from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import relationship

from .database import Base


class Game(Base):
    __tablename__ = "games"
    __table_args__ = (
        CheckConstraint("remaining_questions >= 0", name="ck_games_remaining_questions_non_negative"),
        CheckConstraint(
            "status IN ('INIT','PLAYING','GUESSING','RESULT','ENDED')",
            name="ck_games_status_valid",
        ),
        CheckConstraint("language_mode IN ('ja','en')", name="ck_games_language_mode_valid"),
    )

    id = Column(String(36), primary_key=True, index=True)
    status = Column(String(16), nullable=False, default="INIT")
    remaining_questions = Column(Integer, nullable=False, default=12)
    language_mode = Column(String(2), nullable=False, default="ja")
    unlocked_evidence_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    case = relationship("Case", back_populates="game", uselist=False, cascade="all, delete-orphan")
    messages = relationship(
        "Message",
        back_populates="game",
        order_by="Message.created_at",
        cascade="all, delete-orphan",
    )
    guess = relationship("Guess", back_populates="game", uselist=False, cascade="all, delete-orphan")


class Case(Base):
    __tablename__ = "cases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    game_id = Column(String(36), ForeignKey("games.id", ondelete="CASCADE"), nullable=False, unique=True)
    case_id = Column(String(36), nullable=False)
    title = Column(String(255), nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    game = relationship("Game", back_populates="case")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    game_id = Column(String(36), ForeignKey("games.id", ondelete="CASCADE"), nullable=False, index=True)
    question = Column(Text, nullable=False)
    target = Column(String(64), nullable=True)
    answer_text = Column(Text, nullable=False)
    language_mode = Column(String(2), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    game = relationship("Game", back_populates="messages")


class Guess(Base):
    __tablename__ = "guesses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    game_id = Column(String(36), ForeignKey("games.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    killer = Column(String(255), nullable=False)
    motive = Column(Text, nullable=False)
    method = Column(Text, nullable=False)
    trick = Column(Text, nullable=False)
    reasoning = Column(Text, nullable=False)
    score = Column(Integer, nullable=False)
    grade = Column(String(1), nullable=False)
    feedback = Column(JSON, nullable=False)
    weaknesses_top3 = Column(JSON, nullable=False)
    solution_summary = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    game = relationship("Game", back_populates="guess")
