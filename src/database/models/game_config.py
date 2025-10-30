from typing import Optional, Any, Dict
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSON
from datetime import datetime


class GameConfig(SQLModel, table=True):
    """
    Dynamic game configuration stored in database.
    
    Allows balance changes without code deployment.
    ConfigManager caches these values in memory.
    
    Attributes:
        config_key: Unique key (e.g., 'fusion_rates', 'xp_curve')
        config_value: JSON data containing configuration
        description: Human-readable description
        last_modified: Timestamp of last update
        modified_by: Username/system that made the change
    """
    
    __tablename__ = "game_config"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    config_key: str = Field(
        sa_column=Column(String(100)),
        unique=True,
        nullable=False,
        index=True
    )
    
    config_value: Dict[str, Any] = Field(sa_column=Column(JSON), nullable=False)
    description: str = Field(default="", max_length=500)
    
    last_modified: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    modified_by: Optional[str] = Field(default=None, max_length=100)
    
    def __repr__(self) -> str:
        return f"<GameConfig(key='{self.config_key}', modified={self.last_modified})>"