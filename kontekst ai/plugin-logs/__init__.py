"""Plugin-logs — log event analysis tools (stub)."""

from ai_repo.plugins.base import PluginBase, PluginContext


class LogsPlugin(PluginBase):
    """Plugin providing log analysis tools."""

    def register(self, context: PluginContext) -> dict:
        db = context.db

        def search_logs(args: dict) -> dict:
            """Search log events by service, level, or time range."""
            from ai_repo.core.database import LogEvent
            with db.get_session() as session:
                q = session.query(LogEvent)

                service = args.get("service")
                if service:
                    q = q.filter(LogEvent.service == service)

                level = args.get("level")
                if level:
                    q = q.filter(LogEvent.level == level)

                limit = args.get("limit", 50)
                events = q.order_by(LogEvent.ts.desc()).limit(limit).all()

                return {
                    "events": [
                        {
                            "ts": str(e.ts),
                            "service": e.service,
                            "level": e.level,
                            "message": e.message,
                            "error_signature": e.error_signature,
                        }
                        for e in events
                    ]
                }

        def error_summary(args: dict) -> dict:
            """Get unique error signatures with counts."""
            from sqlalchemy import func
            from ai_repo.core.database import LogEvent
            with db.get_session() as session:
                rows = (
                    session.query(
                        LogEvent.error_signature,
                        func.count(LogEvent.id).label("count"),
                    )
                    .filter(LogEvent.error_signature.isnot(None))
                    .group_by(LogEvent.error_signature)
                    .order_by(func.count(LogEvent.id).desc())
                    .limit(args.get("limit", 20))
                    .all()
                )
                return {
                    "errors": [
                        {"signature": r[0], "count": r[1]}
                        for r in rows
                    ]
                }

        return {
            "logs.search": search_logs,
            "logs.error_summary": error_summary,
        }
