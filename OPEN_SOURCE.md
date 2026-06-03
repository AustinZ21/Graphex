# CGA Open Source License Package

CGA (Context Graph Agent) is released as open source under the Apache License
2.0. This file explains the project-level licensing package and the operational
rules maintainers should follow when publishing source code, container images,
or desktop bundles.

This document is a project policy summary, not legal advice.

## License Summary

- Primary project license: Apache License 2.0.
- Project author and creator: Nate Scott.
- Full license text: [LICENSE](LICENSE).
- Project notices and acknowledgements: [NOTICE.md](NOTICE.md).
- Usage disclaimer: [DISCLAIMER.md](DISCLAIMER.md).
- Direct dependency notice summary: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- Contribution terms: [CONTRIBUTING.md](CONTRIBUTING.md).
- Community expectations: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
- Security reporting policy: [SECURITY.md](SECURITY.md).

## Distribution Requirements

When redistributing CGA source, binaries, container images, desktop bundles, or
substantial portions of the software, include:

1. `LICENSE`
2. `NOTICE.md`
3. `DISCLAIMER.md`
4. `THIRD_PARTY_NOTICES.md`
5. Any third-party license notices required by resolved dependencies, base
   images, browser assets, fonts, icons, images, models, templates, or bundled
   artifacts for that exact release build

The Apache License 2.0 requires redistributors to preserve the license, retain
copyright, patent, trademark, and attribution notices, mark modified files, and
carry forward applicable notices from `NOTICE.md`.

`DISCLAIMER.md` does not replace the Apache License 2.0 warranty and liability
terms. It gives users practical operational guidance for configuration,
sensitive data, automation, AI-assisted output, third-party services, and
unsupported assumptions.

## Author And Attribution

CGA (Context Graph Agent) was created and authored by Nate Scott. Public project
documentation, notices, release notes, desktop bundle documentation, and
redistributions should retain that attribution. The promotional website may keep
author credit limited to its footer while these project documents carry the
formal attribution record.

## Third-Party Dependency Review

Before a public release, maintainers should review direct and transitive
dependencies from the exact build artifacts:

- Python dependencies from `requirements.txt` and the resolved environment.
- Viewer dependencies from `src/viewer/package-lock.json`.
- Browser-delivered JavaScript, CSS, font, icon, and image assets.
- Container/base image licenses from the release compose files and image build
  manifests.

If a dependency is added, removed, or replaced, update
`THIRD_PARTY_NOTICES.md` in the same change.

## Contribution Licensing

Unless a separate written agreement says otherwise, contributions submitted to
CGA are accepted under the same Apache License 2.0 that covers the project. By
opening a pull request, issue patch, or other contribution, contributors confirm
they have the right to submit the contribution and license it under Apache-2.0.

## Acknowledgement Policy

Acknowledgements may thank organizations or communities that support open
source, developer tooling, or the CGA ecosystem. Acknowledgements must not imply
endorsement, sponsorship, affiliation, or ownership unless that relationship is
explicitly documented by the maintainers.

## Maintainer Release Checklist

Before publishing a release:

1. Confirm `LICENSE` still reflects the intended public license.
2. Confirm `NOTICE.md` contains current project notices and acknowledgements.
3. Confirm `DISCLAIMER.md` reflects the current product surface and risk model.
4. Confirm `THIRD_PARTY_NOTICES.md` reflects direct dependencies and points to
   exact transitive dependency notices for the release build.
5. Confirm no secrets, private keys, runtime databases, `.env` files, or local
   deployment artifacts are tracked.
6. Run the normal validation and release checks described in
   [docs/PUBLISHING.md](docs/PUBLISHING.md).
