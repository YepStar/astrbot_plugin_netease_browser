"""Optional integration through the companion's published facade only."""

import sys


class CompanionPort:
    def api(self):
        # Discover an already loaded provider; never import/start another plugin.
        for name, module in list(sys.modules.items()):
            if name.endswith("astrbot_plugin_private_companion.main"):
                getter = getattr(module, "get_private_companion_api", None)
                return getter() if getter else None
        return None

    def scene(self, user_id):
        api = self.api()
        return api.get_scene_context(user_id) if api else None

    def activity(self, stage, activity_id, user_id, song=None, **metadata):
        api = self.api()
        if not api:
            return
        if stage == "ended":
            api.notify_external_activity_ended(activity_id)
            return
        method = getattr(api, "notify_external_activity_" + stage)
        method(
            activity_id,
            user_id=user_id,
            kind="music_listening",
            label="听《" + song["name"] + "》",
            source_plugin="astrbot_plugin_netease_browser",
            ttl_seconds=120,
            metadata={"song_id": song["id"], **metadata},
        )
