# Release Checklist (HACS)

Follow these steps for every integration update so HACS detects the new version cleanly:

1. **Validate syntax**
   - Python: `python -m py_compile custom_components/mypup/*.py`
   - JSON: validate `hacs.json`, `custom_components/mypup/manifest.json`, `strings.json`, and `translations/en.json`
   - YAML: validate `custom_components/mypup/services.yaml`
2. **Bump version**
   - Increment `"version"` in `custom_components/mypup/manifest.json` (e.g., `0.1.1`).
3. **Commit & push `main`**
   - `git add -A && git commit -m "Release vX.Y.Z"`
   - `git push`
4. **Tag & publish GitHub Release**
   - `git tag -a vX.Y.Z -m "Release vX.Y.Z"`
   - `git push origin vX.Y.Z`
   - Publish the release on GitHub at `https://github.com/LuukDomhof/mypup-ha/releases/new?tag=vX.Y.Z` so HACS shows the update.
