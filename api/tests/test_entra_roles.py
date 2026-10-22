import pytest

from app.auth.microsoft import SsoDenied, resolve_role
from app.core import settings


def test_role_claim_resolution_prefers_admin(monkeypatch):
    monkeypatch.setattr(settings, "ENTRA_ROLE_SOURCE", "roles")
    monkeypatch.setattr(settings, "ENTRA_ROLE_ADMIN", "Admin")
    monkeypatch.setattr(settings, "ENTRA_ROLE_VIEWER", "Viewer")
    assert resolve_role({"roles": ["Viewer"]}) == "Viewer"
    assert resolve_role({"roles": ["Viewer", "Admin"]}) == "Admin"
    assert resolve_role({"roles": []}) is None
    assert resolve_role({"roles": "Admin"}) is None


def test_group_claim_resolution_and_overage(monkeypatch):
    monkeypatch.setattr(settings, "ENTRA_ROLE_SOURCE", "groups")
    monkeypatch.setattr(settings, "ENTRA_GROUP_ADMIN_ID", "group-admin")
    monkeypatch.setattr(settings, "ENTRA_GROUP_VIEWER_ID", "group-viewer")
    assert resolve_role({"groups": ["group-viewer"]}) == "Viewer"
    assert resolve_role({"groups": ["group-viewer", "group-admin"]}) == "Admin"
    with pytest.raises(SsoDenied) as err:
        resolve_role({"_claim_names": {"groups": "src1"}})
    assert err.value.detail == "groups_overage"
