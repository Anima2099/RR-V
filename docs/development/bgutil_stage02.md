# RR-V 1.6.0 / Stage 02 / BgUtils independent validation

## Scope and upstream versions

- Official upstream: https://github.com/Brainicism/bgutil-ytdlp-pot-provider
- Verified latest stable release on 2026-10-30: 2.0.2 (published 2026-10-07)
- Pinned upstream commit: 26475e9d3665b972c4aeb83b4dbaafcf64b88438
- Official plugin ZIP SHA-256: a26b980bf6d8e8400d8f21445daa4d8381bf6183d20f0be309391f86b31e27ef
- Existing Deno 2.9.8 satisfies the upstream Deno 2.0+ requirement.
- The upstream server uses a local HTTP API with GET /ping and POST /get_pot.

## License gate: NOT APPROVED FOR DISTRIBUTION YET

LuanRT's base BgUtils library is MIT-licensed. However, Brainicism's
BgUtils POT Provider server package and plugin project are GPL-3.0-only.
RR-V core is RR-V Source Available License 1.0, not GPL-licensed.

Keep upstream source, native binaries, and GPL plugin files outside the
RR-V distribution while evaluating. An independent process and a loopback
HTTP API do not by themselves settle all combined-work and redistribution
questions. Stage 03 must resolve the distribution/compliance strategy
before bundling, integrating, or auto-installing this component to users.
If necessary, obtain qualified license advice.

This preliminary assessment is not a legal opinion.

## Run the isolated Windows test

In GitHub Desktop select develop/1.6.0 and Pull origin. Open VS Code and
run this one command in the PowerShell terminal:

~~~powershell
powershell -ExecutionPolicy Bypass -File .\tests\manual\bgutil_standalone_probe.ps1
~~~

The test:
1. Downloads official pinned source and a plugin release ZIP, checking the
   official plugin ZIP SHA-256, package version and license declaration.
2. Installs Deno dependencies into a uniquely named TEMP directory,
   using its own DENO_DIR cache and the upstream frozen lockfile.
3. Starts the server only on a temporary 127.0.0.1 port, not on 0.0.0.0.
4. Checks GET /ping reports 2.0.2.
5. Requests one anonymous PO Token directly via POST /get_pot. The token
   text is never printed in the terminal or written by this test script.
   Upstream server logs may nevertheless contain tokens.
6. Stops the test server and attempts to remove the TEMP workspace.

The test contacts GitHub, Deno/npm dependency sources and YouTube services.
It does not use RR-V cookies or change RR-V WPC or download settings.

To test server startup without requesting a token:

~~~powershell
powershell -ExecutionPolicy Bypass -File .\tests\manual\bgutil_standalone_probe.ps1 -SkipTokenGeneration
~~~

If debugging requires retaining files, append -KeepWorkspace.
Never share raw server logs without redacting tokens or sensitive values.

## What passing does and does not prove

PASS shows the pinned Deno provider can install, start locally and produce
an anonymous token on this Windows system. It does not guarantee that
YouTube streams will download, that the provider works with signed-in
cookies, or that WPC fallback and RR-V packaging are safe. Those checks
belong to Stage 03 and later steps, after legal distribution is resolved.
