import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

def test_app_imports_and_loads():
    from app.main import app
    assert app is not None
