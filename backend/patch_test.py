with open('tests/test_phase11_devices.py', 'r', encoding='utf-8') as f:
    c = f.read()
old_fixture = '''@pytest.fixture
def test_client(db_session: Session):
    from app.core.database import get_db
    def override_get_db():
        yield db_session
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()'''
new_fixture = '''@pytest.fixture
def test_client(db_session: Session, monkeypatch):
    import sys
    db_url = str(db_session.get_bind().url)
    monkeypatch.setenv(\"DATABASE_URL\", db_url)
    monkeypatch.setenv(\"ENVIRONMENT\", \"test\")
    for k in list(sys.modules.keys()):
        if k.startswith(\"app.\"):
            del sys.modules[k]
    from app.main import app as fresh_app
    with TestClient(fresh_app) as c:
        yield c'''
c = c.replace(old_fixture, new_fixture)
with open('tests/test_phase11_devices.py', 'w', encoding='utf-8') as f:
    f.write(c)
