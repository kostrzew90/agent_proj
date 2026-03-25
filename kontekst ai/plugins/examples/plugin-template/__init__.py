"""Example plugin — demonstrates plugin structure."""

from ai_repo.plugins.base import PluginBase, PluginContext


class TemplatePlugin(PluginBase):
    """Minimal plugin that registers a single hello tool."""

    def register(self, context: PluginContext) -> dict:
        def hello_handler(args: dict) -> dict:
            name = args.get("name", "world")
            return {"message": f"Hello, {name}! This is plugin-template."}

        return {"plugin.hello": hello_handler}
