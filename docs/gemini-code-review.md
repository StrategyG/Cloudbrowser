# Gemini AI PR Code Review

The workflow in .github/workflows/gemini-code-review.yml uses Gemini to review
actual changed-file patches on same-repository pull requests. It creates or
updates one bot comment and does not merge code automatically.

## Setup

1. Add the Actions repository secret named **GEMINI_API_KEY** in
   Settings > Secrets and variables > Actions > New repository secret.
2. Optionally set the Actions repository variable **GEMINI_MODEL**. The
   default is **gemini-3.8-flash**; select another supported model if needed.
3. Merge the workflow and its companion script into the default branch.
   On this installation pull request, the trusted base branch does not
   contain the reviewer script yet, so initial reviews will be skipped.
4. Open or update a same-repository PR. Inspect the workflow in GitHub Actions
   and its **Gemini AI Code Review (advisory)** PR comment.

## Safeguards and limitations

- The workflow uses pull_request rather than pull_request_target.
  PRs from forks are deliberately skipped because the secret is unavailable.
- It checks out a trusted base commit, not the PR's code, and reads the PR
  patch through the GitHub API without running changed code.
- Token privileges are limited to contents: read and pull-requests: write.
- A bounded input covers at most 80 files, 70,000 characters in total and
  12,000 characters per patch. The comment reports omitted or truncated data.
- Code comments and PR titles are treated as untrusted data, not instructions.
- The generated comments are advisory and do not replace human reviewers,
  automated tests, SAST, supply-chain scans or branch protections.
- PR code and title are sent to the third-party Gemini API; do not enable
  on confidential repositories without authorization and a data-sharing policy.
- Only comments owned by github-actions[bot] with the matching marker are
  edited, so other human or bot reviews are preserved.
- Gemini quota, model deprecations and API errors can cause job failures.
  Failures never fabricate a successful code review.
- SDK version constraints are intentionally broad in this initial integration.
  Review and pin the resolved dependencies for a higher-assurance deployment.

## Validation

Run the included unit tests with:

    python -m pytest -q tests/test_gemini_pr_review.py

The repository's existing Verify Cloudbrowser CI continues to run its own
lint, tests and Docker checks independently of Gemini review.
