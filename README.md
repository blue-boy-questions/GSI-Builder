# GSI Builder

Build a Generic System Image from stock Android firmware using [MysticGSI](https://github.com/MysticGSI/mysticgsi) and GitHub Actions.

## Build

1. Open the **Actions** tab.
2. Select **Build MysticGSI**.
3. Click **Run workflow**.
4. Enter:
   - `firmware_url`: direct firmware download URL
   - `build_name`: output name
   - `rom_type`: patch type such as `generic`, `pixel`, `hyperos`, `coloros`, or `oneui`
   - `no_debloat`: retain applications normally removed by the patch set
5. Download the result from the workflow run's **Artifacts** section.

The workflow creates a compressed output, generates `SHA256SUMS`, and retains the artifact for seven days.

## Notes

- The firmware URL must be directly downloadable by the GitHub-hosted runner.
- Large firmware packages require substantial temporary disk space.
- Workflow artifacts are not GitHub Release assets.
- Review MysticGSI's documentation and supported firmware formats before building.

## License

This repository contains only the GitHub Actions wrapper. MysticGSI is maintained and licensed separately by its upstream authors.
