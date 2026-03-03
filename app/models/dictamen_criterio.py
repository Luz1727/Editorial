from sqlalchemy import Column, BigInteger, Integer, String, ForeignKey
from sqlalchemy.orm import relationship

from app.db.session import Base


class DictamenCriterio(Base):
    __tablename__ = "dictamen_criterios"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    dictamen_id = Column(BigInteger, ForeignKey("dictamenes.id", ondelete="CASCADE"), nullable=False, index=True)

    criterio = Column(String(255), nullable=False)
    value = Column(Integer, nullable=False)

    dictamen = relationship("Dictamen", back_populates="criterios")