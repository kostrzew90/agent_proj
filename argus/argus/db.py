from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from argus.config import settings

class Base(DeclarativeBase):
    pass

engine = create_engine(settings.db_url, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
