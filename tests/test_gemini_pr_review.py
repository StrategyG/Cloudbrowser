"""Offline unit tests for Gemini PR review guards and coverage."""

from scripts.gemini_pr_review import MARKER, build_diff, find_review_comment


def test_diff_reads_real_patch():
    body, stats = build_diff(
        [
            {
                "filename": "cloudbrowser/server.py",
                "status": "modified",
                "patch": "@@ -1 +1 @@\n-old\n+new",
            }
        ]
    )
    assert "FILE: cloudbrowser/server.py" in body
    assert "+new" in body
    assert stats == {
        "total": 1,
        "included": 1,
        "unavailable": 0,
        "truncated": 0,
        "omitted": 0,
    }


def test_missing_binary_patch_is_explicit():
    body, stats = build_diff([{"filename": "image.png", "status": "added"}])
    assert "Patch unavailable" in body
    assert stats["unavailable"] == 1


def test_only_our_bot_comment_can_be_updated():
    comments = [
        {"id": 1, "user": {"login": "someone"}, "body": MARKER},
        {"id": 2, "user": {"login": "github-actions[bot]"}, "body": "Unrelated"},
        {"id": 3, "user": {"login": "github-actions[bot]"}, "body": MARKER},
    ]
    assert find_review_comment(comments) == 3


def test_file_count_is_bounded():
    body, stats = build_diff(
        [
            {"filename": f"file{i}.py", "status": "modified", "patch": "+safe"}
            for i in range(85)
        ]
    )
    assert stats["included"] == 80
    assert stats["omitted"] == 5
    assert "file84.py" not in body


def test_patch_truncation_is_disclosed():
    body, stats = build_diff(
        [{"filename": "large.py", "status": "modified", "patch": "x" * 15000}]
    )
    assert "[Patch truncated.]" in body
    assert stats["truncated"] == 1
