"""Organize: group loose files sharing a naming convention into one folder."""
import uuid

from fastapi.testclient import TestClient

from app.analyzers.naming import convention, folder_name_for, suggest_groups
from app.core.database import SessionLocal, init_db
from app.main import app
from app.models import DriveFile, OptimizationAction, OrganizeSuggestion, User, UserSettings
from app.services import optimization_service, organize_service

init_db()


def f(drive_id, name, parent="root", category="images", size=100):
    return {"drive_id": drive_id, "name": name, "parent_id": parent, "category": category, "size_bytes": size}


def test_convention_and_folder_names():
    assert convention("Screenshot (35).png") == "Screenshot"
    assert convention("Screen Recording 2026-08-01 113349.mp4") == "Screen Recording"
    assert convention("IMG_2001 (1).jpg") == "IMG"
    assert convention("ICONAT_Sahyog paper_Submission.pdf") is None  # no counter/date: not a convention
    assert convention("2024.pdf") is None
    assert folder_name_for("Screenshot", "images") == "Screenshots"
    assert folder_name_for("Screen Recording", "video") == "Screen Recordings"
    assert folder_name_for("IMG", "images") == "Photos" and folder_name_for("VID", "video") == "Videos"
    assert folder_name_for("budget", "spreadsheets") == "Budgets"
    assert folder_name_for("lecture copy", "pdf") == "Lecture copies"


def test_groups_need_three_files_in_the_same_folder_and_kind():
    files = [f(f"s{i}", f"Screenshot ({i}).png") for i in range(3)]
    files += [f("o1", "Screenshot (9).png", parent="other")]          # different folder
    files += [f(f"r{i}", f"report_{i}.pdf", category="pdf") for i in range(2)]  # only two
    groups = suggest_groups(files, folders={}, root_id="root")
    assert len(groups) == 1
    g = groups[0]
    assert (g.folder_name, g.parent_name, len(g.drive_ids)) == ("Screenshots", "My Drive", 3)
    assert g.pattern == "Screenshot….png"


def test_reuses_an_existing_folder_and_skips_already_organized_files():
    folders = {"fold-1": {"name": "Screenshots", "parent_id": "root"},
               "fold-2": {"name": "Photos", "parent_id": "root"}}
    loose = [f(f"s{i}", f"Screenshot ({i}).png") for i in range(3)]
    inside = [f(f"p{i}", f"IMG_{i}.jpg", parent="fold-2") for i in range(4)]  # already in "Photos"
    groups = suggest_groups(loose + inside, folders, root_id="root")
    assert [g.folder_name for g in groups] == ["Screenshots"]
    assert groups[0].existing_folder_id == "fold-1"


def test_dedicated_folders_and_cryptic_prefixes_are_left_alone():
    # A submissions folder holding only Q01_….java … Q22_….java is already organized.
    assignment = [f(f"q{i}", f"Q{i:02d}_Sort.java", parent="daa", category="code") for i in range(1, 23)]
    assert suggest_groups(assignment, {"daa": {"name": "DAA_22submissions", "parent_id": "root"}}, "root") == []
    # Same files loose in My Drive: still skipped — "Q" is too cryptic for a folder name.
    loose = [f(f"q{i}", f"Q{i:02d}_Sort.java", category="code") for i in range(1, 23)]
    assert suggest_groups(loose, {}, "root") == []
    # Known short conventions still count, and My Drive itself is never "dedicated".
    photos = [f(f"p{i}", f"IMG_{i}.jpg") for i in range(5)]
    assert [g.folder_name for g in suggest_groups(photos, {}, "root")] == ["Photos"]


