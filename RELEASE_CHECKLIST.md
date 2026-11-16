# Release Checklist (HACS)

Follow these steps for every integration update so HACS detects the new version cleanly:

1. **Validate syntax**
   - Python: `python -m py_compile custom_components/mypup/*.py`
   - JSON: validate `hacs.json`, `custom_components/mypup/manifest.json`, `strings.json`, and `translations/en.json`
   - YAML: validate `custom_components/mypup/services.yaml`
2. **Determine & bump Semantic Version (`MAJOR.MINOR.PATCH`)**
   - Review commits since the last tag (`git log <last-tag>..HEAD --oneline`) and bump `"version"` in `custom_components/mypup/manifest.json` accordingly:
     - **`PATCH` (`X.Y.Z+1`)**: bug fixes, copy/translation tweaks, docs, or internal refactors.
     - **`MINOR` (`X.Y+1.0`)**: new backwards-compatible features, entities, services, or options.
     - **`MAJOR` (`X+1.0.0`)**: breaking changes (e.g., renamed entities/attributes or incompatible config changes).
3. **Commit & push `main`**
   - `git add -A && git commit -m "Release vX.Y.Z"`
   - `git push`
4. **Tag & publish GitHub Release**
   - `git tag -a vX.Y.Z -m "Release vX.Y.Z"`
   - `git push origin vX.Y.Z`
   - Publish the release on GitHub at `https://github.com/LuukDomhof/mypup-ha/releases/new?tag=vX.Y.Z` so HACS shows the update.
   - **Always fill in the GitHub Release notes** (or click **Generate release notes**)—HACS pulls update changelogs directly from the GitHub Release body.
