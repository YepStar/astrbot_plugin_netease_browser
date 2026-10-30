"""Discover the active LivingMemory read facade without importing or reading its storage."""

import asyncio


class MemoryPort:
    def __init__(self, context):
        self.context = context

    async def recall(self, umo, persona_id, query):
        for star in self.context.get_all_stars():
            if star.name != "astrbot_plugin_livingmemory" or not star.activated:
                continue
            getter = getattr(star.star_cls, "recall_behavior_context", None)
            if not callable(getter):
                return {"status": "unsupported", "memories": []}
            try:
                return await asyncio.wait_for(
                    getter(umo=umo, persona_id=persona_id, query=query), 12
                )
            except Exception:
                return {"status": "unavailable", "memories": []}
        return {"status": "unavailable", "memories": []}
