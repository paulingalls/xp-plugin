# Angle: what this made reachable

One question, across the whole diff: what can now be reached that could not be
reached before? Whether there is anything here at all is this project's answer,
not the angle's — many changes have no such surface, and reporting nothing is a
normal, correct result. Report what you can trace to a caller, never a category.

- **Untrusted input reaching an interpreter**: a shell, a query language, a
  template, a deserializer, a path join, an eval, a regex built from input.
- **Write-then-execute**: anything the actor under review can WRITE that
  something else later EXECUTES or trusts — a config file, a hook, a bootstrap
  line, a dependency pin, a generated script, a cached credential.
- **Deny-lists where an allow-list was meant**, and exemptions that wave through
  the very file that enforces the rule.
- **Secrets and credentials**: newly logged, newly written to disk, newly
  committed, issued with no expiry and no clearer, or compared with `==`.
- **Authorization checked on one path and not its sibling**, or enforced by the
  caller only, so a second caller inherits nothing.
- **Trust boundaries the change moved**: data that used to be validated at the
  edge and is now consumed further in; a limit that moved from the server to the
  client; an identity taken from something the requester controls.

For each: the entry point, the path it travels, and what an actor gains at the
end of it.
