from pydantic import BaseModel
from typing import Literal, Optional, List

class AdminTemplateOut(BaseModel):
    id: int
    name: str
    original_filename: str
    created_at: str

    class Config:
        from_attributes = True

GenerateMode = Literal["ALL", "BOOK", "SELECTED"]

class AdminTemplateGenerateIn(BaseModel):
    mode: GenerateMode
    book_id: Optional[int] = None
    user_ids: Optional[List[int]] = None