"""pytest 公共 fixture：临时文件 SQLite（每测试独立文件，避免 :memory: 连接竞态）+ 全模型建表。"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models_registry  # noqa: F401  确保全部模型注册到 Base
from database import Base


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
