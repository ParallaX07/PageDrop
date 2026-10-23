# Release notes

Before tagging a release, copy `TEMPLATE.md` to `release-notes/vX.Y.Z.md` and
fill in the release details. The tag workflow requires this non-empty file and
uses it as the GitHub release body on both first publication and reruns. It
replaces `{{version}}` with the tag's numeric version in the published notes.
