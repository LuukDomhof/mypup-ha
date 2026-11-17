# Release Checklist (HACS)

Follow these steps for every integration update so `main` stays green and HACS detects the new version cleanly:

1. **Develop & test on `dev`**
   - Never commit untested changes directly to `main`.
   - Run local checks:
     - `python -m unittest discover -s tests -v`
     - `python -m py_compile custom_components/mypup/*.py`
     - Validate JSON (`hacs.json`, `manifest.json`, `strings.json`, `translations/en.json`) and YAML (`services.yaml`, `.github/workflows/validate.yml`).
2. **Determine & bump Semantic Version (`MAJOR.MINOR.PATCH`) on `dev`**
   - Review commits since the last tag (`git log <last-tag>..HEAD --oneline`) and bump `"version"` in `custom_components/mypup/manifest.json` accordingly:
     - **`PATCH` (`X.Y.Z+1`)**: bug fixes, copy/translation tweaks, docs, CI/test fixes, or internal refactors.
     - **`MINOR` (`X.Y+1.0`)**: new backwards-compatible features, entities, services, or options.
     - **`MAJOR` (`X+1.0.0`)**: breaking changes (e.g., renamed entities/attributes or incompatible config changes).
3. **Push `dev` and verify GitHub Actions CI passes (MANDATORY GATE)**
   - Push `dev`: `git push origin dev`
   - Wait for **all** GitHub Actions jobs (`tests`, `hassfest`, `hacs`) to succeed on `dev` (`gh run list -R LuukDomhof/mypup-ha --branch dev`).
   - **Do NOT merge into `main` or tag a release until GitHub Actions is green on `dev`.**
4. **Merge `dev` into `main`, tag, & publish GitHub Release**
   - `git checkout main && git merge --ff-only dev && git push origin main`
   - `git tag -a vX.Y.Z -m "Release vX.Y.Z" && git push origin vX.Y.Z`
   - Publish the release with `gh release create vX.Y.Z -R LuukDomhof/mypup-ha --title "vX.Y.Z" --notes "..."` (always include Markdown release notes, since HACS displays them as the update changelog).
