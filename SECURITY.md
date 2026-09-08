# Security

storecheck reads built app packages, declaration files, store listing text
and public rule pages. It writes only under `<app>/storecheck/` and its own
cache directory.

**Store console access is read-only by construction.** The console readers
sign requests with credentials taken from the environment and never copy,
log or persist them. They call list and get endpoints only.

**No policy text is stored.** Rule-page records hold fingerprints and
paraphrases; the full text lives in a local cache that is not committed.

To report a vulnerability, open a private security advisory on the GitHub
repository, or write to Editerra AB at contact@editerra.se. Please do not
open a public issue for a security problem.
