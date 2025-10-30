from typing import Dict

from src.database.models.daily_quest import DailyQuest
from src.services.config_manager import ConfigManager


class QuestService:
    """
    Daily quest reward calculation and management.
    
    Handles reward calculation with completion bonuses and streak multipliers.
    Rewards scale with consecutive day completion streaks.
    
    Usage:
        >>> rewards = QuestService.calculate_rewards(daily_quest)
        >>> print(f"Rikis: {rewards['rikis']}, Grace: {rewards['grace']}")
    """
    
    @staticmethod
    def calculate_rewards(daily_quest: DailyQuest) -> Dict[str, int]:
        """
        Calculate rewards for completed daily quests.
        
        Base rewards granted for any progress.
        Completion bonus granted if all quests finished.
        Streak multiplier applied based on consecutive days (7-day increments).
        
        Args:
            daily_quest: DailyQuest object with completion data
        
        Returns:
            Dictionary with reward amounts:
                - rikis (int)
                - grace (int)
                - riki_gems (int)
        
        Example:
            >>> # Incomplete quests (3/5)
            >>> calculate_rewards(quest)
            {'rikis': 500, 'grace': 3, 'riki_gems': 1}
            
            >>> # Complete quests + 14-day streak
            >>> calculate_rewards(complete_quest)
            {'rikis': 1200, 'grace': 6, 'riki_gems': 2}  # +20% from streak
        """
        base_rikis = ConfigManager.get("quest_rewards.base_rikis", 500)
        base_grace = ConfigManager.get("quest_rewards.base_grace", 3)
        base_gems = ConfigManager.get("quest_rewards.base_gems", 1)
        
        completion_bonus_rikis = ConfigManager.get("quest_rewards.completion_bonus_rikis", 500)
        completion_bonus_grace = ConfigManager.get("quest_rewards.completion_bonus_grace", 2)
        completion_bonus_gems = ConfigManager.get("quest_rewards.completion_bonus_gems", 1)
        
        streak_multiplier = ConfigManager.get("quest_rewards.streak_multiplier", 0.1)
        
        base_rewards = {
            "rikis": base_rikis,
            "grace": base_grace,
            "riki_gems": base_gems
        }
        
        if daily_quest.is_complete():
            base_rewards["rikis"] += completion_bonus_rikis
            base_rewards["grace"] += completion_bonus_grace
            base_rewards["riki_gems"] += completion_bonus_gems
        
        if daily_quest.bonus_streak >= 7:
            multiplier = 1 + (daily_quest.bonus_streak // 7) * streak_multiplier
            for key in base_rewards:
                base_rewards[key] = int(base_rewards[key] * multiplier)
        
        return base_rewards