from typing import Optional, Dict
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import BigInteger
from sqlalchemy.dialects.postgresql import JSON
from datetime import datetime


class TutorialProgress(SQLModel, table=True):
    """
    Player tutorial progress and reward tracking.
    
    Tracks completion of tutorial steps and reward claims.
    Tutorial serves as onboarding experience teaching core mechanics.
    
    Tutorial Steps:
        - register_account: Complete registration
        - first_prayer: Use /prayer command
        - first_summon: Use /summon command
        - first_fusion: Attempt fusion
        - view_collection: Check /maidens
        - set_leader: Set a leader maiden
        - complete_daily_quest: Finish all daily objectives
    
    Rewards per step (configurable):
        - Grace, Rikis, or XP rewards
        - Unlocking features
        - Guidance popups
    
    Attributes:
        player_id: Owner's Discord ID
        steps_completed: Dict tracking which steps are done
        rewards_claimed: Dict tracking which rewards taken
        started_at: When tutorial began
        completed_at: When all steps finished (nullable)
    """
    
    __tablename__ = "tutorial_progress"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(
        sa_column=Column(BigInteger, nullable=False, unique=True, index=True),
        foreign_key="players.discord_id"
    )
    
    steps_completed: Dict[str, bool] = Field(
        default_factory=lambda: {
            "register_account": False,
            "first_prayer": False,
            "first_summon": False,
            "first_fusion": False,
            "view_collection": False,
            "set_leader": False,
            "complete_daily_quest": False
        },
        sa_column=Column(JSON)
    )
    
    rewards_claimed: Dict[str, bool] = Field(
        default_factory=lambda: {
            "register_account": False,
            "first_prayer": False,
            "first_summon": False,
            "first_fusion": False,
            "view_collection": False,
            "set_leader": False,
            "complete_daily_quest": False
        },
        sa_column=Column(JSON)
    )
    
    started_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    completed_at: Optional[datetime] = Field(default=None)
    
    def is_step_complete(self, step: str) -> bool:
        """
        Check if specific tutorial step is completed.
        
        Args:
            step: Tutorial step name
        
        Returns:
            True if step completed, False otherwise
        
        Example:
            >>> if tutorial.is_step_complete("first_prayer"):
            ...     print("Prayer step done!")
        """
        return self.steps_completed.get(step, False)
    
    def is_reward_claimed(self, step: str) -> bool:
        """
        Check if reward for step has been claimed.
        
        Args:
            step: Tutorial step name
        
        Returns:
            True if reward claimed, False otherwise
        
        Example:
            >>> if not tutorial.is_reward_claimed("first_summon"):
            ...     print("Reward available!")
        """
        return self.rewards_claimed.get(step, False)
    
    def complete_step(self, step: str) -> bool:
        """
        Mark tutorial step as completed.
        
        Args:
            step: Tutorial step name
        
        Returns:
            True if step was newly completed, False if already done
        
        Example:
            >>> if tutorial.complete_step("first_fusion"):
            ...     print("Step newly completed!")
        """
        if step not in self.steps_completed:
            return False
        
        if self.steps_completed[step]:
            return False
        
        self.steps_completed[step] = True
        
        if self.is_tutorial_complete() and not self.completed_at:
            self.completed_at = datetime.utcnow()
        
        return True
    
    def claim_reward(self, step: str) -> bool:
        """
        Mark reward as claimed for step.
        
        Validates that step is completed before allowing claim.
        
        Args:
            step: Tutorial step name
        
        Returns:
            True if reward newly claimed, False if already claimed or step not done
        
        Example:
            >>> if tutorial.claim_reward("set_leader"):
            ...     print("Reward claimed!")
        """
        if step not in self.rewards_claimed:
            return False
        
        if not self.is_step_complete(step):
            return False
        
        if self.rewards_claimed[step]:
            return False
        
        self.rewards_claimed[step] = True
        return True
    
    def get_progress_count(self) -> int:
        """
        Get number of completed tutorial steps.
        
        Returns:
            Count of completed steps (0-7)
        
        Example:
            >>> progress = tutorial.get_progress_count()
            >>> print(f"Tutorial: {progress}/7 steps")
        """
        return sum(1 for completed in self.steps_completed.values() if completed)
    
    def get_progress_percentage(self) -> float:
        """
        Calculate tutorial completion percentage.
        
        Returns:
            Percentage (0-100)
        
        Example:
            >>> percent = tutorial.get_progress_percentage()
            >>> print(f"Tutorial {percent:.1f}% complete")
        """
        total = len(self.steps_completed)
        completed = self.get_progress_count()
        return (completed / total) * 100 if total > 0 else 0.0
    
    def is_tutorial_complete(self) -> bool:
        """
        Check if all tutorial steps are completed.
        
        Returns:
            True if all steps done, False otherwise
        
        Example:
            >>> if tutorial.is_tutorial_complete():
            ...     print("Tutorial finished!")
        """
        return all(self.steps_completed.values())
    
    def get_unclaimed_rewards(self) -> list[str]:
        """
        Get list of steps with unclaimed rewards.
        
        Returns:
            List of step names with rewards available
        
        Example:
            >>> unclaimed = tutorial.get_unclaimed_rewards()
            >>> print(f"Unclaimed rewards: {len(unclaimed)}")
        """
        return [
            step for step, completed in self.steps_completed.items()
            if completed and not self.rewards_claimed.get(step, False)
        ]
    
    def get_next_step(self) -> Optional[str]:
        """
        Get next incomplete tutorial step.
        
        Returns steps in order:
        1. register_account
        2. first_prayer
        3. first_summon
        4. first_fusion
        5. view_collection
        6. set_leader
        7. complete_daily_quest
        
        Returns:
            Step name or None if all complete
        
        Example:
            >>> next_step = tutorial.get_next_step()
            >>> if next_step:
            ...     print(f"Next: {next_step}")
        """
        step_order = [
            "register_account",
            "first_prayer",
            "first_summon",
            "first_fusion",
            "view_collection",
            "set_leader",
            "complete_daily_quest"
        ]
        
        for step in step_order:
            if not self.steps_completed.get(step, False):
                return step
        
        return None
    
    def __repr__(self) -> str:
        return (
            f"<TutorialProgress(player={self.player_id}, "
            f"progress={self.get_progress_count()}/7, "
            f"complete={self.is_tutorial_complete()})>"
        )