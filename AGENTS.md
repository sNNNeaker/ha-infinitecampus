# Rules for AI agents

These rules apply to every AI coding agent that works in this repository (Claude Code, Codex, Cursor, Copilot and others). `CLAUDE.md` imports this file.

## Never publish private data

Everything committed here ends up on GitHub, including the full history. Treat the repository as public, even if it is private today. Deleting a value in a later commit does not remove it: it stays in the history.

Never put any of the following into a tracked file, a commit message, a branch or tag name, an issue, a pull request, a release note, a test fixture, a log sample or a screenshot:

- **Credentials:** passwords, tokens, API keys, cookies, session ids, JWTs, private keys, webhook ids or webhook URLs, alarm or door codes.
- **Network details:** real IP addresses (private or public), host names, MAC addresses, Wi-Fi names, personal domains, dynamic DNS names, internal URLs.
- **People:** real names of the owner's family (especially children), email addresses, phone numbers, the home address, coordinates, names of schools or daycares, student or customer numbers, photos.
- **Device and account identifiers:** serial numbers, VINs, device ids, account ids, and entity ids or file names that reveal any of the above.
- **Raw captures from real accounts:** API responses, HAR files, logs or database dumps, unless every such value has been replaced.

Use placeholders instead: `192.0.2.10` or `example.com` for addresses, `Jane Doe` and `you@example.com` for people, `<TOKEN>` for credentials, and invented ids in test fixtures.

Do not copy text from the owner's private notes or private configuration (for example a Home Assistant config folder) into this repository without replacing these values first.

## Before every commit

1. Read the staged diff (`git diff --cached`) and check it against the list above.
2. Check the commit message too.
3. If you are unsure whether a value is private, treat it as private and ask the owner.

## Before every push to GitHub

1. Push to GitHub only when the owner asks for it in this session. A private test remote may exist next to `origin`; pushing there needs no extra permission, but the same content rules apply, because those commits are published later.
2. Check every commit that the push would publish, not only the last one: `git log -p origin/<branch>..HEAD`.
3. Never force-push to GitHub without the owner's explicit approval.

## If private data was committed

- **Not pushed to GitHub yet:** remove it from the history (amend or rebase the commit). A follow-up commit that deletes the value is not enough.
- **Already on GitHub:** stop and tell the owner at once. The value counts as leaked and must be changed at its source (new password, new token). Do not rewrite the published history on your own.
