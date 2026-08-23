from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tresrv.models import Base


def make_session_factory(database_url: str):
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)
