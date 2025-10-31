from typing import Callable, Dict, List, Any
import asyncio

class EventBus:
    """Simple async pub/sub event bus for in-game events."""

    _listeners: Dict[str, List[Callable[[Dict[str, Any]], Any]]] = {}

    @classmethod
    def subscribe(cls, event_name: str, callback: Callable[[Dict[str, Any]], Any]):
        cls._listeners.setdefault(event_name, []).append(callback)

    @classmethod
    async def publish(cls, event_name: str, data: Dict[str, Any]):
        listeners = cls._listeners.get(event_name, [])
        for listener in listeners:
            try:
                if asyncio.iscoroutinefunction(listener):
                    await listener(data)
                else:
                    listener(data)
            except Exception as e:
                print(f"[EventBus] Error in listener for {event_name}: {e}")
