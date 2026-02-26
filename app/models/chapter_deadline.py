from datetime import datetime
from sqlalchemy import Column, BigInteger, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.db.session import Base

class ChapterDeadline(Base):
    __tablename__ = "chapter_deadlines"

    id = Column(BigInteger, primary_key=True, index=True)
    chapter_id = Column(BigInteger, ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False, index=True)

    stage = Column(String(50), nullable=False)
    due_at = Column(DateTime, nullable=False)

    set_by = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    note = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relaciones
    chapter = relationship("Chapter", back_populates="deadlines")
    setter = relationship("User", foreign_keys=[set_by], backref="deadlines_set")  # ← así está bien