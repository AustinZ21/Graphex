from pydantic import ValidationError

from backend.auth.models import AdminUserUpdate, ProjectCreate, ProjectUpdate, UserCreate


def test_rejects_sqli_like_username_payload():
    try:
        UserCreate(username="admin'; DROP TABLE users;--", password="Password123!", role="developer")
        assert False, "Expected ValidationError"
    except ValidationError:
        pass


def test_rejects_sqli_like_project_name_payload():
    try:
        ProjectCreate(project_name="proj'; DELETE FROM projects;--", upstream_url="http://localhost:8001", description="x")
        assert False, "Expected ValidationError"
    except ValidationError:
        pass


def test_accepts_valid_identifier_payloads():
    u = UserCreate(username="admin_user-01", password="Password123!", role="developer")
    p = ProjectCreate(project_name="browseragent-prod", upstream_url="http://localhost:8001", description="safe")
    a = AdminUserUpdate(username="viewer.user")
    assert u.username == "admin_user-01"
    assert p.project_name == "browseragent-prod"
    assert a.username == "viewer.user"


def test_rejects_non_http_upstream_url():
    try:
        ProjectCreate(project_name="valid-key", upstream_url="javascript:alert(1)", description="x")
        assert False, "Expected ValidationError"
    except ValidationError:
        pass


def test_project_update_optional_validations():
    ok = ProjectUpdate(project_name="valid-key", upstream_url="https://localhost:8001", description="desc")
    assert ok.project_name == "valid-key"
    try:
        ProjectUpdate(project_name="bad key with spaces")
        assert False, "Expected ValidationError"
    except ValidationError:
        pass
