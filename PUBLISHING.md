# Publishing crewai-pastdotdev

Two people do this, in this order:

- **The PyPI owner**: the owner of the `pastdotdev` account on PyPI and of
  the `pastdotdev` organization on GitHub. Steps A and B.
- **The listing owner**: the person who asks CrewAI to list past dev in its
  docs, from their own GitHub account. Step C.

Step C starts only when step B is complete, because the CrewAI page tells
readers to `pip install crewai-pastdotdev`.

## Before you start

Run the tests with a real project key one time. The live test spends a few
credits (one small Ingest and one Recall).

```bash
cd crewai-pastdotdev
python -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"
PAST_API_KEY="past_sk_..." pytest
```

All tests must pass and none may be skipped.

## A. The PyPI pending publisher (PyPI owner)

The release uses PyPI Trusted Publishing: PyPI accepts an upload from one
GitHub workflow, so no API token is made, stored or typed. Do this step
first. A pending publisher is allowed before the project exists on PyPI.

1. Sign in to PyPI as the `pastdotdev` account and open
   https://pypi.org/manage/account/publishing/.
2. Under "Add a new pending publisher", choose **GitHub** and fill in:

| Field | Value |
| :- | :- |
| PyPI Project Name | `crewai-pastdotdev` |
| Owner | `pastdotdev` |
| Repository name | `crewai-pastdotdev` |
| Workflow name | `publish.yml` |
| Environment name | (empty) |

3. Click **Add**.

## B. The repository and the release (PyPI owner)

The PyPI page and the CrewAI page link to
`https://github.com/pastdotdev/crewai-pastdotdev`.

1. Create the public repository `pastdotdev/crewai-pastdotdev`, with no
   README, license or `.gitignore` (the folder has them).
2. Copy this folder as it is into the repository, with its `.github` folder,
   then commit and push:

```bash
git init -b main
git add .
git commit -m "crewai-pastdotdev 0.1.0"
git remote add origin git@github.com:pastdotdev/crewai-pastdotdev.git
git push -u origin main
```

3. Push the version tag. The tag must be `v` followed by `__version__` in
   `src/crewai_pastdotdev/_version.py`:

```bash
git tag v0.1.0
git push origin v0.1.0
```

4. The tag starts `.github/workflows/publish.yml`. It checks that the tag
   matches the version, runs the tests, builds the sdist and the wheel, runs
   `twine check`, and uploads them to PyPI. Watch it under the repository's
   **Actions** tab. On the first upload, PyPI makes the project and the
   pending publisher becomes an ordinary trusted publisher.
5. Check the release from a clean environment:

```bash
python -m venv /tmp/check && /tmp/check/bin/pip install crewai-pastdotdev
/tmp/check/bin/python -c "import crewai_pastdotdev as p; print(p.__version__)"
```

For a later release, change `__version__` in
`src/crewai_pastdotdev/_version.py`, commit, push, and push the new tag
(for example `v0.1.1`).

### Fallback: upload with an API token

Use this only if Trusted Publishing cannot be used.

1. Make an API token on PyPI for the `pastdotdev` account
   (https://pypi.org/manage/account/token/). For the first upload the scope
   must be "Entire account", because the project does not exist yet. After
   the first upload, replace it with a token scoped to `crewai-pastdotdev`.
2. Build and upload from a clean checkout of the tag. When twine asks, the
   user name is `__token__` and the password is the token.

```bash
python -m pip install --upgrade build twine
rm -rf dist
python -m build
twine check dist/*
twine upload dist/*
```

## C. The CrewAI docs listing (listing owner)

CrewAI has no tool or memory catalogue to submit to: a package on PyPI is
enough to be usable, and a listing is a docs pull request to
`crewAIInc/crewAI`. All the text is in [DOCS_PR.md](DOCS_PR.md).

1. Open the issue: https://github.com/crewAIInc/crewAI/issues/new/choose,
   template "Feature request", with the fields in DOCS_PR.md, section 1.
   Write down the issue number.
2. Fork `crewAIInc/crewAI` and make the branch:

```bash
git clone git@github.com:<your-account>/crewAI.git
cd crewAI
git checkout -b docs/past-dev-memory
```

3. Make the changes in DOCS_PR.md, sections 2.1 to 2.5: the new page, the
   card, the sentence on the Memory page, the four `docs/docs.json` entries,
   and the `ar`, `ko` and `pt-BR` copies.
4. Check the links (needs Node.js):

```bash
cd docs
npx mintlify broken-links
npx mintlify dev
```

5. Commit, push and open the pull request against `main`, with the title and
   body in DOCS_PR.md, section 2. Put the issue number in both places.

```bash
git add docs
git commit -m "docs: add past dev memory and tools page"
git push -u origin docs/past-dev-memory
```

6. Answer the review. A review bot comments first. A pull request with no
   activity for 45 days is marked stale.
