from app.services import jobs


def test_job_requires_confirmation(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    job = jobs.create("video", {"prompt": "night city"}, 0.5)
    assert job.status == "awaiting_confirmation"
    confirmed = jobs.confirm(job.id)
    assert confirmed is not None
    assert confirmed.status == "queued"


def test_job_cannot_confirm_twice(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    job = jobs.create("song", {}, 0)
    jobs.confirm(job.id)
    assert jobs.confirm(job.id) is None