def test_demo_organize_and_undo():
    c = TestClient(app)
    c.post("/auth/demo")
    c.post("/api/analyze")
    suggestions = c.get("/api/organize").json()
    assert {"Budgets", "Untitled documents"} <= {s["folder_name"] for s in suggestions}
    target = next(s for s in suggestions if s["folder_name"] == "Budgets")
    res = c.post(f"/api/organize/{target['id']}/apply", json={"folder_name": "Budget sheets"}).json()
    assert res["success"] and res["moved"] == target["count"] and res["folder_name"] == "Budget sheets"
    assert target["id"] not in {s["id"] for s in c.get("/api/organize").json()}

    entry = next(h for h in c.get("/api/history").json() if h["action"] == "organized")
    assert entry["restorable"] and "Budget sheets" in entry["detail"]
    assert c.post(f"/api/history/{entry['id']}/restore").status_code == 200
    user_id = c.get("/api/user").json()["id"]
    with SessionLocal() as db:
        parents = {r.parent_id for r in db.query(DriveFile).filter(
            DriveFile.user_id == user_id, DriveFile.name.like("budget_%"), DriveFile.is_trashed.is_(False))}
    assert parents == {"demo-root"}


class FakeDrive:
    def __init__(self):
        self.parents, self.folders, self.trashed = {}, {}, set()

    def create_folder(self, name, parent_id):
        fid = f"folder-{len(self.folders)}"
        self.folders[fid] = name
        return fid

    def move_file(self, file_id, new_parent, old_parent):
        assert self.parents[file_id] == old_parent
        self.parents[file_id] = new_parent

    def folder_is_empty(self, folder_id):
        return folder_id not in self.parents.values()

    def trash_file(self, file_id):
        self.trashed.add(file_id)


def test_real_moves_keep_files_and_undo_trashes_only_the_empty_new_folder(monkeypatch):
    fake = FakeDrive()
    monkeypatch.setattr(organize_service, "get_client", lambda user: fake)
    with SessionLocal() as db:
        user = User(email=f"org-{uuid.uuid4().hex}@example.com", name="O", is_demo=False, refresh_token="r")
        db.add(user)
        db.flush()
        db.add(UserSettings(user_id=user.id))
        ids = []
        for i in range(3):
            drive_id = f"shot-{uuid.uuid4().hex[:6]}"
            ids.append(drive_id)
            fake.parents[drive_id] = "root-x"
            db.add(DriveFile(user_id=user.id, drive_id=drive_id, name=f"Screenshot ({i}).png", mime_type="image/png",
                             extension=".png", category="images", size_bytes=10, parent_id="root-x"))
        sug = OrganizeSuggestion(user_id=user.id, parent_id="root-x", parent_name="My Drive", folder_name="Screenshots",
                                 pattern="Screenshot….png", category="images", drive_ids=ids,
                                 names=[f"Screenshot ({i}).png" for i in range(3)], total_bytes=30)
        db.add(sug)
        db.commit()

        res = organize_service.apply_suggestion(db, user, sug.id)
        assert res["moved"] == 3 and set(fake.parents.values()) == {"folder-0"}
        action = db.query(OptimizationAction).filter_by(user_id=user.id, action="organized").one()
        assert action.status == "success" and len(action.undo_data["moves"]) == 3

        optimization_service.restore_action(db, user, action)
        assert set(fake.parents.values()) == {"root-x"}
        assert fake.trashed == {"folder-0"}  # CloudClean's own folder, now empty -> Trash (not deleted)
        assert action.status == "reverted"


def test_folder_paths_walk_up_to_my_drive():
    from app.services.drive_service import folder_paths

    folders = {"col": {"name": "College", "parent_id": "root"}, "daa": {"name": "DAA", "parent_id": "col"},
               "shared": {"name": "From a friend", "parent_id": "not-mine"}}
    paths = folder_paths(folders, "root")
    assert paths["daa"] == "My Drive / College / DAA" and paths["root"] == "My Drive"
    assert paths["shared"] == "From a friend"  # parent isn't the user's: no fake path


def test_auth_status_reports_configuration_without_secrets():
    body = TestClient(app).get("/auth/status").json()
    assert set(body) == {"google_configured", "gmail_enabled"}
