"""The review API: what the page can record, and what it must refuse.

The page's JavaScript has no test harness without a node toolchain, so this covers the server
side and the DOM layer is verified by driving the real page.
"""

import pytest
from fastapi.testclient import TestClient

from app import project as project_store
from app.manifests import base
from app.manifests.candidates import Candidate, Candidates
from app.manifests.project import Project
from app.manifests.review import Review
from app.web import server


@pytest.fixture
def project_root(tmp_path):
    root = tmp_path / "project"
    project_store.create(root, Project(id="test", created_at=project_store.now()))
    base.write(
        project_store.candidates_path(root),
        Candidates(
            candidates=[
                Candidate(id="c001", source_id="v01", start=1.0, end=5.0, anchor=5.0, kind="short"),
                Candidate(
                    id="c002",
                    source_id="v02",
                    start=0.0,
                    end=2.0,
                    anchor=2.0,
                    kind="short",
                    flags=["source_too_short"],
                ),
            ]
        ),
    )
    return root


@pytest.fixture
def client(project_root):
    return TestClient(server.create_app(project_root))


def read_review(root) -> Review:
    return base.read(project_store.review_path(root), Review)


def test_the_page_lists_usable_and_dropped_candidates_separately(client):
    body = client.get("/").text

    assert "c001" in body
    assert "c002" in body
    assert "source_too_short" in body, "a dropped candidate shows why, so it can be rescued"


def test_a_verdict_reaches_the_file(client, project_root):
    response = client.put("/api/verdict/c001", json={"verdict": "keep"})

    assert response.status_code == 200
    assert read_review(project_root).verdicts == {"c001": "keep"}


def test_a_verdict_on_an_unknown_candidate_is_refused(client, project_root):
    """A typo would otherwise accumulate entries the director never looks at, and
    `review.json` would stop describing the project it belongs to."""
    assert client.put("/api/verdict/c999", json={"verdict": "keep"}).status_code == 404
    assert not project_store.review_path(project_root).exists()


def test_an_invalid_verdict_is_refused(client):
    assert client.put("/api/verdict/c001", json={"verdict": "maybe"}).status_code == 422


def test_a_trim_is_recorded_and_can_be_cleared(client, project_root):
    client.put("/api/trim/c001", json={"start": 1.5, "end": 4.0})
    assert read_review(project_root).trims["c001"].start == 1.5

    client.delete("/api/trim/c001")
    assert "c001" not in read_review(project_root).trims


def test_a_backwards_trim_is_refused(client, project_root):
    assert client.put("/api/trim/c001", json={"start": 4.0, "end": 1.0}).status_code == 400


def test_a_note_is_recorded_and_clearing_it_removes_the_entry(client, project_root):
    client.put("/api/note/c001", json={"note": "same setup as c012"})
    assert read_review(project_root).notes["c001"] == "same setup as c012"

    client.put("/api/note/c001", json={"note": "   "})
    assert "c001" not in read_review(project_root).notes


def test_marking_done_is_recorded(client, project_root):
    client.post("/api/complete")

    assert read_review(project_root).completed is True


def test_media_outside_the_project_cannot_be_reached(client):
    """This process can read everything the user can; the route is the only thing between the
    port and their filesystem."""
    for path in (
        "/media/proxies/..%2f..%2fetc%2fpasswd",
        "/media/../../etc/passwd",
        "/media/sources/c001",
        "/media/proxies/c001%2f..%2f..%2fproject.json",
    ):
        assert client.get(path).status_code in (404, 400), path


def test_a_missing_proxy_is_a_404_not_a_crash(client):
    assert client.get("/media/proxies/c001").status_code == 404


def test_every_write_updates_the_timestamp(client, project_root):
    client.put("/api/verdict/c001", json={"verdict": "drop"})

    assert read_review(project_root).updated_at is not None
