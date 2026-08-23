with open("backend/tests/test_phase18_security.py", "r") as f:
    content = f.read()

import re
old_fixture = r'''@pytest\.fixture\(\)
def client\(monkeypatch, tmp_path: Path\):
    db_file = tmp_path / "test_ultron\.db"
    log_dir = tmp_path / "logs"
    monkeypatch\.setenv\("DATABASE_URL", f"sqlite:///{db_file}"\)
    monkeypatch\.setenv\("LOG_DIR", str\(log_dir\)\)
    monkeypatch\.setenv\("ENVIRONMENT", "test"\)
    monkeypatch\.delenv\("ANTHROPIC_API_KEY", raising=False\)
    monkeypatch\.delenv\("GEMINI_API_KEY", raising=False\)
    from app\.core\.config import get_settings
    get_settings\.cache_clear\(\)
    from app\.main import app
    from app\.core\.database import Base, engine
    Base\.metadata\.create_all\(bind=engine\)
    with TestClient\(app\) as test_client:
        yield test_client'''

new_fixture = '''@pytest.fixture()
def client(monkeypatch, tmp_path: Path):
    db_file = tmp_path / "test_ultron.db"
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("LOG_DIR", str(log_dir))
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from app.core.config import get_settings
    get_settings.cache_clear()
    
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    
    from app.core.database import Base, get_db
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    def override_get_db():
        try:
            db = TestingSessionLocal()
            yield db
        finally:
            db.close()
            
    from app.main import app
    app.dependency_overrides[get_db] = override_get_db
    
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()'''

new_content = re.sub(old_fixture, new_fixture, content)
with open("backend/tests/test_phase18_security.py", "w") as f:
    f.write(new_content)
