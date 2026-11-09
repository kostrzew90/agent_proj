import yaml
from sqlalchemy import select
from argus.models import Asset, Source


def seed_assets(session, path: str) -> None:
    data = yaml.safe_load(open(path, encoding="utf-8"))
    for a in data["assets"]:
        existing = session.get(Asset, a["symbol"])
        if existing is None:
            session.add(Asset(**a))
        else:
            for k, v in a.items():
                setattr(existing, k, v)
    session.commit()


def seed_sources(session, path: str) -> None:
    data = yaml.safe_load(open(path, encoding="utf-8"))
    for s in data["sources"]:
        existing = session.scalar(select(Source).where(Source.handle == s["handle"]))
        if existing is None:
            session.add(Source(**s))
        else:
            existing.display_name = s["display_name"]
    session.commit()
