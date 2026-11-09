import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from argus.db import Base
import argus.models  # noqa: F401  (rejestruje tabele)

@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    s = Sess()
    yield s
    s.close()
