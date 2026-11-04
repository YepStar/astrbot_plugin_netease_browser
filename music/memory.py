"""Discover the active LivingMemory read facade without importing or reading its storage."""

import asyncio


class MemoryPort:
    def __init__(self, context):
        self.context = context

    def providers(self):
        return [
            {"id": star.name, "active": bool(star.activated),
             "supported": callable(getattr(star.star_cls, "recall_behavior_context", None))}
            for star in self.context.get_all_stars()
            if "memory" in star.name.lower() or callable(getattr(star.star_cls, "recall_behavior_context", None))
        ]

    async def recall(self, umo, persona_id, query, *, plugin_name="astrbot_plugin_livingmemory"):
        for star in self.context.get_all_stars():
            if star.name != plugin_name or not star.activated:
                continue
            getter = getattr(star.star_cls, "recall_behavior_context", None)
            if not callable(getter):
                return {"status": "unsupported", "memories": []}
            try:
                result = await asyncio.wait_for(
                    getter(umo=umo, persona_id=persona_id, query=query), 12
                )
                if not isinstance(result, dict) or not isinstance(result.get("memories", []), list):
                    return {"status": "invalid_response", "memories": []}
                return result
            except Exception:
                return {"status": "unavailable", "memories": []}
        return {"status": "unavailable", "memories": []}
